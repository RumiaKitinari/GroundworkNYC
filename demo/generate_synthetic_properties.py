"""Generate a clearly synthetic NYC food-service property scenario inventory."""

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CURRENT = DATA / "integrated/current"
DESTINATION = DATA / "listings/synthetic_properties.csv"
SEED = 440
BOROUGH_COUNTS = {"Manhattan": (220, 22), "Brooklyn": (340, 34), "Queens": (270, 27),
                  "Bronx": (120, 12), "Staten Island": (50, 5)}
RENT_BOUNDS = {"Manhattan": (48, 650), "Brooklyn": (25, 230), "Queens": (24, 200),
               "Bronx": (20, 155), "Staten Island": (20, 135)}
SALE_BOUNDS = {"Manhattan": (500, 4800), "Brooklyn": (260, 2200), "Queens": (230, 1700),
               "Bronx": (180, 1350), "Staten Island": (180, 1150)}
# These are corridor scenario anchors, not a claim that every street in an NTA
# commands a prime retail rent. Luxury-only flagship corridors are excluded.
PRIME_ANCHORS = {
    "SoHo-Little Italy-Hudson Square": 374,
    "Midtown South-Flatiron-Union Square": 329,
    "Upper West Side (Central)": 296,
    "Upper East Side-Lenox Hill-Roosevelt Island": 268,
    "Financial District-Battery Park City": 204,
}
BOROUGH_SALE_BENCHMARK = {"Manhattan": 1410, "Brooklyn": 521, "Queens": 670,
                          "Bronx": 525, "Staten Island": 366}
MIN_RETAIL_DENSITY_SQFT_PER_SQ_MILE = 50000
MIN_RETAIL_AREA_SQFT = 15000
MAX_MODELED_DEPTH_FT = 110
FIELDS = (
    "property_id", "inventory_type", "transaction", "geoid", "borough", "neighborhood",
    "location_label", "latitude", "longitude", "location_precision", "corridor_tier",
    "corridor_context", "building_type", "floor", "ground_floor", "corner_position",
    "available_sqft", "frontage_ft", "condition", "former_food_use", "kitchen_status",
    "ventilation_status", "step_free_entry", "outdoor_space_potential", "restaurant_fit",
    "annual_rent_psf", "monthly_rent", "asking_price", "asking_price_psf",
    "estimated_market_rent_psf", "estimated_cap_rate", "reported_occupied_rent_psf",
    "rent_context_scope", "rent_context_year", "pricing_adjustment", "pricing_basis", "availability",
    "source_release", "generation_seed",
)


def number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp(value, low, high):
    return min(high, max(low, value))


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(part)
    return sha.hexdigest()


def weighted_median(values):
    ordered = sorted(values)
    total = sum(weight for _, weight in ordered)
    halfway = total / 2
    cumulative = 0
    for index, (value, weight) in enumerate(ordered):
        cumulative += weight
        if cumulative >= halfway:
            if cumulative == halfway and index + 1 < len(ordered):
                return (value + ordered[index + 1][0]) / 2
            return value
    raise ValueError("A neighborhood rent median requires positive source weights.")


def read_inputs(release):
    master_path = release / "master_tract_features.csv"
    geography_path = release / "geography/nyc_2020_census_tracts.geojson"
    with master_path.open(newline="", encoding="utf-8-sig") as stream:
        master = list(csv.DictReader(stream))
    geojson = json.loads(geography_path.read_text(encoding="utf-8"))
    geometry = {feature["properties"]["geoid"]: shape(feature["geometry"])
                for feature in geojson["features"]}
    eligible = defaultdict(list)
    rents = defaultdict(list)
    for row in master:
        rent = number(row.get("reported_median_monthly_rent_psf"))
        if rent is not None and 1 <= rent <= 75 and row.get("nta_code"):
            year = str(row.get("rent_reporting_year") or "").strip()
            weight = max(1, int(number(row.get("leased_storefronts")) or 1))
            rents[(row["borough"], row["nta_code"])].append((rent * 12, weight, year))
        retail_sqft = number(row.get("retail_area_sqft")) or 0
        land_sq_miles = number(row.get("land_area_sq_miles")) or 0
        retail_density = retail_sqft / land_sq_miles if land_sq_miles > 0 else 0
        commercial_presence = ((number(row.get("reported_storefront_property_count")) or 0) > 0
                               or (number(row.get("active_restaurant_count")) or 0) > 0)
        if (row.get("eligible_for_location_screening") == "True" and row.get("nta_code")
                and row["geoid"] in geometry and commercial_presence
                and retail_density >= MIN_RETAIL_DENSITY_SQFT_PER_SQ_MILE
                and retail_sqft >= MIN_RETAIL_AREA_SQFT):
            eligible[row["borough"]].append(row)
    return eligible, rents, geometry, {"master": digest(master_path), "geography": digest(geography_path)}


