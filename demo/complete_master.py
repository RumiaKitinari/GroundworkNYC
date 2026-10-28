"""Finish current-context features without fabricating source values or outcomes."""

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from datetime import date
from statistics import median

import numpy as np

from enrich_location_data import number, ratio, read_csv, register, write_csv
from evaluation import fingerprint


def zip722_index(rows):
    result = {}
    for row in rows:
        if row["naics"].replace("/", "").replace("-", "") != "722":
            continue
        if row["zip"] in result:
            raise ValueError("Duplicate ZIP/NAICS-722 total")
        result[row["zip"]] = number(row["est"])
    return result


def postal_and_license_context(stage, master, data):
    from refresh_integrated import raw_revision, COUNTY_BY_BOROUGH_NUMBER
    from match_sla_lifespan_leads import normalized_address, COUNTY_TO_BOROUGH
    import csv
    known = {r["geoid"] for r in master}
    # No external geocoder: require an unambiguous exact normalized source address.
    generic_home = data / "raw_sources/sla_active_context"
    if (generic_home / "manifest.json").exists():
        generic = json.loads((generic_home / "manifest.json").read_text())["revisions"][-1]
        entry = generic["files"][0]
        license_path = generic_home / generic["directory"] / entry["file"]
        manifest = {"downloaded_at": generic["downloaded_at"],
                    "files": {"active": {"sha256": entry["sha256"], "dataset_url": "https://data.ny.gov/d/9s3h-dpkz"}}}
    else:
        home = data / "raw_sources/sla_licenses"
        manifest = json.loads((home / "manifest.json").read_text())
        license_path = home / manifest["revision"] / "active.csv"
    if fingerprint(license_path) != manifest["files"]["active"]["sha256"]:
        raise ValueError("SLA active source checksum mismatch")
    licenses = read_csv(license_path)
    categories = {"Restaurant", "Summer Restaurant", "Catering Establishment", "Hotel", "Club", "Cabaret"}
    selected = [r for r in licenses if r["description"] in categories and r["premisescounty"].lower().strip() in COUNTY_TO_BOROUGH]
    addresses_needed = set()
    for row in selected:
        borough = COUNTY_TO_BOROUGH.get(row["premisescounty"].lower().strip(), "")
        addresses_needed.add((borough, *normalized_address(row["actualaddressofpremises"], row["zipcode"], borough)))
    address_geoids = defaultdict(set)
    parcel_zip = defaultdict(Counter)
    raw, revision = raw_revision("pluto")
    seen = set()
    borough_names = {"1": "manhattan", "2": "bronx", "3": "brooklyn", "4": "queens", "5": "staten island"}
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            bbl, bct = row.get("bbl", ""), row.get("bct2020", "")
            if bbl in seen:
                continue
            seen.add(bbl)
            geoid = "36" + COUNTY_BY_BOROUGH_NUMBER.get(bct[:1], "") + bct[1:]
            if geoid not in known:
                continue
            zip_code = row.get("zipcode", "").strip()
            if len(zip_code) != 5 or not zip_code.isdigit():
                continue
            parcel_zip[geoid][zip_code] += 1
            borough = borough_names.get(bct[:1], "")
            key = (borough, *normalized_address(row.get("address", ""), zip_code, borough))
            if key in addresses_needed:
                address_geoids[key].add(geoid)
    for filename, address_field, zip_field in (("entities/current_restaurants.csv", "", "zipcode"),
                                                ("entities/current_storefronts.csv", "property_street_address_or", "zip_code")):
        for row in read_csv(stage / filename):
            geoid = row.get("geoid", "")
            if geoid not in known:
                continue
            county_to_digit = {"061": "1", "005": "2", "047": "3", "081": "4", "085": "5"}
            borough = borough_names.get(county_to_digit.get(geoid[2:5]), "")
            street = row.get(address_field, "") if address_field else " ".join((row.get("building", ""), row.get("street", "")))
            key = (borough, *normalized_address(street, row.get(zip_field, ""), borough))
            if key in addresses_needed:
                address_geoids[key].add(geoid)
    counts, ages, seen_license, stats = Counter(), defaultdict(list), set(), Counter()
    retrieved = date.fromisoformat(manifest["downloaded_at"][:10])
    for row in selected:
        key_id = row["licensepermitid"]
        if not key_id or key_id in seen_license:
            continue
        seen_license.add(key_id)
        borough = COUNTY_TO_BOROUGH.get(row["premisescounty"].lower().strip(), "")
        key = (borough, *normalized_address(row["actualaddressofpremises"], row["zipcode"], borough))
        locations = address_geoids.get(key, set())
        if len(locations) != 1:
            stats["ambiguous" if locations else "unmatched"] += 1
            continue
        geoid = next(iter(locations))
        counts[geoid] += 1
        stats["matched"] += 1
        try:
            issued = date.fromisoformat(row["originalissuedate"][:10])
            if issued <= retrieved:
                ages[geoid].append((retrieved-issued).days/365.2425)
        except ValueError:
            pass
    vintage = next(r["vintage"] for r in read_csv(stage / "source_catalog.csv") if r["source"] == "Census Business Patterns")
    if vintage != "2023":
        raise ValueError("ZIP comparison schema is pinned to 2023; explicitly version a newer comparison")
    latest = zip722_index(read_csv(stage / "features/zip_food_service_business_patterns.csv"))
    old_path = stage / "features/zip_food_service_business_patterns_2015.csv"
    old = zip722_index(read_csv(old_path)) if old_path.exists() else {}
    definitions = {
        "dominant_property_zipcode": ("Most frequent PLUTO property ZIP among uniquely counted tax lots in the tract; ties resolved by ZIP order. NOT a centroid ZIP or ZCTA polygon crosswalk.", "5-digit property ZIP"),
        "dominant_zip_property_share": ("Fraction of tax lots with a valid ZIP that use the dominant property ZIP; not a tract area or resident share.", "share"),
        "food_drink_estabs_dominant_zip_2023": ("Published NAICS-722 total for dominant property ZIP. Whole-ZIP context, NOT tract establishments; repeated ZIP totals must not be summed across tracts.", "establishments/ZIP"),
        "food_drink_estabs_dominant_zip_2015": ("Published 2015 NAICS-722 total for dominant current property ZIP. Whole-ZIP context, not tract counts or fixed historical boundaries.", "establishments/ZIP"),
        "food_drink_dominant_zip_growth_2015_2023": ("2023 ZIP NAICS-722 establishments divided by 2015 total minus one, only when both published and baseline positive. Postal and industry changes limit comparability.", "relative change (not percentage points)"),
        "matched_restaurant_hospitality_sla_license_count": ("Active SLA licenses classified as Restaurant, Summer Restaurant, Catering Establishment, Hotel, Club or Cabaret with unique exact-address tract matches; lower-bound coverage, not all on-premises licenses.", "matched licenses"),
        "matched_restaurant_hospitality_sla_licenses_per_sq_mile": ("Matched restaurant/hospitality SLA licenses divided by tract land area. Zero means no exact matches, not verified absence of licenses.", "matched licenses/sq mi"),
        "matched_restaurant_hospitality_sla_median_age_years": ("Median years since original issue among exact-address matched selected active license classes, measured at source download date; not restaurant age.", "years"),
    }
    records, links = [], []
    for row in master:
        zips = parcel_zip[row["geoid"]]
        dominant = sorted(zips, key=lambda z: (-zips[z], z))[0] if zips else ""
        a, b = latest.get(dominant), old.get(dominant)
        records.append({"geoid": row["geoid"], "dominant_property_zipcode": dominant,
                        "dominant_zip_property_share": zips[dominant]/sum(zips.values()) if dominant else "",
                        "food_drink_estabs_dominant_zip_2023": a if a is not None else "",
                        "food_drink_estabs_dominant_zip_2015": b if b is not None else "",
                        "food_drink_dominant_zip_growth_2015_2023": a/b-1 if a is not None and b and b > 0 else "",
                        "matched_restaurant_hospitality_sla_license_count": counts[row["geoid"]],
                        "matched_restaurant_hospitality_sla_licenses_per_sq_mile": ratio(counts[row["geoid"]], number(row.get("land_area_sq_miles"))),
                        "matched_restaurant_hospitality_sla_median_age_years": median(ages[row["geoid"]]) if ages[row["geoid"]] else ""})
        links.extend({"geoid": row["geoid"], "property_zip": z, "parcel_count": n,
                      "share_of_zip_coded_parcels": n/sum(zips.values())} for z, n in sorted(zips.items()))
    result = register(stage, master, "features/tract_postal_license_context.csv", records, definitions,
                      "Property ZIP and matched SLA context", {"publisher_version": revision["publisher_version"] + "; SLA " + manifest["downloaded_at"][:10],
                        "source_url": manifest["files"]["active"]["dataset_url"]}, "property ZIP and matched license address",
                      "Current commercial context", "Dominant property ZIP is a proxy; license counts have partial exact-address coverage. Neither supplies closure outcomes.")
    filename = "geography/tract_property_zip_crosswalk.csv"
    write_csv(stage / filename, links, ("geoid", "property_zip", "parcel_count", "share_of_zip_coded_parcels"))
    result["_qa_files"].append(filename)
    result.update({"license_matching": dict(stats), "license_source_sha256": manifest["files"]["active"]["sha256"],
                   "tracts_with_property_zip": sum(bool(r["dominant_property_zipcode"]) for r in records)})
    return result


