"""Integrate complete public sources with explicit geography and observation periods."""

import csv
import gzip
import io
import json
import math
import zipfile
from collections import defaultdict
from datetime import date, datetime
import re


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) and parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator and denominator > 0 else ""


def register(stage, master, filename, records, definitions, label, revision, grain, purpose, limitation):
    indexed = {row["geoid"]: row for row in records}
    if len(indexed) != len(records) or set(indexed) != {row["geoid"] for row in master}:
        raise ValueError(f"New feature table must cover each master tract once: {filename}")
    fields = ("geoid", *definitions)
    write_csv(stage / filename, records, fields)
    for row in master:
        row.update(indexed[row["geoid"]])
    path = stage / "data_dictionary.csv"
    dictionary = read_csv(path)
    dictionary = [row for row in dictionary if not (
        row["file"] in {"master_tract_features.csv", filename} and row["column"] in definitions)]
    for file in ("master_tract_features.csv", filename):
        dictionary.extend({"file": file, "column": key, "definition": value[0], "unit": value[1]}
                          for key, value in definitions.items())
    write_csv(path, dictionary, ("file", "column", "definition", "unit"))
    path = stage / "source_catalog.csv"
    catalog = [row for row in read_csv(path) if row["source"] != label]
    catalog.append({"source": label, "vintage": revision["publisher_version"], "native_grain": grain,
                    "purpose": purpose, "coverage": limitation, "url": revision["source_url"]})
    write_csv(path, catalog, ("source", "vintage", "native_grain", "purpose", "coverage", "url"))
    path = stage / "feature_readiness.csv"
    readiness = [row for row in read_csv(path) if row["use"] != label]
    readiness.append({"use": label, "primary_output": filename, "analysis_grain": "2020 census tract",
                      "status": "current context", "limitation": limitation})
    write_csv(path, readiness, ("use", "primary_output", "analysis_grain", "status", "limitation"))
    return {"_tables": [(filename, fields)], "_qa_files": [filename], "tracts": len(records)}