def weighted_sample(rows, count, rng):
    if len(rows) < count:
        raise ValueError(f"Only {len(rows)} eligible commercial tracts for a {count}-property quota.")
    def key(row):
        storefronts = number(row.get("reported_storefront_property_count")) or 0
        restaurants = number(row.get("active_restaurant_count")) or 0
        retail_sqft = number(row.get("retail_area_sqft")) or 0
        weight = 1 + .8 * math.log1p(storefronts) + .45 * math.sqrt(restaurants) + .25 * math.log1p(retail_sqft / 1000)
        return rng.random() ** (1 / weight)
    return sorted(rows, key=key, reverse=True)[:count]


def context_and_rate(tract, nta_rents, rng, sqft, floor, corner, condition):
    borough, name = tract["borough"], tract["nta_name"]
    local = nta_rents.get((borough, tract["nta_code"]), [])
    latest_year = max((entry[2] for entry in local), default="")
    latest_local = [entry for entry in local if entry[2] == latest_year]
    borough_fallback = {"Manhattan": 106, "Brooklyn": 48, "Queens": 48, "Bronx": 48, "Staten Island": 36}[borough]
    neighborhood = (weighted_median([(rate, weight) for rate, weight, _ in latest_local])
                    if len(latest_local) >= 2 else borough_fallback)
    reported = number(tract.get("reported_median_monthly_rent_psf"))
    if reported is not None and 1 <= reported <= 75:
        tract_annual = clamp(reported * 12, neighborhood * .55, neighborhood * 1.8)
        anchor, scope = .45 * tract_annual + .55 * neighborhood, "tract_and_neighborhood"
        year = str(tract.get("rent_reporting_year") or latest_year)
    else:
        anchor, scope = neighborhood, "neighborhood" if len(latest_local) >= 2 else "borough_fallback"
        year = latest_year if scope == "neighborhood" else ""
    prime_neighborhood = borough == "Manhattan" and name in PRIME_ANCHORS
    tier = rng.choices(("secondary", "neighborhood_main", "prime_retail"),
                       weights=(36, 50, 14) if prime_neighborhood else (49, 48, 3))[0]
    if tier == "prime_retail" and name in PRIME_ANCHORS:
        anchor = PRIME_ANCHORS[name]
        scope = "published_corridor_scenario"
        year = "2026"
        tier_factor = rng.uniform(.83, 1.12)
    else:
        tier_factor = {"secondary": .78, "neighborhood_main": 1.12,
                       "prime_retail": 1.68}[tier]
    condition_factor = {"Shell": .88, "Buildout-Ready": 1.0, "Second-Generation": 1.11}[condition]
    size_factor = clamp((1800 / sqft) ** .10, .82, 1.19)
    rate = anchor * 1.10 * tier_factor * condition_factor * size_factor
    rate *= .64 if floor == "Second" else 1.09 if corner else 1
    rate *= rng.lognormvariate(0, .12)
    lower, upper = RENT_BOUNDS[borough]
    adjustment = "rent_floor" if rate < lower else "rent_ceiling" if rate > upper else "none"
    rate = clamp(rate, lower, upper)
    context = {"secondary": "Secondary commercial street scenario",
               "neighborhood_main": "Neighborhood retail corridor scenario",
               "prime_retail": "Prime retail corridor scenario"}[tier]
    return money(rate), tier, context, scope, money(reported * 12) if reported else "", adjustment, year