def refine_dictionary_units(stage):
    """Replace legacy generic units only where the source quantity is explicit."""
    units = {
        "geoid": "11-digit GEOID", "tract_code": "6-digit tract code", "tract_label": "tract label",
        "borough": "borough name", "nta_code": "NTA code", "nta_name": "NTA name",
        "community_district_code": "community district code", "community_district_name": "community district name",
        "centroid_latitude": "degrees north", "centroid_longitude": "degrees east",
        "land_area_sq_miles": "sq mi", "total_jobs": "jobs", "job_density_per_sq_mile": "jobs/sq mi",
        "walkability_population_weight": "area-allocated EPA population weight",
        "national_walkability_index": "EPA index (1-20)", "smart_location_score": "EPA SLC_score index",
        "average_latest_inspection_score": "DOHMH inspection points", "average_latest_critical_violations": "critical violations/restaurant",
        "nearest_subway_distance_miles": "miles", "nearest_citibike_distance_miles": "miles",
        "nearest_pedestrian_count_site_distance_miles": "miles",
        "nearest_pedestrian_count_site_latest_pedestrian_count_total": "pedestrians in source observation window",
        "nearest_pedestrian_count_site_loc": "source site identifier (legacy alias)",
        "taxi_borough": "borough name", "taxi_zone": "TLC zone name", "taxi_service_zone": "TLC service zone",
        "food_nightlife_pois_per_1000_residents": "POIs/1,000 residents", "jobs_per_1000_residents": "jobs/1,000 residents",
        "food_nightlife_poi_per_sq_mile": "POIs/sq mi", "cuisine_categories": "distinct tagged cuisine categories",
        "eligible_for_location_screening": "boolean",
        "reported_storefront_property_count": "registered BBL properties",
        "reported_vacant_storefront_count": "registered BBL properties with reported vacancy",
    }
    path = stage / "data_dictionary.csv"
    rows = read_csv(path)
    changed = set()
    for row in rows:
        if row["unit"] != "varies":
            continue
        key = row["column"]
        unit = units.get(key)
        if unit is None:
            if key.endswith("_id") or key.endswith("_objectid"):
                unit = "source identifier"
            elif key.endswith("_name") or key == "nearest_subway_station_complex":
                unit = "source location name"
            elif key.endswith("_share"):
                unit = "share"
            elif key.startswith("jobs_"):
                unit = "jobs"
            elif "ridership" in key or "transfers" in key:
                unit = "entries/week" if "ridership" in key else "transfers/week"
            elif "departures" in key or "arrivals" in key:
                unit = "trips/source month"
            elif key.startswith(("pickups_", "dropoffs_")):
                unit = "trips/source month (whole TLC zone context; nonadditive across tracts)"
            elif key.startswith("cbd_congestion_fee_"):
                unit = "USD/source month (whole TLC zone context; nonadditive across tracts)"
            elif key.startswith("active_days_"):
                unit = "days/source month"
            elif key.endswith("_sqft"):
                unit = "sq ft"
            elif "_count" in key or key in {"restaurants_with_current_score", "subway_station_complex_count"}:
                unit = "records or entities as defined"
            elif key.startswith("permitted_event_hours"):
                unit = "permitted event-hours/source window (community district context)"
            elif key.startswith(("first_event_date", "last_event_date")):
                unit = "YYYY-MM-DD"
        if unit:
            row["unit"] = unit
            changed.add(key)
    write_csv(path, rows, ("file", "column", "definition", "unit"))
    return sorted(changed)