def rebuild_acs(stage, raw, master, revision, minimum_tracts=2200):
    if revision["publisher_version"] != "2024":
        raise ValueError("ACS context schema is pinned to 2024; add a versioned schema before integrating a newer vintage")
    known = {row["geoid"] for row in master}
    tables, table_counts, raw_rows = {}, {}, []
    for path in sorted(raw.glob("*.dat")):
        table = path.stem.rsplit("-", 1)[-1].upper()
        values = {}
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream, delimiter="|")
            if "GEO_ID" not in (reader.fieldnames or []):
                raise ValueError(f"Invalid ACS summary header: {path.name}")
            for item in reader:
                geoid = item["GEO_ID"].removeprefix("1400000US")
                if not item["GEO_ID"].startswith("1400000US") or geoid not in known:
                    continue
                if geoid in values:
                    raise ValueError(f"Duplicate ACS geography: {table} {geoid}")
                values[geoid] = {key: number(value) for key, value in item.items() if key != "GEO_ID"}
                raw_rows.append({"geoid": geoid, "table": table,
                                 "estimates_and_margins": json.dumps(values[geoid], separators=(",", ":"))})
        if len(values) < minimum_tracts:
            raise ValueError(f"Incomplete NYC ACS table: {table}: {len(values)}")
        tables[table], table_counts[table] = values, len(values)
    required = {"B01001", "B17001", "B19301", "B19001", "B08301", "B15003", "B05002", "B11001", "B25003", "B25064", "B19013"}
    if not required <= set(tables) or set(tables) - required - {"B23025", "B25010"}:
        raise ValueError("ACS context needs all eleven core tables and only supported extension tables")
    definitions = {}
    records = []
    for row in master:
        geoid = row["geoid"]
        record = {"geoid": geoid}

        def get(table, index=1, kind="E"):
            return tables[table].get(geoid, {}).get(f"{table}_{kind}{index:03d}")

        def total(table, indices):
            values = [get(table, index) for index in indices]
            return sum(values) if all(value is not None for value in values) else None

        def add(name, value, description, unit="people"):
            record[name] = "" if value is None else value
            definitions[name] = (description + " Source: 2024 ACS five-year detailed tables; missing/suppressed values remain blank.", unit)

        def share(name, numerator, denominator, description):
            add(name, ratio(numerator, denominator), description, "share")

        add("population_2024", get("B01001"), "B01001 total population.")
        add("population_under_18_2024", total("B01001", [3, 4, 5, 6, 27, 28, 29, 30]), "B01001 population under 18.")
        add("population_65_plus_2024", total("B01001", [*range(20, 26), *range(44, 50)]), "B01001 population aged 65 and over.")
        add("population_density_per_sq_mile", ratio(get("B01001"), number(row.get("land_area_sq_miles"))), "B01001 population divided by tract land area.", "people/sq mi")
        add("median_household_income_2024", get("B19013"), "B19013 median household income in 2024 inflation-adjusted dollars.", "USD/year")
        add("median_household_income_margin_of_error_2024", get("B19013", kind="M"), "Published B19013 median household income margin of error.", "USD/year")
        young = total("B01001", [8, 9, 10, 11, 12, 32, 33, 34, 35, 36])
        add("population_age_20_34_2024", young, "B01001 population aged 20 through 34.")
        share("pct_residents_age_20_34", young, get("B01001"), "Population aged 20-34 divided by total population.")
        add("poverty_universe_population_2024", get("B17001"), "B17001 population for whom poverty status is determined.")
        add("population_below_poverty_2024", get("B17001", 2), "B17001 population below the poverty level.")
        share("poverty_share_2024", get("B17001", 2), get("B17001"), "Below-poverty population divided by its poverty-status universe.")
        add("per_capita_income_2024", get("B19301"), "B19301 per-capita income in 2024 inflation-adjusted dollars.", "USD/year")
        add("per_capita_income_moe_2024", get("B19301", kind="M"), "Published B19301 per-capita income margin of error.", "USD/year")
        add("households_2024", get("B11001"), "B11001 total households.", "households")
        for key, indices, label in (("under_50000", range(2, 11), "under $50,000"),
                                     ("50000_99999", range(11, 14), "$50,000-$99,999"),
                                     ("100000_plus", range(14, 18), "$100,000 or more")):
            share(f"household_income_{key}_share_2024", total("B19001", indices), get("B19001"),
                  f"B19001 share of households with annual income {label}.")
        add("workers_age_16_plus_2024", get("B08301"), "B08301 workers aged 16 and over, including those working from home.")
        for key, index in (("public_transit", 10), ("bicycle", 18), ("walked", 19), ("work_from_home", 21)):
            share(f"commute_{key}_share_2024", get("B08301", index), get("B08301"),
                  f"B08301 {key.replace('_', ' ')} count divided by all workers aged 16+.")
        add("education_population_25_plus_2024", get("B15003"), "B15003 population aged 25 and over.")
        share("bachelors_or_higher_share_2024", total("B15003", range(22, 26)), get("B15003"),
              "B15003 bachelor, master, professional and doctorate holders divided by population aged 25+.")
        share("foreign_born_share_2024", get("B05002", 13), get("B05002"), "B05002 foreign-born share; descriptive context, not individual cuisine preference.")
        add("occupied_housing_units_2024", get("B25003"), "B25003 occupied housing units.", "housing units")
        share("owner_occupied_share_2024", get("B25003", 2), get("B25003"), "B25003 owner-occupied share of occupied housing units.")
        share("renter_occupied_share_2024", get("B25003", 3), get("B25003"), "B25003 renter-occupied share of occupied housing units.")
        add("median_residential_gross_rent_2024", get("B25064"), "B25064 median residential gross rent; separate from commercial rent.", "USD/month")
        add("median_residential_gross_rent_moe_2024", get("B25064", kind="M"), "Published B25064 median residential gross rent margin of error.", "USD/month")
        if "B23025" in tables:
            add("civilian_labor_force_2024", get("B23025", 3), "B23025 civilian labor force aged 16+.")
            add("unemployed_residents_2024", get("B23025", 5), "B23025 unemployed civilian residents aged 16+.")
            share("unemployment_rate_2024", get("B23025", 5), get("B23025", 3),
                  "B23025 unemployed residents divided by civilian labor force; not all residents.")
        if "B25010" in tables:
            add("average_household_size_2024", get("B25010"), "B25010 average household size of occupied housing units; published estimate, excludes group quarters.", "people/household")
        records.append(record)
    filename = "features/tract_acs_context.csv"
    result = register(stage, master, filename, records, definitions, "ACS detailed context", revision,
                      "Census tract", "customer and housing context",
                      f"Complete NYC tract rows extracted from {len(tables)} full national tables; ACS estimates and margins retained; current context only.")
    existing_feature = stage / "features/tract_demographics_income.csv"
    if existing_feature.exists():
        fields = tuple(read_csv(existing_feature)[0])
        write_csv(existing_feature, master, fields)
        result["_tables"].append(("features/tract_demographics_income.csv", fields))
        result["_qa_files"].append("features/tract_demographics_income.csv")
    catalog_path = stage / "source_catalog.csv"
    catalog = read_csv(catalog_path)
    for item in catalog:
        if item["source"] in {"ACS demographics", "ACS income"}:
            table = "b01001" if item["source"] == "ACS demographics" else "b19013"
            item.update({"vintage": f"2024 ACS five-year {table.upper()}",
                         "coverage": "Complete published NYC tract rows from official bulk summary file; no API key required.",
                         "url": revision["source_url"].replace("b01001.dat", table + ".dat")})
    write_csv(catalog_path, catalog, catalog[0].keys())
    evidence_file = "features/acs_context_estimates_and_margins.csv"
    write_csv(stage / evidence_file, raw_rows, ("geoid", "table", "estimates_and_margins"))
    result["_qa_files"].append(evidence_file)
    result.update({"table_tract_counts": table_counts, "derived_fields": len(definitions), "api_key_required": False})
    return result