def make_property(tract, geometry, nta_rents, transaction, index, rng, release_name, seed):
    borough = tract["borough"]
    central = {"Manhattan": 1500, "Brooklyn": 1750, "Queens": 1800,
               "Bronx": 1950, "Staten Island": 2150}[borough]
    sqft = int(clamp(round(rng.lognormvariate(math.log(central), .43) / 25) * 25, 500, 6500))
    floor = "Ground" if transaction == "purchase" or rng.random() < .95 else "Second"
    corner = floor == "Ground" and rng.random() < .19
    former = floor == "Ground" and rng.random() < .24
    condition = rng.choices(("Second-Generation", "Buildout-Ready", "Shell"),
                            weights=(60, 34, 6) if former else (0, 60, 40))[0]
    if transaction == "purchase":
        building = ("Stand-Alone Retail" if borough in {"Staten Island", "Queens", "Bronx"}
                    and rng.random() < .28 else "Retail Condominium")
    else:
        building = ("Stand-Alone Retail" if borough in {"Staten Island", "Queens", "Bronx"}
                    and rng.random() < .28 else "Mixed-Use Storefront")
    frontage = math.ceil(clamp(max(sqft / MAX_MODELED_DEPTH_FT,
                                   math.sqrt(sqft) * (.52 if corner else .42) * rng.uniform(.90, 1.20)), 12, 80))
    rate, tier, context, scope, reported, adjustment, rent_year = context_and_rate(
        tract, nta_rents, rng, sqft, floor, corner, condition)
    kitchen = "Existing Fit-Out Assumed" if former else "Build-Out Required"
    vent = "Existing System Assumed; Verify" if former and rng.random() < .68 else "Feasibility Unverified"
    step_free = floor == "Ground" and rng.random() < .79
    outdoor = "Potential Sidewalk Space; Permit Unverified" if floor == "Ground" and frontage >= 17 and rng.random() < .38 else "Not Assumed"
    fit = "Higher Potential; Verify Utilities And Permits" if former and vent.startswith("Existing") else "Feasibility Review Required"
    if scope == "published_corridor_scenario":
        pricing_basis = "2026 published corridor asking-rent anchor + simulated adjustments"
    elif scope == "borough_fallback":
        pricing_basis = "Modeled borough rent baseline + 2026 market calibration; simulated assumptions"
    else:
        dof_context = f"{rent_year} NYC DOF" if rent_year else "NYC DOF"
        pricing_basis = f"{dof_context} occupied rent context + 2026 market calibration; simulated assumptions"
    point = geometry.representative_point()
    # Approximate tract point, deliberately not a purported storefront entrance.
    location = (round(point.y, 5), round(point.x, 5))
    row = dict.fromkeys(FIELDS, "")
    row.update(property_id=f"GW-SYN-{index:04d}", inventory_type="synthetic_demonstration",
               transaction=transaction, geoid=tract["geoid"], borough=borough,
               neighborhood=tract["nta_name"],
               location_label=f"{tract['nta_name']}, {borough} (Approximate Area)",
               latitude=location[0], longitude=location[1], location_precision="tract_approximate",
               corridor_tier=tier, corridor_context=context, building_type=building,
               floor=floor, ground_floor=str(floor == "Ground").lower(), corner_position=str(corner).lower(),
               available_sqft=sqft, frontage_ft=frontage, condition=condition,
               former_food_use=str(former).lower(), kitchen_status=kitchen, ventilation_status=vent,
               step_free_entry="Assumed" if step_free else "Unverified",
               outdoor_space_potential=outdoor, restaurant_fit=fit,
               estimated_market_rent_psf=rate, reported_occupied_rent_psf=reported,
               rent_context_scope=scope, rent_context_year=rent_year,
               pricing_adjustment=adjustment,
               pricing_basis=pricing_basis,
               availability="Scenario Only; Not An Available Listing",
               source_release=release_name, generation_seed=seed)
    if transaction == "lease":
        row["annual_rent_psf"] = rate
        row["monthly_rent"] = money(rate * sqft / 12)
    else:
        cap = {"Manhattan": .052, "Brooklyn": .061, "Queens": .067,
               "Bronx": .072, "Staten Island": .075}[borough] * rng.uniform(.88, 1.13)
        net_rent_share = rng.uniform(.57, .69)
        raw_sale_psf = float(rate) * net_rent_share / cap
        lower, upper = SALE_BOUNDS[borough]
        if raw_sale_psf < lower or raw_sale_psf > upper:
            sale_adjustment = "sale_floor" if raw_sale_psf < lower else "sale_ceiling"
            row["pricing_adjustment"] = (sale_adjustment if adjustment == "none"
                                         else f"{adjustment}+{sale_adjustment}")
        sale_psf = round(clamp(raw_sale_psf, lower, upper))
        row["asking_price_psf"] = sale_psf
        row["asking_price"] = sale_psf * sqft
        row["estimated_cap_rate"] = money(float(rate) * net_rent_share / sale_psf)
    return row