def epa_context(stage, master):
    from refresh_integrated import raw_revision
    from rebuild_epa import ogr_csv, geometry, NYC_COUNTIES
    from shapely.strtree import STRtree
    raw, revision = raw_revision("epa_walkability")
    raw_sha = fingerprint(raw)
    cache = stage / "epa_additional_provenance.json"
    table = stage / "features/tract_epa_additional_context.csv"
    geometry_sha = fingerprint(stage / "geography/nyc_2020_census_tracts.geojson")
    provenance = {"raw_sha256": raw_sha, "geometry_sha256": geometry_sha}
    if cache.exists() and table.exists() and json.loads(cache.read_text()) == provenance:
        values = read_csv(table)
    else:
        tracts = ogr_csv(stage / "geography/nyc_2020_census_tracts.geojson", fields=["geoid"])
        polygons = [geometry(r) for r in tracts]
        tree = STRtree(polygons)
        counties = ",".join(f"'{c}'" for c in NYC_COUNTIES)
        groups = ogr_csv("/vsizip/" + str(raw.resolve()) + "/SmartLocationDatabase.gdb", "EPA_SLD_Database_V3",
                         fields=["GEOID10", "D3B", "D4C"], where=f"STATEFP='36' AND COUNTYFP IN ({counties})")
        if len(groups) < 6000:
            raise ValueError("Incomplete EPA NYC block group coverage")
        totals = defaultdict(lambda: defaultdict(float))
        for group in groups:
            polygon = geometry(group)
            for index in tree.query(polygon):
                area = polygon.intersection(polygons[index]).area
                if area <= 0:
                    continue
                target = totals[tracts[index]["geoid"]]
                for field in ("D3B", "D4C"):
                    value = number(group.get(field))
                    if value is not None:
                        target[field] += value * area
                        target[field + "_area"] += area
        values = [{"geoid": r["geoid"], "epa_intersection_density": ratio(totals[r["geoid"]]["D3B"], totals[r["geoid"]]["D3B_area"]),
                   "epa_transit_frequency": ratio(totals[r["geoid"]]["D4C"], totals[r["geoid"]]["D4C_area"])} for r in master]
    definitions = {"epa_intersection_density": ("EPA SLD v3 D3B weighted pedestrian-oriented intersection density; projected-overlap-area-weighted mean of source block groups in 2020 tract. Not a current street count.", "weighted intersections/sq mi"),
                   "epa_transit_frequency": ("EPA SLD v3 D4C aggregate transit-service frequency near source block-group boundaries during evening peak; projected-overlap-area-weighted mean. Source-era service, not a current GTFS schedule.", "services/hour (source-era area-weighted mean)")}
    result = register(stage, master, "features/tract_epa_additional_context.csv", values, definitions,
                      "EPA intersections and transit context", revision, "EPA source block groups crosswalked to 2020 tracts",
                      "built environment context", "EPA SLD v3 vintage; source-era context only. Do not interpret as contemporary transit schedules.")
    cache.write_text(json.dumps(provenance, indent=2) + "\n")
    return result