def rebuild_rac(stage, raw, master, revision, minimum_blocks=10000):
    totals = defaultdict(lambda: defaultdict(int))
    known = {row["geoid"] for row in master}
    seen, blocks = set(), 0
    with gzip.open(raw, "rt", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            block = row["h_geocode"]
            if len(block) != 15 or block[:11] not in known:
                continue
            if block in seen:
                raise ValueError("Duplicate residence block")
            seen.add(block)
            for field in ("C000", "CE03", "CNS18"):
                value = int(row[field])
                if value < 0:
                    raise ValueError("Negative residence job count")
                totals[block[:11]][field] += value
            blocks += 1
    if blocks < minimum_blocks:
        raise ValueError("Incomplete NYC residence-area source")
    vintage = revision["publisher_version"]
    definitions = {
        "resident_area_jobs": (f"{vintage} LODES RAC S000 JT00 jobs by home block aggregated to tract; all jobs, so a person may hold multiple jobs.", "jobs"),
        "resident_area_high_earning_jobs": (f"{vintage} RAC CE03 jobs earning over $3,333/month assigned by home block.", "jobs"),
        "resident_area_food_service_jobs": (f"{vintage} RAC CNS18 accommodation and food service jobs assigned by home block.", "jobs"),
        "resident_area_jobs_year": ("Year of integrated LODES residence-area counts.", "year"),
        "workplace_to_resident_area_job_ratio": ("Workplace jobs divided by home-area jobs, only when both LODES vintages match; not a daytime population.", "ratio")}
    wac = next(row["vintage"] for row in read_csv(stage / "source_catalog.csv") if row["source"] == "LODES")
    same_year = wac.startswith(vintage + " ")
    records = [{"geoid": row["geoid"], "resident_area_jobs": totals[row["geoid"]]["C000"],
                "resident_area_high_earning_jobs": totals[row["geoid"]]["CE03"],
                "resident_area_food_service_jobs": totals[row["geoid"]]["CNS18"],
                "resident_area_jobs_year": vintage,
                "workplace_to_resident_area_job_ratio": ratio(number(row["total_jobs"]), totals[row["geoid"]]["C000"]) if same_year else ""}
               for row in master]
    result = register(stage, master, "features/tract_resident_jobs.csv", records, definitions,
                      "LODES residence-area jobs", revision, "Residence census block", "resident employment context",
                      "Complete NYC residence blocks; all-job counts may include multiple jobs per resident.")
    result.update({"blocks": blocks, "resident_area_jobs": sum(row["resident_area_jobs"] for row in records), "workplace_vintage_matches": same_year})
    return result


def projected_tracts(stage):
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform
    from shapely import make_valid
    project = Transformer.from_crs(4326, 32618, always_xy=True).transform
    features = json.loads((stage / "geography/nyc_2020_census_tracts.geojson").read_text())["features"]
    return {item["properties"]["geoid"]: make_valid(transform(project, shape(item["geometry"]))) for item in features}, project


def rebuild_entrances(stage, raw, master, revision):
    from shapely.geometry import Point
    from shapely import STRtree
    _, project = projected_tracts(stage)
    entrances, seen = [], set()
    for item in read_csv(raw):
        if item["entry_allowed"].strip().upper() != "YES":
            continue
        point = (float(item["entrance_longitude"]), float(item["entrance_latitude"]))
        key = (item["complex_id"], *point)
        if key in seen:
            continue
        seen.add(key)
        entrances.append({"complex_id": item["complex_id"], "station_name": item["stop_name"],
                          "longitude": point[0], "latitude": point[1], "entrance_type": item["entrance_type"]})
    if len(entrances) < 1000:
        raise ValueError("Incomplete subway entrance inventory")
    points = [Point(*project(row["longitude"], row["latitude"])) for row in entrances]
    tree = STRtree(points)
    records = []
    for row in master:
        center = Point(*project(float(row["centroid_longitude"]), float(row["centroid_latitude"])))
        hits = tree.query(center, predicate="dwithin", distance=400)
        nearest = tree.nearest(center)
        records.append({"geoid": row["geoid"], "subway_entry_points_within_400m_centroid": len(hits),
                        "subway_complexes_within_400m_centroid": len({entrances[int(i)]["complex_id"] for i in hits}),
                        "nearest_subway_entry_distance_m": center.distance(points[int(nearest)])})
    definitions = {
        "subway_entry_points_within_400m_centroid": ("Distinct entry-allowed MTA entrance coordinates within 400 projected meters of the tract centroid; straight-line proximity.", "entrances"),
        "subway_complexes_within_400m_centroid": ("Distinct station complexes with an entry-allowed entrance within 400 meters of tract centroid.", "station complexes"),
        "nearest_subway_entry_distance_m": ("Projected straight-line distance from tract centroid to nearest entry-allowed entrance; not a walking route.", "meters")}
    result = register(stage, master, "features/tract_subway_entrance_access.csv", records, definitions,
                      "MTA subway entrances", revision, "Entrance point", "entrance-level access",
                      "MTA 2024 entrance inventory; unique entry-allowed coordinates; centroid distances do not imply tract-wide access.")
    entity = "entities/subway_entrances.csv"
    write_csv(stage / entity, entrances, entrances[0].keys())
    result["_qa_files"].append(entity)
    result["entry_points"] = len(entrances)
    return result


def rebuild_subway_patterns(stage, raw, master, revision, minimum_stations=400):
    totals = defaultdict(lambda: defaultdict(float))
    timestamps = set()
    for row in read_csv(raw):
        when = datetime.fromisoformat(row["transit_timestamp"])
        timestamps.add(when)
        count = float(row["ridership"])
        if not math.isfinite(count) or count < 0:
            raise ValueError("Invalid subway ridership")
        item = totals[row["station_complex_id"]]
        item["total"] += count
        item["weekend"] += count if when.weekday() >= 5 else 0
        item["morning"] += count if 6 <= when.hour < 10 else 0
        item["evening"] += count if 17 <= when.hour < 22 else 0
        item["late_night"] += count if when.hour >= 22 or when.hour < 5 else 0
    if len(timestamps) != 168 or len(totals) < minimum_stations:
        raise ValueError("Subway patterns require a complete citywide week")
    records = []
    for row in master:
        station = totals.get(row["nearest_subway_station_complex_id"], {})
        records.append({"geoid": row["geoid"], **{
            f"nearest_subway_{period}_ridership_share": ratio(station.get(period), station.get("total"))
            for period in ("weekend", "morning", "evening", "late_night")}})
    definitions = {f"nearest_subway_{period}_ridership_share": (
        f"Share of nearest station-complex weekly entries occurring {description}; all seven days unless weekend; activity at a station, not visits to a restaurant.", "share")
        for period, description in (("weekend", "Saturday and Sunday"), ("morning", "06:00-09:59"),
                                     ("evening", "17:00-21:59"), ("late_night", "22:00-04:59"))}
    result = register(stage, master, "features/tract_subway_time_patterns.csv", records, definitions,
                      "MTA station time patterns", revision, "Station complex and hour", "time-of-day mobility context",
                      f"One complete observed week beginning {min(timestamps).date()}; not an annual average or measured restaurant demand.")
    entity = "entities/subway_station_time_patterns.csv"
    station_rows = [{"station_complex_id": key, **value} for key, value in sorted(totals.items())]
    write_csv(stage / entity, station_rows, ("station_complex_id", "total", "weekend", "morning", "evening", "late_night"))
    result["_qa_files"].append(entity)
    result.update({"stations": len(totals), "hours": len(timestamps)})
    return result


def rebuild_taxi_crosswalk(stage, raw, master, revision):
    import shapefile
    from pyproj import CRS, Transformer
    from shapely import STRtree, make_valid
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    tracts, _ = projected_tracts(stage)
    with zipfile.ZipFile(raw) as archive:
        files = {name.rsplit(".", 1)[-1].lower(): name for name in archive.namelist() if not name.startswith("__MACOSX")}
        project = Transformer.from_crs(CRS.from_wkt(archive.read(files["prj"]).decode()), 32618, always_xy=True).transform
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(files["shp"])),
                                  shx=io.BytesIO(archive.read(files["shx"])), dbf=io.BytesIO(archive.read(files["dbf"])))
        grouped = defaultdict(list)
        for item in reader.iterShapeRecords():
            identifier = str(item.record.as_dict()["LocationID"])
            grouped[identifier].append(make_valid(transform(project, shape(item.shape.__geo_interface__))))
    if len(grouped) < 250:
        raise ValueError("Incomplete taxi zone geography")
    zones = {key: unary_union(value) for key, value in grouped.items()}
    zone_ids, geometries = list(zones), list(zones.values())
    tree, crosswalk, records = STRtree(geometries), [], []
    for row in master:
        geoid = row["geoid"]
        tract = tracts[geoid]
        pieces = []
        for index in tree.query(tract, predicate="intersects"):
            zone = geometries[int(index)]
            area = tract.intersection(zone).area
            if area <= 1:
                continue
            pieces.append((zone_ids[int(index)], area, area / tract.area))
            crosswalk.append({"geoid": geoid, "location_id": zone_ids[int(index)],
                              "overlap_area_sq_m": area, "tract_area_share": area / tract.area,
                              "taxi_zone_area_share": area / zone.area})
        coverage = sum(part[2] for part in pieces)
        if coverage > 1.01:
            raise ValueError(f"Overlapping taxi-zone allocations: {geoid}")
        dominant = max(pieces, key=lambda part: part[1]) if pieces else ("", 0, "")
        records.append({"geoid": geoid, "taxi_zone_overlap_count": len(pieces),
                        "taxi_zone_area_coverage_share": coverage,
                        "taxi_zone_dominant_area_id": dominant[0], "taxi_zone_dominant_area_share": dominant[2]})
    definitions = {
        "taxi_zone_overlap_count": ("Number of TLC taxi-zone polygons overlapping tract by more than one square meter.", "zones"),
        "taxi_zone_area_coverage_share": ("Sum of projected taxi-zone overlap areas divided by tract polygon area; gaps remain unallocated.", "share"),
        "taxi_zone_dominant_area_id": ("TLC zone with largest projected overlap area; not centroid zone assignment.", "zone ID"),
        "taxi_zone_dominant_area_share": ("Largest taxi-zone overlap as fraction of tract polygon area; trip totals are not disaggregated.", "share")}
    result = register(stage, master, "features/tract_taxi_zone_overlap.csv", records, definitions,
                      "TLC taxi zone geometry", revision, "Taxi-zone polygon", "geographic overlap context",
                      "Projected polygon intersections; no assumptions about where within a taxi zone trips occurred.")
    crosswalk_file = "geography/tract_taxi_zone_crosswalk.csv"
    write_csv(stage / crosswalk_file, crosswalk, ("geoid", "location_id", "overlap_area_sq_m", "tract_area_share", "taxi_zone_area_share"))
    result["_qa_files"].append(crosswalk_file)
    result.update({"taxi_zones": len(zones), "overlap_rows": len(crosswalk),
                   "multi_zone_tracts": sum(row["taxi_zone_overlap_count"] > 1 for row in records)})
    return result