def generate(release=CURRENT, seed=SEED):
    release = Path(release).resolve()
    rng = random.Random(seed)
    eligible, rents, geometry, fingerprints = read_inputs(release)
    rows = []
    for borough, (count, purchases) in BOROUGH_COUNTS.items():
        tracts = weighted_sample(eligible[borough], count, rng)
        rng.shuffle(tracts)
        for position, tract in enumerate(tracts):
            transaction = "purchase" if position < purchases else "lease"
            rows.append(make_property(tract, geometry[tract["geoid"]], rents, transaction,
                                      len(rows) + 1, rng, release.name, seed))
    selected_tracts = {tract["geoid"]: tract for tracts in eligible.values() for tract in tracts}
    validate(rows, geometry, selected_tracts)
    return rows, {"seed": seed, "source_release": release.name, "source_sha256": fingerprints,
                  "benchmarks": benchmark_summary(rows), "summary": summarize(rows),
                  "pricing_adjustments": dict(Counter(row["pricing_adjustment"] for row in rows)),
                  "quality_audit": {
                      "minimum_retail_density_sqft_per_sq_mile": MIN_RETAIL_DENSITY_SQFT_PER_SQ_MILE,
                      "minimum_retail_area_sqft": MIN_RETAIL_AREA_SQFT,
                      "maximum_modeled_depth_ft": round(max(int(row["available_sqft"]) / float(row["frontage_ft"])
                                                         for row in rows), 2),
                      "rent_context_scopes": dict(Counter(row["rent_context_scope"] for row in rows)),
                      "second_floor_scenarios": sum(row["floor"] == "Second" for row in rows),
                      "saleable_purchase_assets": sum(row["transaction"] == "purchase" and row["building_type"]
                                                      in {"Retail Condominium", "Stand-Alone Retail"} for row in rows),
                  }}