def geographic_rent_predictions(train, queries, method):
    predictions = []
    for row in queries:
        donors = [r for r in train if r["borough"] == row["borough"]] or train
        if not donors:
            raise ValueError("No reported rent donors")
        rents = np.array([float(r["reported_median_monthly_rent_psf"]) for r in donors])
        if method == "borough_median":
            predictions.append(float(np.median(rents)))
            continue
        # Local UTM-like distances suffice for donor ranking within NYC.
        distances = np.array([math.hypot((float(r["centroid_latitude"])-float(row["centroid_latitude"]))*111.32,
                             (float(r["centroid_longitude"])-float(row["centroid_longitude"]))*84.3) for r in donors])
        nearest = np.argsort(distances)[:5]
        weights = 1 / np.maximum(distances[nearest], .1)
        predictions.append(float(np.exp(np.average(np.log(rents[nearest]), weights=weights))))
    return predictions


def rent_estimates(master):
    from sklearn.model_selection import GroupKFold
    donors = [row for row in master if number(row.get("reported_median_monthly_rent_psf")) not in (None, 0)]
    groups = [r["nta_code"] or r["geoid"] for r in donors]
    folds = min(5, len(set(groups)))
    if folds < 2:
        raise ValueError("Rent estimation requires at least two neighborhood groups")
    metrics = {}
    for method in ("borough_median", "local_log_idw_5"):
        errors, percentage_errors = [], []
        for training, test in GroupKFold(n_splits=folds).split(donors, groups=groups):
            a, b = [donors[i] for i in training], [donors[i] for i in test]
            for row, prediction in zip(b, geographic_rent_predictions(a, b, method)):
                actual = float(row["reported_median_monthly_rent_psf"])
                errors.append(abs(prediction-actual))
                percentage_errors.append(abs(prediction-actual)/actual)
        metrics[method] = {"mean_absolute_error_monthly_psf": float(np.mean(errors)),
                           "median_absolute_percentage_error": float(np.median(percentage_errors)), "held_out_rows": len(errors)}
    selected = min(metrics, key=lambda k: metrics[k]["mean_absolute_error_monthly_psf"])
    missing = [r for r in master if number(r.get("reported_median_monthly_rent_psf")) is None]
    estimates = dict(zip((r["geoid"] for r in missing), geographic_rent_predictions(donors, missing, selected)))
    return estimates, {"method_selected": selected, "validation": metrics, "folds": folds,
                       "split": "NTA-disjoint GroupKFold; method selection only, not independent final test",
                       "warning": "Cross-validation covers observed tracts only; missing coverage may differ. Estimates are current area context, not asking rents or survival predictors."}