def rebuild_business_patterns(stage, raw, revision):
    with zipfile.ZipFile(raw) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if len(names) != 1:
            raise ValueError("Unexpected ZIP Business Patterns archive")
        with io.TextIOWrapper(archive.open(names[0]), encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = [row for row in reader if row["naics"].replace("/", "").replace("-", "").startswith("722")]
    if len(rows) < 10000:
        raise ValueError("Incomplete ZIP food-service industry context")
    historical = revision["publisher_version"] == "2015"
    filename = "features/zip_food_service_business_patterns_2015.csv" if historical else "features/zip_food_service_business_patterns.csv"
    write_csv(stage / filename, rows, rows[0].keys())
    path = stage / "source_catalog.csv"
    catalog = read_csv(path)
    for row in catalog:
        if row["source"] == ("Census Business Patterns 2015" if historical else "Census Business Patterns"):
            row.update({"vintage": revision["publisher_version"], "native_grain": "ZIP and NAICS",
                        "coverage": "Complete published nationwide ZIP food-service rows; ZIP totals retained separately; no tract allocation.", "url": revision["source_url"]})
    if historical and not any(row["source"] == "Census Business Patterns 2015" for row in catalog):
        catalog.append({"source": "Census Business Patterns 2015", "vintage": "2015", "native_grain": "ZIP and NAICS",
                        "purpose": "ZIP-level historical industry comparison", "coverage": "Complete nationwide food-service extract; ZIP boundaries and industry classifications can change.",
                        "url": revision["source_url"]})
    write_csv(path, catalog, catalog[0].keys())
    path = stage / "feature_readiness.csv"
    label = "ZIP food-service industry context 2015" if historical else "ZIP food-service industry context"
    readiness = [row for row in read_csv(path) if row["use"] != label]
    readiness.append({"use": label, "primary_output": filename,
                      "analysis_grain": "ZIP and NAICS", "status": "ready at native geography",
                      "limitation": "Published establishment counts and suppressed employment remain at ZIP/NAICS grain; NAICS hierarchy rows must not be summed together; no tract allocation."})
    write_csv(path, readiness, ("use", "primary_output", "analysis_grain", "status", "limitation"))
    return {"_tables": [], "_qa_files": [filename], "rows": len(rows),
            "unique_zips": len({row["zip"] for row in rows}), "tract_allocation": False}


def rebuild_historical_events(stage, raw, master, revision, minimum_rows=100000):
    from refresh_integrated import BOROUGH_NUMBER
    counts, types, months = defaultdict(dict), defaultdict(set), defaultdict(set)
    records = invalid_start = invalid_duration = 0
    latest_allowed = date.today().year - 1
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        display = "Start Date/Time" in (reader.fieldnames or [])
        aliases = {"Event ID": "event_id", "Start Date/Time": "start_date_time", "End Date/Time": "end_date_time",
                   "Event Borough": "event_borough", "Community Board": "community_board", "Event Type": "event_type"}
        reader.fieldnames = [aliases.get(key, key) for key in (reader.fieldnames or [])]
        if not {"event_id", "start_date_time", "end_date_time", "event_borough", "community_board", "event_type"} <= set(reader.fieldnames):
            raise ValueError("Historical event schema does not contain required declared fields")
        for row in reader:
            records += 1
            try:
                start = datetime.strptime(row["start_date_time"], "%m/%d/%Y %I:%M:%S %p") if display else datetime.fromisoformat(row["start_date_time"])
            except (ValueError, KeyError):
                invalid_start += 1
                continue
            duration = None
            try:
                end = datetime.strptime(row["end_date_time"], "%m/%d/%Y %I:%M:%S %p") if display else datetime.fromisoformat(row["end_date_time"])
                if end > start:
                    duration = (min(end, datetime(start.year+1, 1, 1))-start).total_seconds()/3600
            except (ValueError, KeyError):
                pass
            if duration is None:
                invalid_duration += 1
            if not 2015 <= start.year <= latest_allowed:
                continue
            prefix = BOROUGH_NUMBER.get(row.get("event_borough"))
            if prefix is None:
                continue
            months[start.year].add(start.month)
            identifier = (row["event_id"], start.isoformat())
            for board in {int(n) for n in re.findall(r"\d+", row.get("community_board", ""))}:
                if not 1 <= board <= 18:
                    continue
                key = (start.year, str(prefix*100+board))
                previous = counts[key].get(identifier)
                if identifier not in counts[key] or (duration is not None and (previous is None or duration > previous)):
                    counts[key][identifier] = duration
                types[key].add(row.get("event_type", ""))
    if records < minimum_rows:
        raise ValueError("Historical events source has incomplete row coverage")
    years = [y for y in months if len(months[y]) == 12]
    if not years:
        raise ValueError("No past historical event year has all twelve observed months")
    year = max(years)
    native_file = "features/community_district_historical_events.csv"
    native = [{"year": y, "community_district_code": code, "published_event_occurrences": len(ids),
               "permitted_hours_in_start_year": sum(v for v in ids.values() if v is not None),
               "valid_duration_occurrences": sum(v is not None for v in ids.values()),
               "distinct_event_types": len(types[(y, code)] - {""})} for (y, code), ids in sorted(counts.items())]
    write_csv(stage / native_file, native, ("year", "community_district_code", "published_event_occurrences", "permitted_hours_in_start_year", "valid_duration_occurrences", "distinct_event_types"))
    definitions = {
        "past_year_permitted_events_district_context": ("Published event ID/start-time occurrences in the tract's community district for historical_event_context_year; deduplicated within district. Whole-district context, not observed tract events.", "event occurrences/community district/year"),
        "past_year_permitted_event_hours_district_context": ("Valid permitted duration within event start year, summed over distinct district occurrences; duplicate conflicting durations use maximum valid value. Missing or nonpositive durations are omitted from hours, NOT event counts. Check duration-valid share. Setup/breakdown windows, not customer attendance.", "valid permit-hours/community district/year"),
        "past_year_event_duration_valid_share": ("Distinct published district-year event occurrences with valid positive source durations divided by all distinct occurrences. Invalid durations remain in event counts.", "share"),
        "historical_event_context_year": ("Latest past calendar year with all twelve months represented in the full historical permitted-event export. Presence of twelve months is not proof every event was captured.", "year"),
    }
    features = [{"geoid": r["geoid"], "past_year_permitted_events_district_context": len(counts[(year, r["community_district_code"])]),
                 "past_year_permitted_event_hours_district_context": sum(v for v in counts[(year, r["community_district_code"])].values() if v is not None),
                 "past_year_event_duration_valid_share": ratio(sum(v is not None for v in counts[(year, r["community_district_code"])].values()), len(counts[(year, r["community_district_code"])])),
                 "historical_event_context_year": year} for r in master]
    result = register(stage, master, "features/tract_historical_event_context.csv", features, definitions,
                      "Historical permitted events", revision, "event occurrence and community district", "Past-year activity context",
                      "Complete publisher export processed; not tract-level attendance or a verified historical survival predictor. Upcoming-event fields retained separately for the website.")
    result["_qa_files"].append(native_file)
    result.update({"raw_rows": records, "invalid_start_date_rows": invalid_start,
                   "invalid_duration_rows_retained_in_event_counts_when_geolocated": invalid_duration, "selected_year": year,
                   "native_district_year_rows": len(native)})
    return result


def rebuild(name, stage, raw, master, revision):
    if name == "sla_active_context":
        rows = read_csv(raw)
        if len(rows) < 20000 or not {"licensepermitid", "premisescounty", "actualaddressofpremises", "description", "originalissuedate"} <= set(rows[0]):
            raise ValueError("Incomplete or changed active SLA source schema")
        return {"_tables": [], "_qa_files": [], "raw_rows": len(rows),
                "integration": "Derived by the current-master completion transform, not outcome labels"}
    if name == "events_historical":
        return rebuild_historical_events(stage, raw, master, revision)
    if name in {"business_patterns", "business_patterns_2015"}:
        return rebuild_business_patterns(stage, raw, revision)
    functions = {"acs_context": rebuild_acs, "lodes_rac": rebuild_rac,
                 "subway_entrances": rebuild_entrances, "taxi_zone_geometry": rebuild_taxi_crosswalk}
    return functions[name](stage, raw, master, revision)


def validate_enrichment(stage):
    """Check ratios and overlap conservation independently of the source transforms."""
    master = read_csv(stage / "master_tract_features.csv")
    checked = 0
    for row in master:
        bounded = [key for key in row if key.endswith("_share_2024") or key in {
            "pct_residents_age_20_34", "taxi_zone_area_coverage_share", "taxi_zone_dominant_area_share"}
            or key.startswith("nearest_subway_") and key.endswith("_ridership_share")]
        for key in bounded:
            if row[key] != "" and (number(row[key]) is None or float(row[key]) > 1.01):
                raise ValueError(f"Share outside its valid range: {row['geoid']} {key}")
            checked += 1
        for columns in (("owner_occupied_share_2024", "renter_occupied_share_2024"),
                        ("household_income_under_50000_share_2024", "household_income_50000_99999_share_2024", "household_income_100000_plus_share_2024")):
            if all(row.get(key, "") != "" for key in columns):
                if abs(sum(float(row[key]) for key in columns) - 1) > 1e-6:
                    raise ValueError(f"ACS exhaustive shares do not sum to one: {row['geoid']}")
    path = stage / "geography/tract_taxi_zone_crosswalk.csv"
    zone_weights, seen = defaultdict(float), set()
    if path.exists():
        for row in read_csv(path):
            key = (row["geoid"], row["location_id"])
            if key in seen:
                raise ValueError("Duplicate tract/taxi-zone crosswalk key")
            seen.add(key)
            zone_weights[row["location_id"]] += float(row["taxi_zone_area_share"])
        if any(value > 1.01 for value in zone_weights.values()):
            raise ValueError("Tract intersections exceed a taxi zone's area")
    return {"bounded_values_checked": checked, "crosswalk_keys_checked": len(seen)}


def synchronize_resident_ratio(stage, master, workplace_year):
    path = stage / "features/tract_resident_jobs.csv"
    if not path.exists():
        return None
    fields = tuple(read_csv(path)[0])
    for row in master:
        row["workplace_to_resident_area_job_ratio"] = (
            ratio(number(row["total_jobs"]), number(row["resident_area_jobs"]))
            if str(row["resident_area_jobs_year"]) == workplace_year else "")
    write_csv(path, master, fields)
    return ("features/tract_resident_jobs.csv", fields)