def validate(rows, geometry, selected_tracts=None):
    from shapely.geometry import Point
    if len(rows) != 1000 or len({row["property_id"] for row in rows}) != 1000:
        raise ValueError("Synthetic inventory must have exactly 1,000 unique property IDs.")
    if len({row["geoid"] for row in rows}) != 1000:
        raise ValueError("Property scenarios must use distinct NYC tracts.")
    for borough, (count, purchases) in BOROUGH_COUNTS.items():
        subset = [row for row in rows if row["borough"] == borough]
        if len(subset) != count or sum(row["transaction"] == "purchase" for row in subset) != purchases:
            raise ValueError(f"Incorrect scenario allocation for {borough}.")
        sale_median = statistics.median(int(row["asking_price_psf"]) for row in subset if row["transaction"] == "purchase")
        if not .4 <= sale_median / BOROUGH_SALE_BENCHMARK[borough] <= 1.6:
            raise ValueError(f"{borough} sale scenarios diverge from published market checks.")
    for row in rows:
        if selected_tracts is not None:
            tract = selected_tracts[row["geoid"]]
            land_sq_miles = number(tract.get("land_area_sq_miles")) or 0
            retail_density = (number(tract.get("retail_area_sqft")) or 0) / land_sq_miles if land_sq_miles > 0 else 0
            if (retail_density < MIN_RETAIL_DENSITY_SQFT_PER_SQ_MILE
                    or (number(tract.get("retail_area_sqft")) or 0) < MIN_RETAIL_AREA_SQFT):
                raise ValueError(f"Scenario is not in a supported commercial tract: {row['property_id']}")
        if any(value is None or value == "" for key, value in row.items()
               if key not in {"annual_rent_psf", "monthly_rent", "asking_price", "asking_price_psf",
                              "estimated_cap_rate", "reported_occupied_rent_psf", "rent_context_year"}):
            raise ValueError(f"Missing required scenario attribute: {row['property_id']}")
        if row["inventory_type"] != "synthetic_demonstration" or row["location_precision"] != "tract_approximate":
            raise ValueError("Synthetic provenance and approximate-location label are required.")
        if not geometry[row["geoid"]].buffer(.00002).covers(Point(float(row["longitude"]), float(row["latitude"]))):
            raise ValueError(f"Approximate point is outside its census tract: {row['property_id']}")
        sqft = int(row["available_sqft"])
        if not 500 <= sqft <= 6500 or row["floor"] == "Second" and row["ground_floor"] != "false":
            raise ValueError(f"Implausible physical attributes: {row['property_id']}")
        frontage = float(row["frontage_ft"])
        if not 12 <= frontage <= 80 or sqft / frontage > MAX_MODELED_DEPTH_FT + 2:
            raise ValueError(f"Implausible storefront frontage or depth: {row['property_id']}")
        if row["floor"] == "Second" and (row["former_food_use"] == "true" or row["outdoor_space_potential"] != "Not Assumed"):
            raise ValueError(f"Second-floor scenario has ground-floor features: {row['property_id']}")
        if row["condition"] == "Second-Generation" and row["former_food_use"] != "true":
            raise ValueError(f"Second-generation restaurant without former food use: {row['property_id']}")
        rent_psf = Decimal(str(row["estimated_market_rent_psf"]))
        if not RENT_BOUNDS[row["borough"]][0] <= rent_psf <= RENT_BOUNDS[row["borough"]][1]:
            raise ValueError(f"Rent outside borough review envelope: {row['property_id']}")
        if row["transaction"] == "lease":
            if row["asking_price"] or row["asking_price_psf"] or row["estimated_cap_rate"]:
                raise ValueError("Lease scenario contains a purchase valuation.")
            if money(Decimal(str(row["annual_rent_psf"])) * sqft / 12) != Decimal(str(row["monthly_rent"])):
                raise ValueError(f"Lease arithmetic mismatch: {row['property_id']}")
        else:
            if row["annual_rent_psf"] or row["monthly_rent"]:
                raise ValueError("Purchase scenario contains a lease asking rent.")
            if row["building_type"] not in {"Retail Condominium", "Stand-Alone Retail"}:
                raise ValueError(f"Purchase scenario lacks a saleable asset type: {row['property_id']}")
            price_psf = int(row["asking_price_psf"])
            if not SALE_BOUNDS[row["borough"]][0] <= price_psf <= SALE_BOUNDS[row["borough"]][1]:
                raise ValueError(f"Sale valuation outside borough review envelope: {row['property_id']}")
            if int(row["asking_price"]) != price_psf * sqft:
                raise ValueError(f"Purchase arithmetic mismatch: {row['property_id']}")
    if sum(row["transaction"] == "lease" for row in rows) != 900:
        raise ValueError("Inventory must have exactly 900 lease scenarios.")
    if sum(row["pricing_adjustment"].startswith("rent_floor") for row in rows) > 80:
        raise ValueError("Too many rents required lower-bound correction; recalibrate the model.")
    if sum("sale_floor" in row["pricing_adjustment"] or "sale_ceiling" in row["pricing_adjustment"]
           for row in rows) > 10:
        raise ValueError("Too many sale prices required envelope correction; recalibrate the model.")
    soho = [float(row["annual_rent_psf"]) for row in rows if row["transaction"] == "lease" and "SoHo" in row["neighborhood"]]
    queens = [float(row["annual_rent_psf"]) for row in rows if row["transaction"] == "lease" and row["borough"] == "Queens"]
    if not soho or statistics.median(soho) < 2 * statistics.median(queens):
        raise ValueError("SoHo scenarios must materially exceed typical Queens rents.")