def allocate_zone_counts(crosswalk, zones, known):
    totals = defaultdict(lambda: defaultdict(float))
    zone_weights = defaultdict(float)
    for link in crosswalk:
        if link["geoid"] not in known:
            raise ValueError("Unknown tract in taxi crosswalk")
        weight = float(link["taxi_zone_area_share"])
        if not math.isfinite(weight) or not 0 <= weight <= 1.000001:
            raise ValueError("Invalid taxi zone allocation weight")
        zone_weights[link["location_id"]] += weight
        for key, value in zones.get(link["location_id"], {}).items():
            totals[link["geoid"]][key] += weight * value
    if any(weight > 1.0001 for weight in zone_weights.values()):
        raise ValueError("Taxi crosswalk allocates more than one zone total")
    expected = {key: sum(values.get(key, 0)*zone_weights.get(zone, 0) for zone, values in zones.items())
                for key in {k for values in zones.values() for k in values}}
    for key, total in expected.items():
        if not math.isclose(sum(values.get(key, 0) for values in totals.values()), total, rel_tol=1e-9, abs_tol=.01):
            raise ValueError("Taxi area allocation did not conserve covered-zone totals")
    return totals, expected


def complete(stage, master, data):
    required = ("geography/tract_taxi_zone_crosswalk.csv", "entities/subway_stations_weekly_activity.csv")
    if not all((stage / name).exists() for name in required):
        return {"status": "not_available_in_this_release", "_tables": [], "_qa_files": []}
    revision = {"publisher_version": "current source-specific vintages", "source_url": "source_catalog.csv"}
    definitions = {}

    def define(key, text, unit):
        definitions[key] = (text + " Current context only; excluded from retrospective survival training.", unit)

    estimates, validation = rent_estimates(master)
    rent_raw_home = data / "raw_sources/storefront_rent_stats"
    manifest = json.loads((rent_raw_home / "manifest.json").read_text())
    revision_rent = manifest["revisions"][-1]
    entry = revision_rent["files"][0]
    rent_path = rent_raw_home / revision_rent["directory"] / entry["file"]
    if fingerprint(rent_path) != entry["sha256"]:
        raise ValueError("Rent source changed")
    from audit_training_data import rent_audit
    rent_rows, rent_summary = rent_audit(master, read_csv(rent_path))
    reasons = {r["geoid"]: r["missingness_reason"] for r in rent_rows}
    if rent_summary["source_or_unit_mismatches"]:
        raise ValueError("Reported rents do not reconcile")
    define("commercial_rent_reported_missing", "1 when published tract rent is absent; no source rents are overwritten.", "boolean")
    define("commercial_rent_missingness_reason", "Reported, publisher star marker, or no latest-year source tract; see rent coverage audit.", "category")
    define("commercial_rent_monthly_psf_estimate", "Estimate only for missing reported rents, using the method selected by neighborhood-blocked validation; not a verified property rent.", "USD/sq ft/month (estimated)")
    define("commercial_rent_context_monthly_psf", "Published rent when present, otherwise separately validated area-context estimate; always inspect status column.", "USD/sq ft/month (observed or estimated)")
    define("commercial_rent_context_status", "reported versus estimated; estimates must never be represented as published rents.", "category")
    define("income_context_2024", "Published household income, otherwise existing population-weighted neighboring-tract median estimate; not an observed median when filled.", "USD/year (observed or estimated)")
    define("income_context_status", "reported, neighbor_estimate, or unavailable; original income unchanged.", "category")
    define("commercial_area_sqft_per_sq_mile", "PLUTO commercial floor area divided by tract land area.", "sq ft/sq mi")
    define("bar_count_per_sq_mile", "Full-extract OSM tagged bars, pubs and nightclubs divided by tract land area.", "POIs/sq mi")
    define("cafe_count_per_sq_mile", "Full-extract OSM tagged cafes divided by tract land area.", "POIs/sq mi")
    define("citibike_arrivals_per_sq_mile_latest_month", "Latest complete-month Citi Bike arrivals divided by tract land area; no station counts are not inferred from missing trip coverage.", "arrivals/sq mi")
    define("subway_weekly_ridership_within_400m", "Sum of station-complex weekly entries within 400 m straight-line of tract centroid; counts each complex once, not each entrance.", "entries/week")
    define("subway_complexes_within_400m", "Number of station complexes within 400 m straight-line of tract centroid.", "station complexes")
    define("registered_properties_with_vacancy_share", "Registered BBL properties with at least one reported vacant space divided by registered BBL properties; NOT a storefront vacancy rate.", "share")
    define("registered_properties_vacancy_share_status", "property_level_proxy_not_storefront_vacancy_rate when denominator is positive; unavailable otherwise.", "category")

    # Read every trip in the already downloaded complete HVFHV month.
    import duckdb
    from refresh_integrated import raw_revision
    trip_path, trip_revision = raw_revision("tlc_hvfhv")
    month = trip_revision["publisher_version"]
    start = month + "-01"
    year, mon = map(int, month.split("-"))
    end = f"{year + (mon == 12):04d}-{mon % 12 + 1:02d}-01"
    connection = duckdb.connect()
    try:
        zone_rows = connection.execute("""
            SELECT DOLocationID, count(*) AS n,
                   count(*) FILTER (WHERE hour(dropoff_datetime) >= 18 AND hour(dropoff_datetime) < 22),
                   count(*) FILTER (WHERE hour(dropoff_datetime) >= 22 OR hour(dropoff_datetime) < 3)
            FROM read_parquet(?) WHERE pickup_datetime >= CAST(? AS TIMESTAMP)
                 AND pickup_datetime < CAST(? AS TIMESTAMP) AND DOLocationID IS NOT NULL GROUP BY DOLocationID
        """, [str(trip_path), start, end]).fetchall()
    finally:
        connection.close()
    zones = {str(z): {"dropoffs": float(n), "evening": float(e), "late_night": float(l)} for z, n, e, l in zone_rows}
    allocated, conservation = allocate_zone_counts(read_csv(stage / required[0]), zones, {r["geoid"] for r in master})
    for key, text, unit in (
        ("rideshare_dropoffs_area_allocated", "Sum of all overlapping TLC zones' drop-offs times each zone's area fraction in the tract; uniform-area proxy, not observed tract trips.", "dropoffs/month (area allocated)"),
        ("rideshare_dropoffs_per_sq_mile", "Area-allocated monthly drop-offs divided by tract land area; not the whole zone repeated for every tract.", "dropoffs/sq mi/month (area allocated)"),
        ("rideshare_evening_dropoff_share", "Area-allocated drop-offs 18:00-21:59 divided by all allocated drop-offs.", "share"),
        ("rideshare_late_night_dropoff_share", "Area-allocated drop-offs 22:00-02:59 divided by all allocated drop-offs.", "share"),
        ("rideshare_allocation_month", "Complete HVFHV month used for projected-area allocation.", "YYYY-MM"),
    ):
        define(key, text, unit)
    stations = read_csv(stage / required[1])
    hour_path, hour_revision = raw_revision("mta_subway")
    time_patterns = defaultdict(Counter)
    observed_hours = set()
    import csv
    with hour_path.open(newline="", encoding="utf-8-sig") as stream:
        for item in csv.DictReader(stream):
            timestamp = datetime.fromisoformat(item["transit_timestamp"])
            observed_hours.add(timestamp)
            count = float(item["ridership"])
            period = time_patterns[item["station_complex_id"]]
            period["all"] += count
            if timestamp.weekday() >= 5:
                period["weekend"] += count
            else:
                if 6 <= timestamp.hour < 10:
                    period["weekday_am"] += count
                if 16 <= timestamp.hour < 19:
                    period["weekday_pm"] += count
                if 18 <= timestamp.hour < 22:
                    period["weekday_evening"] += count
    if len(observed_hours) != 168 or len(time_patterns) < 400:
        raise ValueError("Nearby subway time shares require a full station week")
    if any(not math.isclose(float(s["weekly_ridership"]), time_patterns[s["station_complex_id"]]["all"], abs_tol=.01)
           for s in stations):
        raise ValueError("Nearby station inventory and hourly source have different weekly totals")
    for period in ("weekend", "weekday_am", "weekday_pm", "weekday_evening"):
        define(f"subway_within_400m_{period}_share", f"Entries during {period} divided by all-week entries at complexes within 400 m of tract centroid. Weekday AM 06-09, PM 16-18, evening 18-21; overlapping windows are not additive.", "share")
    define("walkability_context_index", "Published EPA crosswalked index when present, otherwise land-area-weighted neighboring published indices. Missing isolated tracts are not invented.", "EPA index (observed or neighbor estimated)")
    define("walkability_context_status", "reported, neighbor_estimate, or unavailable; original EPA values unchanged.", "category")
    from refresh_integrated import miles
    records = []
    for row in master:
        record = {"geoid": row["geoid"]}
        rent = number(row.get("reported_median_monthly_rent_psf"))
        income = number(row.get("median_household_income_2024"))
        neighbor_income = number(row.get("neighbor_income_2024_estimate"))
        local = [s for s in stations if miles(float(row["centroid_latitude"]), float(row["centroid_longitude"]),
                  float(s["latitude"]), float(s["longitude"])) <= .4/1.609344]
        area = number(row.get("land_area_sq_miles"))
        values = allocated.get(row["geoid"], {})
        for period in ("weekend", "weekday_am", "weekday_pm", "weekday_evening"):
            record[f"subway_within_400m_{period}_share"] = ratio(
                sum(time_patterns[s["station_complex_id"]][period] for s in local),
                sum(time_patterns[s["station_complex_id"]]["all"] for s in local))
        record.update({"commercial_rent_reported_missing": int(rent is None),
                       "commercial_rent_missingness_reason": reasons[row["geoid"]],
                       "commercial_rent_monthly_psf_estimate": round(estimates[row["geoid"]], 4) if rent is None else "",
                       "commercial_rent_context_monthly_psf": rent if rent is not None else round(estimates[row["geoid"]], 4),
                       "commercial_rent_context_status": "reported" if rent is not None else "estimated",
                       "income_context_2024": income if income is not None else neighbor_income if neighbor_income is not None else "",
                       "income_context_status": "reported" if income is not None else "neighbor_estimate" if neighbor_income is not None else "unavailable",
                       "commercial_area_sqft_per_sq_mile": ratio(number(row.get("commercial_area_sqft")), area),
                       "bar_count_per_sq_mile": ratio(number(row.get("bar_nightlife_competitor_count")), area),
                       "cafe_count_per_sq_mile": ratio(number(row.get("cafe_competitor_count")), area),
                       "citibike_arrivals_per_sq_mile_latest_month": ratio(number(row.get("citibike_arrivals_latest_month")), area),
                       "subway_weekly_ridership_within_400m": sum(float(s["weekly_ridership"]) for s in local),
                       "subway_complexes_within_400m": len(local),
                       "registered_properties_with_vacancy_share": ratio(number(row.get("reported_vacant_storefront_count")), number(row.get("reported_storefront_property_count"))),
                       "registered_properties_vacancy_share_status": "property_level_proxy_not_storefront_vacancy_rate" if number(row.get("reported_storefront_property_count")) else "unavailable",
                       "rideshare_dropoffs_area_allocated": values.get("dropoffs", ""),
                       "rideshare_dropoffs_per_sq_mile": ratio(values.get("dropoffs"), area),
                       "rideshare_evening_dropoff_share": ratio(values.get("evening"), values.get("dropoffs")),
                       "rideshare_late_night_dropoff_share": ratio(values.get("late_night"), values.get("dropoffs")),
                       "rideshare_allocation_month": month})
        records.append(record)
    by_geoid = {row["geoid"]: {**row, **new} for row, new in zip(master, records)}
    for row, record in zip(master, records):
        walk = number(row.get("national_walkability_index"))
        pairs = [(number(by_geoid[g].get("national_walkability_index")), number(by_geoid[g].get("land_area_sq_miles")))
                 for g in row.get("neighbor_geoids", "").split(";") if g in by_geoid]
        pairs = [(v, w) for v, w in pairs if v is not None and w and w > 0]
        record["walkability_context_index"] = walk if walk is not None else ratio(sum(v*w for v, w in pairs), sum(w for _, w in pairs)) if pairs else ""
        record["walkability_context_status"] = "reported" if walk is not None else "neighbor_estimate" if pairs else "unavailable"
    neighbor_fields = ("commercial_rent_context_monthly_psf", "median_household_income_2024",
                       "job_density_per_sq_mile", "subway_weekly_ridership_within_400m",
                       "citibike_arrivals_per_sq_mile_latest_month", "rideshare_dropoffs_per_sq_mile",
                       "nearest_pedestrian_count_site_latest_pedestrian_count_total", "retail_area_sqft_per_sq_mile",
                       "national_walkability_index", "bar_count_per_sq_mile", "cafe_count_per_sq_mile",
                       "registered_properties_with_vacancy_share")
    for field in neighbor_fields:
        define(field + "_nbr", f"Land-area-weighted mean of {field} in boundary-sharing tracts with nonmissing values; no point-only contacts. Units follow source field.", "source field units (area-weighted mean)")
        for row, record in zip(master, records):
            pairs = [(number(by_geoid[g].get(field)), number(by_geoid[g].get("land_area_sq_miles")))
                     for g in row.get("neighbor_geoids", "").split(";") if g in by_geoid]
            pairs = [(v, w) for v, w in pairs if v is not None and w and w > 0]
            record[field + "_nbr"] = ratio(sum(v*w for v, w in pairs), sum(w for _, w in pairs)) if pairs else ""
    result = register(stage, master, "features/tract_completed_context.csv", records, definitions,
                      "Completed tract context", revision, "2020 census tract", "Current-context analytical preparation",
                      "Estimates, property-level proxies and area allocations explicitly labeled; never verified property rents or survival labels.")
    epa = epa_context(stage, master)
    result["_tables"].extend(epa.pop("_tables"))
    result["_qa_files"].extend(epa.pop("_qa_files"))
    result["epa_additional_context"] = epa
    postal = postal_and_license_context(stage, master, data)
    result["_tables"].extend(postal.pop("_tables"))
    result["_qa_files"].extend(postal.pop("_qa_files"))
    result["postal_and_license_context"] = postal
    result["dictionary_units_refined"] = refine_dictionary_units(stage)
    evidence = {"rent_validation": validation, "rent_coverage": rent_summary,
                "rent_source_sha256": entry["sha256"], "rideshare_source_sha256": fingerprint(trip_path),
                "rideshare_month": month, "area_allocated_totals": conservation,
                "subway_hourly_revision": hour_revision["directory"],
                "warning": "Legacy zone-context trip totals remain for compatibility, not additive tract totals. Use rideshare_* fields for area-allocated analysis."}
    (stage / "master_completion_validation.json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    result.update(evidence)
    return result