def summarize(rows):
    summary = {"total": len(rows), "lease": sum(row["transaction"] == "lease" for row in rows),
               "purchase": sum(row["transaction"] == "purchase" for row in rows),
               "borough_counts": dict(Counter(row["borough"] for row in rows))}
    for key, source in (("sqft", "available_sqft"), ("annual_rent_psf", "annual_rent_psf"),
                        ("monthly_rent", "monthly_rent"), ("asking_price_psf", "asking_price_psf"),
                        ("asking_price", "asking_price")):
        values = sorted(float(row[source]) for row in rows if row[source] != "")
        summary[key] = {"min": round(values[0], 2), "median": round(statistics.median(values), 2),
                        "p90": round(values[int(.9 * (len(values) - 1))], 2), "max": round(values[-1], 2)}
    summary["neighborhoods"] = len({(row["borough"], row["neighborhood"]) for row in rows})
    return summary


def benchmark_summary(rows):
    result = {}
    for borough in BOROUGH_COUNTS:
        subset = [row for row in rows if row["borough"] == borough]
        leases = sorted((row for row in subset if row["transaction"] == "lease"),
                        key=lambda row: float(row["annual_rent_psf"]))
        sales = sorted((row for row in subset if row["transaction"] == "purchase"),
                       key=lambda row: int(row["asking_price_psf"]))
        result[borough] = {
            "lease_annual_psf_median": round(statistics.median(float(row["annual_rent_psf"]) for row in leases), 2),
            "sale_psf_median": round(statistics.median(int(row["asking_price_psf"]) for row in sales)),
            "sale_market_reference_psf": BOROUGH_SALE_BENCHMARK[borough],
            "lease_examples": [{"property_id": row["property_id"], "neighborhood": row["neighborhood"],
                                "corridor_tier": row["corridor_tier"], "annual_rent_psf": str(row["annual_rent_psf"]),
                                "reported_occupied_rent_psf": str(row["reported_occupied_rent_psf"])}
                               for row in (leases[len(leases) // 10], leases[len(leases) // 2], leases[9 * len(leases) // 10])],
            "sale_examples": [{"property_id": row["property_id"], "neighborhood": row["neighborhood"],
                               "asking_price_psf": row["asking_price_psf"],
                               "estimated_cap_rate": str(row["estimated_cap_rate"])}
                              for row in (sales[len(sales) // 10], sales[len(sales) // 2],
                                          sales[9 * len(sales) // 10])],
        }
    return result


def publish(output, rows, manifest, replace=False):
    output = Path(output)
    audit = output.with_suffix(".manifest.json")
    if (output.exists() or audit.exists()) and not replace:
        raise FileExistsError("Synthetic dataset exists; pass --replace to regenerate it intentionally.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(output)
    manifest["csv_sha256"] = digest(output)
    audit.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


@lru_cache(maxsize=4)
def _read_published(path, csv_mtime, manifest_mtime):
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if digest(path) != manifest.get("csv_sha256"):
        raise ValueError("Synthetic property inventory checksum does not match its validation manifest.")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError("Synthetic property inventory schema changed.")
        rows = tuple(reader)
    if (len(rows) != 1000 or len({row["property_id"] for row in rows}) != 1000
            or sum(row["transaction"] == "lease" for row in rows) != 900
            or sum(row["transaction"] == "purchase" for row in rows) != 100
            or any(row["inventory_type"] != "synthetic_demonstration" for row in rows)):
        raise ValueError("Synthetic property inventory did not pass publication checks.")
    return rows


def load_published_inventory(path=DESTINATION):
    path = Path(path).resolve()
    manifest_path = path.with_suffix(".manifest.json")
    if not path.exists() and not manifest_path.exists():
        return ()
    return _read_published(path, path.stat().st_mtime_ns, manifest_path.stat().st_mtime_ns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=CURRENT)
    parser.add_argument("--output", type=Path, default=DESTINATION)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    rows, report = generate(args.release, args.seed)
    publish(args.output, rows, report, replace=args.replace)
    print(json.dumps({"output": str(args.output), **report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
