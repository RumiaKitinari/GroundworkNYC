"""Rebuild supported live signals and safely publish a complete data release."""

import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import sys
import uuid
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from download_sources import DESTINATION as RAW_ROOT, SOURCES, download_source, resolve
from master_tract_spec import FIELD_DEFINITIONS as SPEC_FIELDS, enrich as enrich_master_spec
from rebuild_epa import EPA_FIELDS, rebuild as rebuild_epa
from rebuild_osm import MASTER_FIELDS as OSM_MASTER_FIELDS, rebuild as rebuild_osm
from rent_benchmarks import parse_snapshot


ROOT = Path(__file__).resolve().parents[1]
INTEGRATED_ROOT = ROOT / "data" / "integrated"
BASELINE = INTEGRATED_ROOT / "restaurant_bar_location_data_ready"
CURRENT = INTEGRATED_ROOT / "current"
ENRICHMENT_SOURCES = ("acs_context", "lodes_rac", "subway_entrances", "taxi_zone_geometry", "business_patterns", "business_patterns_2015", "events_historical", "sla_active_context")
SUPPORTED = ("restaurants", "events", "mta_subway", "tlc_hvfhv", "osm", "pluto", "citibike", "storefronts", "storefront_rent_stats", "weather", "epa_walkability", "lodes", "pedestrians", *ENRICHMENT_SOURCES)
COUNTY = {"Bronx": "005", "Brooklyn": "047", "Manhattan": "061", "Queens": "081", "Staten Island": "085"}
BOROUGH_NUMBER = {"Manhattan": 1, "Bronx": 2, "Brooklyn": 3, "Queens": 4, "Staten Island": 5}
QUALITY_FIELDS = ("geoid", "active_restaurant_count", "restaurants_with_current_score",
                  "average_latest_inspection_score", "grade_a_restaurant_count",
                  "average_latest_critical_violations", "grade_a_share")
SUBWAY_FIELDS = ("geoid", "subway_station_complex_count", "subway_weekly_ridership",
                 "subway_weekly_transfers", "nearest_subway_distance_miles",
                 "nearest_subway_station_complex_id", "nearest_subway_station_complex",
                 "nearest_subway_weekly_ridership")
EVENT_FIELDS = ("community_district_code", "event_borough", "permitted_event_count_2026",
                "permitted_event_hours_2026", "event_type_count_2026", "first_event_date_2026",
                "last_event_date_2026")
EVENT_ROLLING_FIELDS = ("community_district_code", "event_borough", "permitted_event_count_next_90_days",
                        "permitted_event_hours_next_90_days", "event_type_count_next_90_days",
                        "first_event_date_next_90_days", "last_event_date_next_90_days")
TAXI_FIELDS = ("location_id", "pickups_latest_month", "dropoffs_latest_month",
               "cbd_congestion_fee_total_latest_month", "active_days_latest_month", "taxi_activity_month")
PLUTO_FIELDS = ("geoid", "relevant_parcel_count", "commercial_office_parcel_count",
                "mixed_use_parcel_count", "vacant_land_parcel_count", "relevant_lot_area_sqft",
                "commercial_area_sqft", "retail_area_sqft", "office_area_sqft",
                "vacant_land_parcel_share", "total_lot_count", "commercial_mixed_lot_share_all",
                "vacant_land_share_all_lots", "mean_commercial_mixed_num_floors")
BIKE_FIELDS = ("geoid", "citibike_station_count", "citibike_departures_latest_month",
               "citibike_arrivals_latest_month", "citibike_evening_departures_latest_month",
               "citibike_weekend_departures_latest_month", "nearest_citibike_distance_miles",
               "nearest_citibike_station_id", "nearest_citibike_station_name",
               "nearest_citibike_departures_latest_month", "citibike_activity_month")
STOREFRONT_FIELDS = ("geoid", "reported_storefront_property_count", "reported_vacant_storefront_count",
                    "reported_storefront_vacancy_share")
RENT_FIELDS = ("geoid", "reported_median_monthly_rent_psf", "reported_median_storefront_sqft",
               "registered_storefronts", "leased_storefronts", "rent_reporting_year")
WEATHER_FLAGS = dict(zip(("fog_ice_fog", "heavy_fog", "thunder", "ice_pellets", "hail", "glaze_rime",
                          "dust_sand", "smoke_haze", "blowing_snow", "high_winds", "mist", "drizzle",
                          "freezing_drizzle", "rain", "freezing_rain", "snow", "unknown_precipitation",
                          "ground_fog", "ice_fog"),
                         ("WT01", "WT02", "WT03", "WT04", "WT05", "WT06", "WT07", "WT08", "WT09",
                          "WT11", "WT13", "WT14", "WT15", "WT16", "WT17", "WT18", "WT19", "WT21", "WT22")))
COUNTY_BY_BOROUGH_NUMBER = {str(number): COUNTY[borough] for borough, number in BOROUGH_NUMBER.items()}
LODES_COLUMNS = {
    "CA01": "jobs_age_29_or_younger", "CA02": "jobs_age_30_to_54", "CA03": "jobs_age_55_or_older",
    "CE01": "jobs_earn_1250_or_less_monthly", "CE02": "jobs_earn_1251_to_3333_monthly",
    "CE03": "jobs_earn_more_than_3333_monthly",
    **dict(zip((f"CNS{i:02d}" for i in range(1, 21)), (
        "jobs_agriculture_forestry_fishing_hunting", "jobs_mining_quarrying_oil_gas", "jobs_utilities",
        "jobs_construction", "jobs_manufacturing", "jobs_wholesale_trade", "jobs_retail_trade",
        "jobs_transportation_warehousing", "jobs_information", "jobs_finance_insurance",
        "jobs_real_estate_rental_leasing", "jobs_professional_scientific_technical", "jobs_management",
        "jobs_admin_support_waste_management", "jobs_educational_services",
        "jobs_health_care_social_assistance", "jobs_arts_entertainment_recreation",
        "jobs_accommodation_food_services", "jobs_other_services", "jobs_public_administration")))
}
WORKER_FIELDS = ("geoid", "land_area_sq_miles", *LODES_COLUMNS.values(), "total_jobs", "job_density_per_sq_mile")
PEDESTRIAN_FIELDS = ("geoid", "nearest_pedestrian_count_site_distance_miles",
                     "nearest_pedestrian_count_site_objectid", "nearest_pedestrian_count_site_loc",
                     "nearest_pedestrian_count_site_latest_pedestrian_count_total")


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    digest = hashlib.sha256()
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.is_file():
                digest.update(child.name.encode())
                digest.update(sha256(child).encode())
        return digest.hexdigest()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def raw_revision(name, revision_name=None):
    if name == "osm" and revision_name is None and not (RAW_ROOT / name / "manifest.json").exists():
        local = ROOT / "data" / "osm" / "NewYork.osm.pbf"
        if not local.is_file():
            raise ValueError("No versioned OSM download or local NewYork.osm.pbf exists")
        import osmium
        reader = osmium.io.Reader(str(local))
        try:
            timestamp = reader.header().get("osmosis_replication_timestamp") or "unknown"
        finally:
            reader.close()
        digest = sha256(local)
        return local, {"directory": "local_" + digest[:12], "publisher_version": timestamp,
                       "source_url": "https://download.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf",
                       "sha256": digest, "local_path": str(local)}
    manifest = json.loads((RAW_ROOT / name / "manifest.json").read_text())
    revisions = manifest["revisions"]
    revision = next((item for item in revisions if item["directory"] == revision_name), None) if revision_name else revisions[-1]
    if revision is None or (len(revision["files"]) != 1 and name != "acs_context"):
        raise ValueError(f"Unknown or unsupported raw revision for {name}")
    if name == "acs_context":
        directory = RAW_ROOT / name / revision["directory"]
        for item in revision["files"]:
            path = directory / item["file"]
            if not path.is_file() or sha256(path) != item["sha256"]:
                raise ValueError("ACS context source failed checksum validation")
        return directory, revision
    file = revision["files"][0]
    path = RAW_ROOT / name / revision["directory"] / file["file"]
    if not path.is_file() or sha256(path) != file["sha256"]:
        raise ValueError(f"Raw source failed checksum validation: {name}")
    return path, revision


def valid_tract(row, known_geoids, polygons=None):
    if polygons and row.get("longitude") and row.get("latitude"):
        try:
            match = containing_tract(float(row["longitude"]), float(row["latitude"]), polygons)
            if match in known_geoids:
                return match
        except ValueError:
            pass
    county = COUNTY.get(row.get("boro", ""))
    tract = row.get("census_tract", "").strip()
    if not county or not tract.isdigit() or len(tract) > 6:
        return None
    geoid = "36" + county + tract.zfill(6)
    return geoid if geoid in known_geoids else None


def rebuild_restaurants(stage, raw, master, minimum=30000):
    previous = read_csv(stage / "entities" / "current_restaurants.csv")
    fields = list(previous[0])
    previous_by_camis = {row["camis"]: row for row in previous}
    known = {row["geoid"] for row in master}
    polygons = polygon_index(stage / "geography" / "nyc_2020_census_tracts.geojson")
    geo_cache = {}

    def tract(row):
        key = (row.get("longitude"), row.get("latitude"), row.get("boro"), row.get("census_tract"))
        if key not in geo_cache:
            geo_cache[key] = valid_tract(row, known, polygons)
        return geo_cache[key]

    by_camis = {}
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            camis = row.get("camis", "").strip()
            if not camis:
                continue
            day = row.get("inspection_date", "")
            group = by_camis.get(camis)
            if group is None:
                by_camis[camis] = {"date": day, "latest": [row], "geo": row if tract(row) else None}
            else:
                if tract(row) and group["geo"] is None:
                    group["geo"] = row
                if day > group["date"]:
                    group["date"], group["latest"] = day, [row]
                elif day == group["date"]:
                    group["latest"].append(row)
    entities = []
    carried_geocodes = 0
    for camis, group in by_camis.items():
        recent = group["latest"]
        geo = next((row for row in recent if tract(row)), None) or group["geo"]
        previous_location = previous_by_camis.get(camis)
        current = next((row for row in recent if row.get("latitude") and row.get("longitude")), recent[0])
        if geo is None:
            if previous_location is not None and previous_location["geoid"] in known:
                geo = previous_location
                carried_geocodes += 1
            else:
                geo = current
        pick = lambda key: next((row[key] for row in recent if row.get(key)), "")
        action = pick("action")
        closed = action.startswith("Establishment Closed by DOHMH") or action.startswith("Establishment re-closed by DOHMH")
        result = {key: current.get(key, "") for key in fields}
        for key in ("latitude", "longitude", "community_board", "council_district", "census_tract", "bin", "bbl", "nta"):
            result[key] = geo.get(key, "")
        result.update({"camis": camis, "inspection_date": group["date"][:10],
                       "latest_score": pick("score"), "latest_grade": pick("grade"),
                       "latest_action": action, "latest_inspection_type": pick("inspection_type"),
                       "latest_violation_count": sum(bool(row.get("violation_code")) for row in recent) if group["date"] else "",
                       "latest_critical_violation_count": sum(row.get("critical_flag") == "Critical" for row in recent) if group["date"] else "",
                       "active_establishment": not closed,
                       "geoid": geo["geoid"] if geo is previous_location else tract(geo) or ""})
        entities.append(result)
    entities.sort(key=lambda row: row["camis"])
    if len(entities) < minimum or len(entities) > 40000:
        raise ValueError(f"Restaurant establishment count outside expected range: {len(entities)}")
    write_csv(stage / "entities" / "current_restaurants.csv", entities, fields)
    groups = defaultdict(list)
    for row in entities:
        if row["active_establishment"] and row["geoid"]:
            groups[row["geoid"]].append(row)
    features = []
    for geoid, rows in sorted(groups.items()):
        scored = [float(row["latest_score"]) for row in rows if row["latest_score"]]
        critical = [float(row["latest_critical_violation_count"]) for row in rows if row["latest_critical_violation_count"] != ""]
        a_count = sum(row["latest_grade"] == "A" for row in rows)
        features.append(dict(zip(QUALITY_FIELDS, (geoid, len(rows), len(scored),
                           sum(scored) / len(scored) if scored else "", a_count,
                           sum(critical) / len(critical) if critical else "",
                           a_count / len(scored) if scored else ""))))
    write_csv(stage / "features" / "tract_restaurant_quality.csv", features, QUALITY_FIELDS)
    feature_by_geoid = {row["geoid"]: row for row in features}
    for row in master:
        values = feature_by_geoid.get(row["geoid"])
        for field in QUALITY_FIELDS[1:]:
            row[field] = values[field] if values else (0 if field in ("active_restaurant_count", "restaurants_with_current_score", "grade_a_restaurant_count") else "")
    return {"establishments": len(entities), "active": sum(row["active_establishment"] for row in entities),
            "prior_geocodes_carried": carried_geocodes,
            "unlocated": sum(not row["geoid"] for row in entities),
            "tracts_with_restaurants": len(features)}


def rebuild_events(stage, raw, master, as_of):
    horizon = as_of + timedelta(days=90)
    known = {row.get("community_district_code") for row in master}
    def new_group():
        return {"ids": set(), "types": set(), "hours": 0.0, "dates": [], "borough": ""}

    groups = defaultdict(new_group)
    groups_2026 = defaultdict(new_group)
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            try:
                start = datetime.fromisoformat(row["start_date_time"])
                end = datetime.fromisoformat(row["end_date_time"])
            except (KeyError, ValueError):
                continue
            if not as_of <= start.date() < horizon or end <= start:
                continue
            borough = row.get("event_borough", "")
            prefix = BOROUGH_NUMBER.get(borough)
            if prefix is None:
                continue
            boards = {int(number) for number in re.findall(r"\d+", row.get("community_board", ""))}
            for board in boards:
                code = str(prefix * 100 + board)
                if not 1 <= board <= 18 or code not in known:
                    continue
                event_id = row.get("event_id") or f"{row.get('event_name')}:{start.isoformat()}"
                for target in (groups, groups_2026) if start.year == 2026 else (groups,):
                    group = target[code]
                    if event_id in group["ids"]:
                        continue
                    group["ids"].add(event_id)
                    group["types"].add(row.get("event_type", ""))
                    group["hours"] += min((end - start).total_seconds() / 3600, 24 * 7)
                    group["dates"].append(start.date())
                    group["borough"] = borough

    def write_events(name, columns, grouped):
        features = []
        for code, group in sorted(grouped.items()):
            features.append(dict(zip(columns, (code, group["borough"], len(group["ids"]),
                            round(group["hours"], 2), len(group["types"] - {""}),
                            min(group["dates"]).isoformat(), max(group["dates"]).isoformat()))))
        write_csv(stage / "features" / name, features, columns)
        return {row["community_district_code"]: row for row in features}

    legacy = write_events("community_district_events_2026.csv", EVENT_FIELDS, groups_2026)
    rolling = write_events("community_district_events_next_90_days.csv", EVENT_ROLLING_FIELDS, groups)
    for row in master:
        for columns, lookup in ((EVENT_FIELDS, legacy), (EVENT_ROLLING_FIELDS, rolling)):
            event = lookup.get(row.get("community_district_code"))
            for field in columns[2:]:
                row[field] = event[field] if event else (0 if field in columns[2:5] else "")
    return {"districts": len(rolling), "events": sum(len(group["ids"]) for group in groups.values()),
            "window_start": as_of.isoformat(), "window_end_exclusive": horizon.isoformat()}


def point_in_ring(x, y, ring):
    inside = False
    for index in range(len(ring)):
        x1, y1 = ring[index - 1]
        x2, y2 = ring[index]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def polygon_index(path):
    features = json.loads(path.read_text())["features"]
    result = defaultdict(list)
    for feature in features:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for rings in polygons:
            outer = rings[0]
            xs, ys = zip(*outer)
            box = (min(xs), min(ys), max(xs), max(ys), rings, feature["properties"]["geoid"])
            for x in range(math.floor(box[0] * 100), math.floor(box[2] * 100) + 1):
                for y in range(math.floor(box[1] * 100), math.floor(box[3] * 100) + 1):
                    result[(x, y)].append(box)
    return result


def containing_tract(lon, lat, polygons):
    for left, bottom, right, top, rings, geoid in polygons.get((math.floor(lon * 100), math.floor(lat * 100)), ()):
        if left <= lon <= right and bottom <= lat <= top and point_in_ring(lon, lat, rings[0]):
            if not any(point_in_ring(lon, lat, hole) for hole in rings[1:]):
                return geoid
    return ""


def miles(lat1, lon1, lat2, lon2):
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dr, dc = r2 - r1, math.radians(lon2 - lon1)
    return 3958.7613 * 2 * math.asin(math.sqrt(math.sin(dr / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dc / 2) ** 2))


def rebuild_lodes(stage, raw, master, minimum_blocks=10000):
    known = {row["geoid"] for row in master}
    totals = defaultdict(lambda: defaultdict(int))
    blocks = 0
    with gzip.open(raw, "rt", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"w_geocode", "C000", *LODES_COLUMNS}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("LODES source lacks required workplace columns")
        for record in reader:
            block = record["w_geocode"]
            geoid = block[:11]
            if len(block) != 15 or geoid not in known:
                continue
            jobs = int(record["C000"])
            if any(sum(int(record[f"{prefix}{index:02d}"]) for index in range(1, count + 1)) != jobs
                   for prefix, count in (("CA", 3), ("CE", 3), ("CNS", 20))):
                raise ValueError(f"LODES job categories do not reconcile for block {block}")
            blocks += 1
            values = totals[geoid]
            values["total_jobs"] += jobs
            for source, field in LODES_COLUMNS.items():
                values[field] += int(record[source])
    if blocks < minimum_blocks:
        raise ValueError(f"LODES NYC block coverage too low: {blocks}")
    features = []
    for row in master:
        geoid = row["geoid"]
        jobs = totals[geoid]["total_jobs"]
        area = float(row["land_area_sq_miles"])
        population = float(row["population_2024"]) if row.get("population_2024") else 0
        feature = {"geoid": geoid, "land_area_sq_miles": row["land_area_sq_miles"],
                   **{field: totals[geoid][field] for field in LODES_COLUMNS.values()},
                   "total_jobs": jobs, "job_density_per_sq_mile": jobs / area if area > 0 else ""}
        features.append(feature)
        row.update(feature)
        row["jobs_per_1000_residents"] = 1000 * jobs / population if population > 0 else ""
    write_csv(stage / "features" / "tract_workers.csv", features, WORKER_FIELDS)
    return {"blocks": blocks, "tracts_with_jobs": sum(row["total_jobs"] > 0 for row in features),
            "nyc_jobs": sum(row["total_jobs"] for row in features)}


def rebuild_pedestrians(stage, raw, master, minimum_sites=100):
    sites = []
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"objectid", "loc", "the_geom"} <= set(reader.fieldnames or []):
            raise ValueError("DOT pedestrian source lacks monitor identifiers or geometry")
        periods = defaultdict(dict)
        for field in reader.fieldnames:
            match = re.fullmatch(r"(may|june|sept|oct)_?(\d{2})_(am|md|pm|p_m)", field)
            if match:
                month, year, daypart = match.groups()
                key = (2000 + int(year), {"may": 5, "june": 6, "sept": 9, "oct": 10}[month])
                periods[key]["pm" if daypart == "p_m" else daypart] = field
        for record in reader:
            point = re.fullmatch(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", record["the_geom"] or "")
            if not point:
                continue
            latest = next(((period, fields) for period, fields in sorted(periods.items(), reverse=True)
                           if len(fields) == 3 and all(record.get(fields[part], "").isdigit()
                                                        for part in ("am", "md", "pm"))), None)
            if latest is None:
                continue
            period, fields = latest
            sites.append({"objectid": record["objectid"], "loc": record["loc"],
                          "longitude": float(point[1]), "latitude": float(point[2]),
                          "period": f"{period[0]}-{period[1]:02d}",
                          "count_total": sum(int(record[fields[part]]) for part in ("am", "md", "pm"))})
    if len(sites) < minimum_sites or len({site["objectid"] for site in sites}) != len(sites):
        raise ValueError(f"DOT pedestrian monitor coverage or uniqueness failed: {len(sites)}")
    write_csv(stage / "entities" / "pedestrian_count_sites_latest.csv", sites,
              ("objectid", "loc", "latitude", "longitude", "period", "count_total"))
    features = []
    for row in master:
        lat, lon = float(row["centroid_latitude"]), float(row["centroid_longitude"])
        nearest = min(sites, key=lambda site: miles(lat, lon, site["latitude"], site["longitude"]))
        feature = dict(zip(PEDESTRIAN_FIELDS, (row["geoid"],
            miles(lat, lon, nearest["latitude"], nearest["longitude"]),
            nearest["objectid"], nearest["loc"], nearest["count_total"])))
        features.append(feature)
        row.update(feature)
    write_csv(stage / "features" / "tract_pedestrian_access.csv", features, PEDESTRIAN_FIELDS)
    return {"sites": len(sites), "latest_period": max(site["period"] for site in sites),
            "tracts_with_monitor_within_half_mile": sum(float(row[PEDESTRIAN_FIELDS[1]]) <= .5 for row in features)}


def rebuild_subway(stage, raw, master):
    old = {row["station_complex_id"]: row for row in read_csv(stage / "entities" / "subway_stations_weekly_activity.csv")}
    stations = {}
    hours = set()
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            station_id = row["station_complex_id"]
            record = stations.setdefault(station_id, {"station_complex_id": station_id,
                "station_complex": row["station_complex"], "latitude": row["latitude"],
                "longitude": row["longitude"], "weekly_ridership": 0.0,
                "weekly_transfers": 0.0, "geoid": old.get(station_id, {}).get("geoid", "")})
            record["weekly_ridership"] += float(row["ridership"])
            record["weekly_transfers"] += float(row["transfers"])
            hours.add(row["transit_timestamp"])
    if len(hours) != 168 or len(stations) < 400:
        raise ValueError("The selected MTA revision is not a complete station week")
    polygons = polygon_index(stage / "geography" / "nyc_2020_census_tracts.geojson")
    for row in stations.values():
        if not row["geoid"]:
            row["geoid"] = containing_tract(float(row["longitude"]), float(row["latitude"]), polygons)
    unmatched = sum(not row["geoid"] for row in stations.values())
    if unmatched > 5:
        raise ValueError(f"Too many subway stations lack a tract: {unmatched}")
    station_rows = sorted(stations.values(), key=lambda row: int(row["station_complex_id"]))
    county_to_borough = {code: name for name, code in COUNTY.items()}
    for station in station_rows:
        station["borough"] = old.get(station["station_complex_id"], {}).get("borough") or county_to_borough.get(station["geoid"][2:5], "")
    write_csv(stage / "entities" / "subway_stations_weekly_activity.csv", station_rows,
              ("station_complex_id", "station_complex", "borough", "latitude", "longitude",
               "weekly_ridership", "weekly_transfers", "geoid"))
    by_tract = defaultdict(list)
    for station in station_rows:
        if station["geoid"]:
            by_tract[station["geoid"]].append(station)
    features = []
    for row in master:
        geoid = row["geoid"]
        lat, lon = float(row["centroid_latitude"]), float(row["centroid_longitude"])
        nearest = min(station_rows, key=lambda station: miles(lat, lon, float(station["latitude"]), float(station["longitude"])))
        local = by_tract[geoid]
        values = dict(zip(SUBWAY_FIELDS, (geoid, len(local) if local else "",
            sum(station["weekly_ridership"] for station in local) if local else "",
            sum(station["weekly_transfers"] for station in local) if local else "",
            miles(lat, lon, float(nearest["latitude"]), float(nearest["longitude"])),
            nearest["station_complex_id"], nearest["station_complex"], nearest["weekly_ridership"])))
        features.append(values)
        row.update(values)
    write_csv(stage / "features" / "tract_subway_access.csv", features, SUBWAY_FIELDS)
    return {"stations": len(station_rows), "unmatched_stations": unmatched,
            "week_start": min(hours)[:10], "week_end": max(hours)[:10]}


def rebuild_tlc(stage, raw, master, month, minimum_trips=5000000, minimum_zones=200):
    try:
        import duckdb
    except ImportError as error:
        raise ValueError("Install demo/requirements-data.txt to rebuild TLC activity") from error
    start = date.fromisoformat(month + "-01")
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    connection = duckdb.connect()
    try:
        pickups = connection.execute("""
            SELECT PULocationID, count(*), coalesce(sum(cbd_congestion_fee), 0),
                   count(distinct cast(pickup_datetime as date))
            FROM read_parquet(?)
            WHERE pickup_datetime >= ? AND pickup_datetime < ? AND PULocationID IS NOT NULL
            GROUP BY PULocationID
        """, [str(raw), start, end]).fetchall()
        dropoffs = connection.execute("""
            SELECT DOLocationID, count(*)
            FROM read_parquet(?)
            WHERE pickup_datetime >= ? AND pickup_datetime < ? AND DOLocationID IS NOT NULL
            GROUP BY DOLocationID
        """, [str(raw), start, end]).fetchall()
    finally:
        connection.close()
    pickup_by_zone = {str(zone): (count, float(fee), days) for zone, count, fee, days in pickups}
    dropoff_by_zone = {str(zone): count for zone, count in dropoffs}
    total = sum(count for count, _, _ in pickup_by_zone.values())
    if total < minimum_trips or len(pickup_by_zone) < minimum_zones:
        raise ValueError(f"TLC month is incomplete: {total} trips across {len(pickup_by_zone)} pickup zones")
    path = stage / "features" / "tract_taxi_activity.csv"
    features = read_csv(path)
    by_geoid = {row["geoid"]: row for row in features}
    for row in features:
        zone = row.get("location_id", "")
        pickup = pickup_by_zone.get(zone)
        row.update({"pickups_latest_month": pickup[0] if pickup else (0 if zone else ""),
                    "dropoffs_latest_month": dropoff_by_zone.get(zone, 0) if zone else "",
                    "cbd_congestion_fee_total_latest_month": round(pickup[1], 2) if pickup else (0 if zone else ""),
                    "active_days_latest_month": pickup[2] if pickup else (0 if zone else ""),
                    "taxi_activity_month": month if zone else ""})
    write_csv(path, features, list(features[0]))
    for row in master:
        feature = by_geoid[row["geoid"]]
        for field in TAXI_FIELDS[1:]:
            row[field] = feature[field]
    return {"month": month, "trips_with_pickup_zone": total, "pickup_zones": len(pickup_by_zone),
            "tracts_with_taxi_zone": sum(bool(row.get("location_id")) for row in features)}


def rebuild_pluto(stage, raw, master, minimum=80000):
    known = {row["geoid"] for row in master}
    totals = defaultdict(lambda: defaultdict(float))
    seen = set()
    assigned = unassigned = duplicates = 0
    versions = set()
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        for parcel in csv.DictReader(stream):
            landuse = parcel.get("landuse", "").strip().zfill(2)
            version = parcel.get("version", "").strip()
            if version:
                versions.add(version)
            bbl = parcel.get("bbl", "").strip()
            if bbl:
                if bbl in seen:
                    duplicates += 1
                    continue
                seen.add(bbl)
            bct = parcel.get("bct2020", "").strip()
            geoid = "36" + COUNTY_BY_BOROUGH_NUMBER.get(bct[:1], "") + bct[1:]
            if len(bct) != 7 or geoid not in known:
                unassigned += landuse in {"04", "05", "11"}
                continue
            values = totals[geoid]
            if landuse.isdigit() and landuse != "00":
                values["total_lot_count"] += 1
            if landuse not in {"04", "05", "11"}:
                continue
            values["relevant_parcel_count"] += 1
            values[{"04": "mixed_use_parcel_count", "05": "commercial_office_parcel_count",
                    "11": "vacant_land_parcel_count"}[landuse]] += 1
            if landuse in {"04", "05"}:
                try:
                    floors = float(parcel.get("numfloors", "") or 0)
                except ValueError:
                    floors = 0
                if math.isfinite(floors) and floors > 0:
                    values["commercial_mixed_floors_sum"] += floors
                    values["commercial_mixed_floors_observed"] += 1
            for source, target in (("lotarea", "relevant_lot_area_sqft"),
                                   ("comarea", "commercial_area_sqft"),
                                   ("retailarea", "retail_area_sqft"),
                                   ("officearea", "office_area_sqft")):
                try:
                    area = float(parcel.get(source, "") or 0)
                except ValueError:
                    area = 0
                if math.isfinite(area) and area > 0:
                    values[target] += area
            assigned += 1
    if assigned < minimum or unassigned > max(100, (assigned + unassigned) * 0.01):
        raise ValueError(f"PLUTO tract coverage is incomplete: {assigned} assigned, {unassigned} unassigned")
    if len(versions) > 1:
        raise ValueError(f"PLUTO raw snapshot mixes versions: {sorted(versions)}")
    features = []
    for row in master:
        values = totals.get(row["geoid"])
        feature = {"geoid": row["geoid"]}
        for field in PLUTO_FIELDS[1:]:
            if field == "vacant_land_parcel_share":
                value = round(values["vacant_land_parcel_count"] / values["relevant_parcel_count"], 6) if values and values["relevant_parcel_count"] else ""
            elif field == "commercial_mixed_lot_share_all":
                value = round((values["mixed_use_parcel_count"] + values["commercial_office_parcel_count"]) / values["total_lot_count"], 6) if values and values["total_lot_count"] else ""
            elif field == "vacant_land_share_all_lots":
                value = round(values["vacant_land_parcel_count"] / values["total_lot_count"], 6) if values and values["total_lot_count"] else ""
            elif field == "mean_commercial_mixed_num_floors":
                value = round(values["commercial_mixed_floors_sum"] / values["commercial_mixed_floors_observed"], 3) if values and values["commercial_mixed_floors_observed"] else ""
            elif values:
                value = int(values[field]) if field.endswith("_count") else values[field]
            else:
                value = ""
            feature[field] = value
            row[field] = value
        features.append(feature)
    write_csv(stage / "features" / "tract_land_use.csv", features, PLUTO_FIELDS)
    return {"source_version": next(iter(versions), "unknown"), "relevant_parcels": assigned,
            "unassigned_parcels": unassigned, "duplicate_bbl_rows": duplicates,
            "tracts_with_relevant_parcels": sum(bool(values["relevant_parcel_count"]) for values in totals.values()),
            "total_lots_with_land_use": sum(int(values["total_lot_count"]) for values in totals.values()),
            "vacant_land_parcels": sum(int(values["vacant_land_parcel_count"]) for values in totals.values())}


def rebuild_storefronts(stage, raw, master, minimum=1800):
    path = stage / "entities" / "current_storefronts.csv"
    old = read_csv(path)
    prior = {row["borough_block_lot"]: row for row in old}
    known = {row["geoid"] for row in master}
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        records = list(csv.DictReader(stream))
    year_counts = defaultdict(int)
    for record in records:
        year_counts[record.get("reporting_year", "").strip()] += 1
    eligible_years = [year for year, count in year_counts.items() if year.isdigit() and count >= minimum]
    if not eligible_years:
        raise ValueError(f"No complete storefront reporting year: {dict(year_counts)}")
    complete_years = []
    reference_rows = max(year_counts[candidate] for candidate in eligible_years)
    for candidate in eligible_years:
        rows = [record for record in records if record.get("reporting_year", "").strip() == candidate]
        not_vacant = sum(record.get("vacant_on_12_31", "").strip().upper() in {"NO", "N"} for record in rows)
        if len(rows) >= reference_rows * 0.8 and not_vacant >= minimum and not_vacant >= len(rows) * 0.1:
            complete_years.append(candidate)
    year = max(complete_years or eligible_years)
    grouped = defaultdict(list)
    for record in records:
        if record.get("reporting_year", "").strip() != year:
            continue
        bbl = record.get("borough_block_lot", "").strip() or record.get("bbl", "").strip()
        if not bbl:
            continue
        grouped[bbl].append(record)
    latest = {}
    for bbl, filings in grouped.items():
        last_date = max(record.get("filing_due_date", "") for record in filings)
        current_filings = [record for record in filings if record.get("filing_due_date", "") == last_date]
        item = dict(current_filings[0])
        item["vacant_current"] = str(any(
            record.get(field, "").strip().upper() in {"YES", "Y"}
            for record in current_filings for field in ("vacant_on_12_31", "vacant_6_30_or_date_sold")
        ))
        latest[bbl] = item
    if len(latest) < minimum or len(latest) < len(prior) * 0.8:
        raise ValueError(f"Storefront property coverage dropped: {len(latest)} vs {len(prior)} prior")
    polygons = polygon_index(stage / "geography" / "nyc_2020_census_tracts.geojson")
    entities = []
    unlocated = carried = 0
    for bbl, record in latest.items():
        item = dict(record)
        item["borough_block_lot"] = bbl
        try:
            geoid = containing_tract(float(record["longitude"]), float(record["latitude"]), polygons)
        except (KeyError, TypeError, ValueError):
            geoid = ""
        if geoid not in known:
            geoid = prior.get(bbl, {}).get("geoid", "")
            carried += bool(geoid)
        if geoid not in known:
            geoid = ""
            unlocated += 1
        item["geoid"] = geoid
        entities.append(item)
    if unlocated > max(100, len(entities) * 0.05):
        raise ValueError(f"Too many storefronts lack a 2020 tract: {unlocated}/{len(entities)}")
    entities.sort(key=lambda item: item["borough_block_lot"])
    fields = tuple(dict.fromkeys((*old[0].keys(), *records[0].keys(), "geoid", "vacant_current")))
    write_csv(path, entities, fields)
    by_tract = defaultdict(list)
    for item in entities:
        if item["geoid"]:
            by_tract[item["geoid"]].append(item)
    occupied_tracts = len(by_tract)
    features = []
    for row in master:
        items = by_tract[row["geoid"]]
        vacant = sum(item["vacant_current"] == "True" for item in items)
        feature = {"geoid": row["geoid"], "reported_storefront_property_count": len(items),
                   "reported_vacant_storefront_count": vacant,
                   "reported_storefront_vacancy_share": ""}
        row.update(feature)
        features.append(feature)
    write_csv(stage / "features" / "tract_storefront_availability.csv", features, STOREFRONT_FIELDS)
    return {"reporting_year": year, "reporting_coverage": "mixed occupied and vacant" if complete_years else "vacant-only or incomplete",
            "properties": len(entities), "unlocated": unlocated,
            "prior_geocodes_carried": carried, "tracts_with_reports": occupied_tracts,
            "properties_with_reported_vacancy": sum(item["vacant_current"] == "True" for item in entities)}


def rebuild_rent_stats(stage, raw, master, minimum=1000):
    snapshot = parse_snapshot(str(raw), sha256(raw))
    by_geoid = snapshot["by_geoid"]
    known = {row["geoid"] for row in master}
    covered = len(known & by_geoid.keys())
    if covered < minimum:
        raise ValueError(f"Too few tract rent medians: {covered}")
    features = []
    for row in master:
        value = by_geoid.get(row["geoid"])
        feature = {"geoid": row["geoid"]}
        for field in RENT_FIELDS[1:]:
            feature[field] = snapshot["reporting_year"] if field == "rent_reporting_year" and value else value.get(field, "") if value else ""
        row.update(feature)
        features.append(feature)
    write_csv(stage / "features" / "tract_storefront_rent_context.csv", features, RENT_FIELDS)
    return {"reporting_year": snapshot["reporting_year"], "tracts_with_medians": covered,
            "unmatched_source_tracts": len(by_geoid) - covered}


def rebuild_weather(stage, raw, as_of, minimum=2000):
    path = stage / "features" / "daily_weather_central_park.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        fields = next(csv.reader(stream))

    def measure(record, key, divisor=1):
        try:
            value = float(record.get(key, "").strip())
        except (AttributeError, ValueError):
            return ""
        return round(value / divisor, 3) if math.isfinite(value) else ""

    rows = []
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        for record in csv.DictReader(stream):
            day = record.get("DATE", "")
            if not "2020-01-01" <= day <= as_of.isoformat():
                continue
            maximum, minimum_temperature = measure(record, "TMAX", 10), measure(record, "TMIN", 10)
            average = round((maximum + minimum_temperature) / 2, 3) if maximum != "" and minimum_temperature != "" else measure(record, "TAVG", 10)
            item = {"station": record.get("STATION", ""), "date": day,
                    "station_name": record.get("NAME", ""), "latitude": record.get("LATITUDE", ""),
                    "longitude": record.get("LONGITUDE", ""), "elevation_m": record.get("ELEVATION", ""),
                    "precipitation_mm": measure(record, "PRCP", 10), "snowfall_mm": measure(record, "SNOW"),
                    "snow_depth_mm": measure(record, "SNWD"), "max_temperature_c": maximum,
                    "min_temperature_c": minimum_temperature, "avg_temperature_c": average,
                    "avg_wind_speed_m_s": measure(record, "AWND", 10)}
            item.update({name: int(bool(record.get(code, "").strip())) for name, code in WEATHER_FLAGS.items()})
            rows.append(item)
    rows.sort(key=lambda row: row["date"])
    if len(rows) < minimum or len({row["date"] for row in rows}) != len(rows):
        raise ValueError(f"Central Park weather coverage is incomplete: {len(rows)} daily observations")
    write_csv(path, rows, fields)
    return {"station": rows[-1]["station"], "days": len(rows), "first_date": rows[0]["date"],
            "latest_date": rows[-1]["date"]}


def rebuild_citibike(stage, raw, master, month, minimum=1000000):
    import io

    known = {row["geoid"] for row in master}
    previous = {row["station_id"]: row for row in read_csv(stage / "entities" / "citibike_stations_august_2026.csv")}
    stations = defaultdict(lambda: defaultdict(float))
    trips = 0
    with zipfile.ZipFile(raw) as archive:
        for member in archive.infolist():
            if not member.filename.lower().endswith(".csv"):
                continue
            with archive.open(member) as binary:
                for trip in csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")):
                    started = trip.get("started_at", "")
                    if not started.startswith(month):
                        continue
                    trips += 1
                    for prefix, count_field in (("start", "departures"), ("end", "arrivals")):
                        station_id = trip.get(f"{prefix}_station_id", "").strip()
                        if not station_id:
                            continue
                        station = stations[station_id]
                        station[count_field] += 1
                        station["station_name"] = trip.get(f"{prefix}_station_name", "") or station.get("station_name", "")
                        try:
                            latitude = float(trip.get(f"{prefix}_lat", ""))
                            longitude = float(trip.get(f"{prefix}_lng", ""))
                        except ValueError:
                            continue
                        if 40.4 < latitude < 41.0 and -74.3 < longitude < -73.6:
                            station["lat_sum"] += latitude
                            station["lon_sum"] += longitude
                            station["coord_count"] += 1
                        if prefix == "start":
                            hour = int(started[11:13])
                            if hour >= 17 or hour < 5:
                                station["evening_departures"] += 1
                            if date.fromisoformat(started[:10]).weekday() >= 5:
                                station["weekend_departures"] += 1
    if trips < minimum:
        raise ValueError(f"Citi Bike month is incomplete: {trips} trips for {month}")
    polygons = polygon_index(stage / "geography" / "nyc_2020_census_tracts.geojson")
    station_rows = []
    by_tract = defaultdict(list)
    for station_id, station in stations.items():
        prior = previous.get(station_id, {})
        count = station.get("coord_count", 0)
        latitude = station["lat_sum"] / count if count else float(prior.get("latitude") or 0)
        longitude = station["lon_sum"] / count if count else float(prior.get("longitude") or 0)
        geoid = containing_tract(longitude, latitude, polygons) if count else prior.get("geoid", "")
        item = {"station_id": station_id, "station_name": station.get("station_name", ""),
                "latitude": latitude, "longitude": longitude, "geoid": geoid,
                "departures_latest_month": int(station["departures"]),
                "arrivals_latest_month": int(station["arrivals"]),
                "evening_departures_latest_month": int(station["evening_departures"]),
                "weekend_departures_latest_month": int(station["weekend_departures"]),
                "activity_month": month}
        station_rows.append(item)
        if geoid in known:
            by_tract[geoid].append(item)
    station_rows.sort(key=lambda item: item["station_id"])
    fields = ("station_id", "station_name", "latitude", "longitude", "geoid",
              "departures_latest_month", "arrivals_latest_month", "evening_departures_latest_month",
              "weekend_departures_latest_month", "activity_month")
    write_csv(stage / "entities" / "citibike_stations_latest_month.csv", station_rows, fields)
    located = [item for item in station_rows if item["geoid"] in known]
    occupied_tracts = len(by_tract)
    features = []
    for row in master:
        tract_stations = by_tract[row["geoid"]]
        latitude = float(row["centroid_latitude"])
        longitude = float(row["centroid_longitude"])
        nearest = min(located, key=lambda item: (item["latitude"] - latitude) ** 2 +
                      ((item["longitude"] - longitude) * math.cos(math.radians(latitude))) ** 2)
        distance = 3958.8 * 2 * math.asin(math.sqrt(
            math.sin(math.radians(nearest["latitude"] - latitude) / 2) ** 2 +
            math.cos(math.radians(latitude)) * math.cos(math.radians(nearest["latitude"])) *
            math.sin(math.radians(nearest["longitude"] - longitude) / 2) ** 2))
        feature = {"geoid": row["geoid"], "citibike_station_count": len(tract_stations) or "",
                   "citibike_departures_latest_month": sum(item["departures_latest_month"] for item in tract_stations) if tract_stations else "",
                   "citibike_arrivals_latest_month": sum(item["arrivals_latest_month"] for item in tract_stations) if tract_stations else "",
                   "citibike_evening_departures_latest_month": sum(item["evening_departures_latest_month"] for item in tract_stations) if tract_stations else "",
                   "citibike_weekend_departures_latest_month": sum(item["weekend_departures_latest_month"] for item in tract_stations) if tract_stations else "",
                   "nearest_citibike_distance_miles": round(distance, 6),
                   "nearest_citibike_station_id": nearest["station_id"],
                   "nearest_citibike_station_name": nearest["station_name"],
                   "nearest_citibike_departures_latest_month": nearest["departures_latest_month"],
                   "citibike_activity_month": month}
        row.update(feature)
        features.append(feature)
    write_csv(stage / "features" / "tract_citibike_activity.csv", features, BIKE_FIELDS)
    return {"month": month, "trips": trips, "stations": len(station_rows),
            "stations_in_nyc_tracts": len(located), "tracts_with_stations": occupied_tracts}


def update_catalog(stage, revisions, as_of, results):
    path = stage / "source_catalog.csv"
    rows = read_csv(path)
    for row in rows:
        if row["source"] == "Restaurant inspections" and "restaurants" in revisions:
            row["vintage"] = "DOHMH records downloaded " + revisions["restaurants"]["downloaded_at"][:10]
        elif row["source"] == "MTA ridership" and "mta_subway" in revisions:
            start = revisions["mta_subway"]["publisher_version"].split("_")[1]
            row["vintage"] = f"Subway hourly ridership, week of {start}"
            row["coverage"] = "complete station-hour week, aggregated by station"
        elif row["source"] == "Permitted events" and "events" in revisions:
            row["vintage"] = f"Upcoming {as_of} to {as_of + timedelta(days=89)}"
            row["coverage"] = "90-day rolling window aggregated to community district"
        elif row["source"] == "TLC HVFHV" and "tlc_hvfhv" in revisions:
            row["vintage"] = revisions["tlc_hvfhv"]["publisher_version"] + " trip records"
            row["coverage"] = "complete pickup month aggregated by taxi zone; inherited by tracts"
            row["url"] = revisions["tlc_hvfhv"]["source_url"]
        elif row["source"] == "OpenStreetMap" and "osm" in revisions:
            row["vintage"] = "BBBike New York PBF; replication timestamp " + revisions["osm"]["publisher_version"]
            row["native_grain"] = "OSM node or way"
            row["coverage"] = "tagged NYC food/nightlife points and ways assigned to 2020 tracts"
            row["url"] = revisions["osm"]["source_url"]
        elif row["source"] == "PLUTO" and "pluto" in revisions:
            row["vintage"] = results["pluto"]["source_version"]
            row["coverage"] = "full land-use lots for denominators; mixed-use, commercial-office, and vacant-land parcels for relevant floor-area measures"
        elif row["source"] == "Citi Bike" and "citibike" in revisions:
            row["vintage"] = results["citibike"]["month"] + " trip data"
            row["coverage"] = "full monthly archive aggregated by station and 2020 tract"
            row["url"] = revisions["citibike"]["source_url"]
        elif row["source"] == "Storefront registry" and "storefronts" in revisions:
            row["vintage"] = results["storefronts"]["reporting_year"] + " filings"
            row["coverage"] = results["storefronts"]["reporting_coverage"] + "; one row per BBL; any reported vacancy at the parcel is not confirmed market availability"
            row["url"] = revisions["storefronts"]["source_url"]
        elif row["source"] == "NYC Storefront Rent Statistics" and "storefront_rent_stats" in revisions:
            row["vintage"] = str(results["storefront_rent_stats"]["reporting_year"])
            row["coverage"] = f"{results['storefront_rent_stats']['tracts_with_medians']} tracts with published medians"
            row["url"] = revisions["storefront_rent_stats"]["source_url"]
        elif row["source"] == "NOAA weather" and "weather" in revisions:
            row["vintage"] = "Central Park 2020-" + results["weather"]["latest_date"]
            row["coverage"] = "complete daily station observations through " + results["weather"]["latest_date"]
            row["url"] = revisions["weather"]["source_url"]
        elif row["source"] == "EPA Smart Location Database" and "epa_walkability" in revisions:
            row["vintage"] = "SLD v3; underlying population circa 2018"
            row["coverage"] = "full NYC block groups spatially crosswalked to 2020 tracts; area allocation is estimated"
            row["url"] = revisions["epa_walkability"]["source_url"]
        elif row["source"] == "LODES" and "lodes" in revisions:
            row["vintage"] = revisions["lodes"]["publisher_version"] + " WAC S000 JT00"
            row["coverage"] = f"{results['lodes']['blocks']} NYC workplace blocks aggregated to 2020 tracts"
            row["url"] = revisions["lodes"]["source_url"]
        elif row["source"] == "DOT pedestrian counts" and "pedestrians" in revisions:
            row["vintage"] = f"Latest complete AM/midday/PM monitor counts; newest {results['pedestrians']['latest_period']}"
            row["coverage"] = f"{results['pedestrians']['sites']} monitored sites; nearest-site proxy, not tract foot traffic"
            row["url"] = revisions["pedestrians"]["source_url"]
    if "storefront_rent_stats" in revisions and not any(row["source"] == "NYC Storefront Rent Statistics" for row in rows):
        rows.append({"source": "NYC Storefront Rent Statistics",
                     "vintage": str(results["storefront_rent_stats"]["reporting_year"]),
                     "native_grain": "Class 2 and 4 registered storefronts by census tract",
                     "purpose": "Reported occupied-rent context; not asking rent",
                     "coverage": f"{results['storefront_rent_stats']['tracts_with_medians']} tracts with published medians",
                     "url": revisions["storefront_rent_stats"]["source_url"]})
    write_csv(path, rows, rows[0].keys())
    if "mta_subway" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        for row in rows:
            if row.get("column") == "subway_weekly_ridership":
                row["definition"] = "Full MTA station-complex ridership for the complete week documented in source_catalog.csv."
        write_csv(path, rows, rows[0].keys())
        path = stage / "feature_readiness.csv"
        rows = read_csv(path)
        for row in rows:
            if row.get("use") == "Subway accessibility and ridership":
                row["limitation"] = "Ridership represents one complete week; see source_catalog.csv for dates."
        write_csv(path, rows, rows[0].keys())
        path = stage / "README.md"
        text = path.read_text()
        text = text.replace("Subway activity represents one complete week in March 2025, not an annual average.",
                            "Subway activity represents one complete week, not an annual average; see source_catalog.csv for the dates.")
        path.write_text(text)
    if "tlc_hvfhv" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        for column, definition in (
            ("pickups_latest_month", "HVFHV trips picked up in the taxi zone during the month in source_catalog.csv."),
            ("dropoffs_latest_month", "Drop-offs from trips picked up during that month, by destination taxi zone."),
            ("cbd_congestion_fee_total_latest_month", "Sum of CBD congestion fees for trips picked up in the taxi zone during that month."),
            ("active_days_latest_month", "Distinct pickup dates in that month for the taxi zone."),
            ("taxi_activity_month", "YYYY-MM of the latest integrated TLC HVFHV activity."),
        ):
            if not any(row.get("file") == "master_tract_features.csv" and row.get("column") == column for row in rows):
                rows.append({"file": "master_tract_features.csv", "column": column, "definition": definition, "unit": "varies"})
        write_csv(path, rows, rows[0].keys())
    if "pluto" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        definitions = {
            "total_lot_count": ("All PLUTO lots with a nonzero land-use code assigned to the 2020 tract.", "lots"),
            "commercial_mixed_lot_share_all": ("PLUTO codes 04 and 05 parcels divided by all tract lots with a nonzero land-use code.", "share"),
            "vacant_land_share_all_lots": ("PLUTO code 11 vacant-land parcels divided by all tract lots with a nonzero land-use code; not storefront vacancy.", "share"),
            "mean_commercial_mixed_num_floors": ("Arithmetic mean of positive reported PLUTO building floors on code 04 and 05 lots; missing and zero values excluded.", "floors"),
        }
        for row in rows:
            if row.get("file") == "master_tract_features.csv" and row.get("column") == "vacant_land_parcel_count":
                row["definition"] = "PLUTO land-use code 11 (vacant land) parcels in the 2020 tract."
            elif row.get("file") == "master_tract_features.csv" and row.get("column") == "vacant_land_parcel_share":
                row["definition"] = "Code 11 vacant land parcels divided by code 04, 05, and 11 relevant parcels in the tract."
        for column, (definition, unit) in definitions.items():
            for file in ("master_tract_features.csv", "features/tract_land_use.csv"):
                if not any(row["file"] == file and row["column"] == column for row in rows):
                    rows.append({"file": file, "column": column, "definition": definition, "unit": unit})
        write_csv(path, rows, rows[0].keys())
    if "citibike" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        definitions = {
            "citibike_departures_latest_month": "Citi Bike trips starting at stations in the tract during citibike_activity_month.",
            "citibike_arrivals_latest_month": "Citi Bike trips ending at stations in the tract during citibike_activity_month.",
            "citibike_evening_departures_latest_month": "Tract station departures from 17:00 through 04:59 during citibike_activity_month.",
            "citibike_weekend_departures_latest_month": "Saturday and Sunday tract station departures during citibike_activity_month.",
            "nearest_citibike_departures_latest_month": "Departures at the nearest station during citibike_activity_month.",
            "citibike_activity_month": "YYYY-MM of the latest complete integrated Citi Bike month.",
        }
        for column, definition in definitions.items():
            if not any(row.get("file") == "master_tract_features.csv" and row.get("column") == column for row in rows):
                rows.append({"file": "master_tract_features.csv", "column": column,
                             "definition": definition, "unit": "month" if column == "citibike_activity_month" else "trips"})
        write_csv(path, rows, rows[0].keys())
        path = stage / "README.md"
        content = path.read_text()
        content = content.replace(
            "Citi Bike activity represents the complete August 2026 archive and does not cover neighborhoods without Citi Bike service.",
            "Citi Bike latest-month activity uses the complete month listed in source_catalog.csv; August 2026 columns remain historical. Areas without Citi Bike stations have no tract station activity."
        )
        path.write_text(content)
    if "storefront_rent_stats" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        definitions = {
            "reported_median_monthly_rent_psf": ("Published median monthly occupied storefront rent per square foot; not asking rent.", "USD/sqft/month"),
            "reported_median_storefront_sqft": ("Published median registered storefront floor area in the tract.", "sqft"),
            "registered_storefronts": ("Registered storefront count in the published rent-statistics table.", "storefronts"),
            "leased_storefronts": ("Leased storefront count in the published rent-statistics table.", "storefronts"),
            "rent_reporting_year": ("Reporting year of the published rent-statistics values.", "year"),
        }
        for column, (definition, unit) in definitions.items():
            if not any(row.get("file") == "master_tract_features.csv" and row.get("column") == column for row in rows):
                rows.append({"file": "master_tract_features.csv", "column": column,
                             "definition": definition, "unit": unit})
        write_csv(path, rows, rows[0].keys())
        path = stage / "feature_readiness.csv"
        rows = read_csv(path)
        if not any(row.get("use") == "Occupied storefront rent context" for row in rows):
            rows.append({"use": "Occupied storefront rent context",
                         "primary_output": "features/tract_storefront_rent_context.csv",
                         "analysis_grain": "tract", "status": "ready with reporting caveat",
                         "limitation": "Published medians describe reported occupied storefronts, not current asking rents or live listings."})
        write_csv(path, rows, rows[0].keys())
    if "events" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        for column in EVENT_ROLLING_FIELDS[2:]:
            if not any(row.get("file") == "master_tract_features.csv" and row.get("column") == column for row in rows):
                rows.append({"file": "master_tract_features.csv", "column": column,
                             "definition": "NYC permitted events within the rolling 90-day window in source_catalog.csv, aggregated by community district.",
                             "unit": "hours" if "hours" in column else "date" if "date" in column else "events"})
        write_csv(path, rows, rows[0].keys())
        path = stage / "feature_readiness.csv"
        rows = read_csv(path)
        for row in rows:
            if row.get("use") == "Event-driven demand":
                row["primary_output"] = "features/community_district_events_next_90_days.csv"
        write_csv(path, rows, rows[0].keys())
    if "epa_walkability" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        definitions = {
            "walkability_population_weight": "Estimated 2018 EPA block-group population allocated to 2020 tracts by polygon overlap area.",
            "national_walkability_index": "EPA SLD v3 index spatially crosswalked to 2020 tracts and weighted by area-allocated 2018 population.",
            "smart_location_score": "EPA SLD v3 score spatially crosswalked to 2020 tracts and weighted by area-allocated 2018 population.",
        }
        for row in rows:
            if row.get("file") == "master_tract_features.csv" and row.get("column") in definitions:
                row["definition"] = definitions[row["column"]]
        write_csv(path, rows, rows[0].keys())
        path = stage / "feature_readiness.csv"
        rows = read_csv(path)
        for row in rows:
            if row.get("use") == "Walkability":
                row["limitation"] = "EPA SLD v3 reflects older built-environment data; 2020 tract values use area-allocated block-group population and require crosswalk sensitivity testing."
        write_csv(path, rows, rows[0].keys())
    if "lodes" in revisions or "pedestrians" in revisions:
        path = stage / "data_dictionary.csv"
        rows = read_csv(path)
        for row in rows:
            if row.get("file") != "master_tract_features.csv":
                continue
            if "lodes" in revisions and (row["column"].startswith("jobs_") or row["column"] in {"total_jobs", "job_density_per_sq_mile"}):
                row["definition"] = f"2023 LODES WAC S000 JT00 workplace jobs aggregated from full New York block records to 2020 NYC tracts; {row['column']}." if row["column"] != "jobs_per_1000_residents" else "2023 LODES workplace jobs per 1,000 ACS 2024 tract residents; cross-vintage context only."
            elif "pedestrians" in revisions and row["column"].startswith("nearest_pedestrian_count_site_"):
                row["definition"] = "Nearest NYC DOT monitored point to tract centroid; latest complete AM, midday and PM count at that point, not observed tract-wide foot traffic." if row["column"].endswith("total") else "Nearest NYC DOT monitored point to tract centroid; see source_catalog.csv for vintage and spatial coverage."
        write_csv(path, rows, rows[0].keys())
        path = stage / "feature_readiness.csv"
        rows = read_csv(path)
        for row in rows:
            if "lodes" in revisions and row.get("use") == "Nearby worker population":
                row["limitation"] = "Full 2023 LODES workplace blocks; distinct from resident population and not current-year employment."
            elif "pedestrians" in revisions and row.get("use") == "Estimated pedestrian activity":
                row["status"] = "ready with coverage warning"
                row["limitation"] = f"Only {results['pedestrians']['sites']} DOT monitor points; counts are nearest-site observations, not tract-wide estimates. Distance is provided."
        write_csv(path, rows, rows[0].keys())


def update_validation_checks(stage, results):
    path = stage / "validation_checks.csv"
    rows = read_csv(path)
    for row in rows:
        if row["check"] == "restaurant establishments assigned to a tract" and "restaurants" in results:
            row["observed"] = results["restaurants"]["establishments"] - results["restaurants"]["unlocated"]
            row["expected_or_source"] = results["restaurants"]["establishments"]
        elif row["check"] == "restaurant CAMIS identifiers are unique" and "restaurants" in results:
            row["observed"] = row["expected_or_source"] = results["restaurants"]["establishments"]
        elif row["check"] == "subway station-complex IDs are unique" and "mta_subway" in results:
            row["observed"] = row["expected_or_source"] = results["mta_subway"]["stations"]
        elif row["check"] == "OSM POIs assigned to a tract" and "osm" in results:
            row["observed"] = row["expected_or_source"] = results["osm"]["pois"]
        elif row["check"] == "relevant PLUTO parcels represented in tract features" and "pluto" in results:
            row["observed"] = results["pluto"]["relevant_parcels"]
            row["expected_or_source"] = results["pluto"]["relevant_parcels"] + results["pluto"]["unassigned_parcels"]
        elif row["check"] == "storefront BBL identifiers are unique" and "storefronts" in results:
            row["observed"] = row["expected_or_source"] = results["storefronts"]["properties"]
        elif row["check"] == "Citi Bike station IDs are unique" and "citibike" in results:
            row["observed"] = row["expected_or_source"] = results["citibike"]["stations"]
    write_csv(path, rows, rows[0].keys())


def update_qa(stage, changed):
    path = stage / "qa_report.csv"
    rows = read_csv(path)
    by_file = {row["file"]: row for row in rows}
    for filename in changed:
        table = read_csv(stage / filename)
        item = by_file.get(filename)
        if item is None:
            item = {field: "" for field in rows[0]}
            item["file"] = filename
            rows.append(item)
        if table:
            fields = list(table[0])
        else:
            with (stage / filename).open(newline="", encoding="utf-8") as stream:
                fields = next(csv.reader(stream))
        blanks = sum(value == "" for row in table for value in row.values())
        item.update({"rows": len(table), "columns": len(fields), "duplicate_rows": 0,
                     "blank_rows": 0, "missing_cell_percent": round(100 * blanks / (len(table) * len(fields)), 3) if table else 0,
                     "status": "pass"})
    write_csv(path, rows, rows[0].keys())


def validate_release(stage, baseline_rows, changed):
    master = read_csv(stage / "master_tract_features.csv")
    ids = [row["geoid"] for row in master]
    if len(master) != baseline_rows or len(ids) != len(set(ids)) or any(len(geoid) != 11 or not geoid.isdigit() for geoid in ids):
        raise ValueError("Master tract coverage or GEOID uniqueness failed")
    geometry = json.loads((stage / "geography" / "nyc_2020_census_tracts.geojson").read_text())
    geometry_ids = [feature["properties"]["geoid"] for feature in geometry["features"]]
    if len(geometry_ids) != len(set(geometry_ids)) or set(ids) != set(geometry_ids):
        raise ValueError("Master GEOIDs do not match the 2020 tract geography")
    fields = set(master[0])
    dictionary = read_csv(stage / "data_dictionary.csv")
    documented = {row["column"] for row in dictionary if row["file"] == "master_tract_features.csv"}
    if fields != documented:
        raise ValueError(f"Master/data dictionary column mismatch: {sorted(fields ^ documented)}")
    feature_tables = 0
    for path in sorted((stage / "features").glob("tract_*.csv")):
        rows = read_csv(path)
        if not rows:
            raise ValueError(f"Empty tract feature table: {path.name}")
        feature_ids = [row["geoid"] for row in rows]
        if len(feature_ids) != len(set(feature_ids)) or not set(feature_ids) <= set(ids):
            raise ValueError(f"Invalid or duplicate 2020 tract GEOIDs: {path.name}")
        extra_fields = set(rows[0]) - fields - {"location_id"}
        if extra_fields:
            raise ValueError(f"Feature columns absent from master in {path.name}: {sorted(extra_fields)}")
        feature_tables += 1
    for feature_name, keys in changed:
        lookup = {row[keys[0]]: row for row in read_csv(stage / feature_name)}
        for row in master:
            item = lookup.get(row.get(keys[0]))
            if item and any(str(row.get(field, "")) != str(item.get(field, "")) for field in keys[1:]):
                raise ValueError(f"Master/feature mismatch: {feature_name} / {row['geoid']}")
    return {"tract_rows": len(master), "unique_geoids": len(set(ids)),
            "geography_geoids": len(geometry_ids), "feature_tables_checked": feature_tables,
            "rebuilt_tables_checked": len(changed), "documented_columns": len(documented)}


def rebuild_master_spec_context(stage, master):
    result = enrich_master_spec(master, stage / "geography" / "nyc_2020_census_tracts.geojson")
    fields = ("geoid", *SPEC_FIELDS)
    write_csv(stage / "features" / "tract_master_spec_context.csv", master, fields)
    path = stage / "data_dictionary.csv"
    dictionary = read_csv(path)
    existing = {(row["file"], row["column"]) for row in dictionary}
    for file in ("master_tract_features.csv", "features/tract_master_spec_context.csv"):
        for column, (definition, unit) in SPEC_FIELDS.items():
            if (file, column) not in existing:
                dictionary.append({"file": file, "column": column, "definition": definition, "unit": unit})
    for row in dictionary:
        if row["file"] in {"master_tract_features.csv", "features/tract_master_spec_context.csv"} and row["column"] in SPEC_FIELDS:
            row["definition"], row["unit"] = SPEC_FIELDS[row["column"]]
    corrections = {
        "reported_storefront_property_count": "Distinct BBL parcels with a DOF storefront report in the selected year; not a count of distinct storefront spaces.",
        "reported_vacant_storefront_count": "Distinct reported BBL parcels with at least one vacant storefront in the latest filing date; not a count of vacant spaces.",
        "reported_storefront_vacancy_share": "Unavailable: BBL-level filings do not identify all individual spaces consistently enough for a storefront-level vacancy denominator.",
    }
    for row in dictionary:
        if row["file"] == "master_tract_features.csv" and row["column"] in corrections:
            row["definition"] = corrections[row["column"]]
    write_csv(path, dictionary, dictionary[0].keys())
    path = stage / "feature_readiness.csv"
    readiness = read_csv(path)
    if not any(row["use"] == "Normalized current tract context" for row in readiness):
        readiness.append({"use": "Normalized current tract context", "primary_output": "features/tract_master_spec_context.csv",
                          "analysis_grain": "2020 census tract", "status": "current context only",
                          "limitation": "Mixes 2023 LODES, 2024 ACS/DOF, and latest mobility/OSM/PLUTO vintages; do not use as retrospective restaurant survival predictors."})
    write_csv(path, readiness, readiness[0].keys())
    return result


def run(selected, as_of, publish=False, download=False, pinned=None):
    pinned = pinned or {}
    INTEGRATED_ROOT.mkdir(parents=True, exist_ok=True)
    with (INTEGRATED_ROOT / ".refresh.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if download:
            for name in selected:
                source = SOURCES[name]
                download_source(source, resolve(source, as_of))
        raw = {name: raw_revision(name, pinned.get(name)) for name in selected}
        active = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
        stage = INTEGRATED_ROOT / (".staging-" + uuid.uuid4().hex)
        shutil.copytree(active, stage)
        try:
            master = read_csv(stage / "master_tract_features.csv")
            old_count = len(master)
            results, changed, revisions = {}, [], {}
            extra_qa = []
            for name in selected:
                path, revision = raw[name]
                revisions[name] = revision
                if name == "restaurants":
                    results[name] = rebuild_restaurants(stage, path, master)
                    changed.append(("features/tract_restaurant_quality.csv", QUALITY_FIELDS))
                elif name == "events":
                    results[name] = rebuild_events(stage, path, master, as_of)
                    changed.append(("features/community_district_events_2026.csv", (EVENT_FIELDS[0], *EVENT_FIELDS[2:])))
                    changed.append(("features/community_district_events_next_90_days.csv",
                                    (EVENT_ROLLING_FIELDS[0], *EVENT_ROLLING_FIELDS[2:])))
                elif name == "mta_subway":
                    results[name] = rebuild_subway(stage, path, master)
                    changed.append(("features/tract_subway_access.csv", SUBWAY_FIELDS))
                    from enrich_location_data import rebuild_subway_patterns
                    patterns = rebuild_subway_patterns(stage, path, master, revision)
                    changed.extend(patterns.pop("_tables"))
                    extra_qa.extend(patterns.pop("_qa_files"))
                    results[name]["time_patterns"] = patterns
                elif name == "tlc_hvfhv":
                    results[name] = rebuild_tlc(stage, path, master, revision["publisher_version"])
                    changed.append(("features/tract_taxi_activity.csv", ("geoid", *TAXI_FIELDS[1:])))
                elif name == "osm":
                    results[name] = rebuild_osm(stage, path, master, read_csv, write_csv, polygon_index, containing_tract)
                    changed.append(("features/tract_competition.csv", ("geoid", *OSM_MASTER_FIELDS)))
                elif name == "pluto":
                    results[name] = rebuild_pluto(stage, path, master)
                    changed.append(("features/tract_land_use.csv", PLUTO_FIELDS))
                elif name == "citibike":
                    results[name] = rebuild_citibike(stage, path, master, revision["publisher_version"])
                    changed.append(("features/tract_citibike_activity.csv", BIKE_FIELDS))
                elif name == "storefronts":
                    results[name] = rebuild_storefronts(stage, path, master)
                    changed.append(("features/tract_storefront_availability.csv", STOREFRONT_FIELDS))
                elif name == "storefront_rent_stats":
                    results[name] = rebuild_rent_stats(stage, path, master)
                    changed.append(("features/tract_storefront_rent_context.csv", RENT_FIELDS))
                elif name == "weather":
                    results[name] = rebuild_weather(stage, path, as_of)
                elif name == "epa_walkability":
                    results[name] = rebuild_epa(stage, path, master, write_csv)
                    changed.append(("features/tract_walkability.csv", EPA_FIELDS))
                elif name == "lodes":
                    results[name] = rebuild_lodes(stage, path, master)
                    changed.append(("features/tract_workers.csv", WORKER_FIELDS))
                elif name == "pedestrians":
                    results[name] = rebuild_pedestrians(stage, path, master)
                    changed.append(("features/tract_pedestrian_access.csv", PEDESTRIAN_FIELDS))
                elif name in ENRICHMENT_SOURCES:
                    from enrich_location_data import rebuild
                    result = rebuild(name, stage, path, master, revision)
                    changed.extend(result.pop("_tables"))
                    extra_qa.extend(result.pop("_qa_files"))
                    results[name] = result
            if set(selected) & {"lodes", "lodes_rac"}:
                from enrich_location_data import synchronize_resident_ratio
                workplace_year = (revisions["lodes"]["publisher_version"] if "lodes" in revisions else
                                  next(row["vintage"].split()[0] for row in read_csv(stage / "source_catalog.csv") if row["source"] == "LODES"))
                ratio_table = synchronize_resident_ratio(stage, master, workplace_year)
                if ratio_table:
                    changed.append(ratio_table)
                    extra_qa.append(ratio_table[0])
            results["master_spec_context"] = rebuild_master_spec_context(stage, master)
            changed.append(("features/tract_master_spec_context.csv", ("geoid", *SPEC_FIELDS)))
            from complete_master import complete
            completion = complete(stage, master, ROOT / "data")
            changed.extend(completion.pop("_tables"))
            extra_qa.extend(completion.pop("_qa_files"))
            results["master_completion"] = completion
            master_fields = list(master[0])
            write_csv(stage / "master_tract_features.csv", master, master_fields)
            update_catalog(stage, revisions, as_of, results)
            update_validation_checks(stage, results)
            qa_files = ["master_tract_features.csv", "source_catalog.csv", "validation_checks.csv",
                        "features/tract_master_spec_context.csv", "data_dictionary.csv", "feature_readiness.csv"]
            if "restaurants" in selected:
                qa_files += ["entities/current_restaurants.csv", "features/tract_restaurant_quality.csv"]
            if "events" in selected:
                qa_files += ["features/community_district_events_2026.csv",
                             "features/community_district_events_next_90_days.csv", "data_dictionary.csv",
                             "feature_readiness.csv"]
            if "mta_subway" in selected:
                qa_files += ["entities/subway_stations_weekly_activity.csv", "features/tract_subway_access.csv",
                             "data_dictionary.csv", "feature_readiness.csv"]
            if "tlc_hvfhv" in selected:
                qa_files += ["features/tract_taxi_activity.csv", "data_dictionary.csv"]
            if "osm" in selected:
                qa_files += ["entities/food_nightlife_pois.csv", "features/tract_competition.csv"]
            if "pluto" in selected:
                qa_files += ["features/tract_land_use.csv", "data_dictionary.csv"]
            if "citibike" in selected:
                qa_files += ["entities/citibike_stations_latest_month.csv", "features/tract_citibike_activity.csv", "data_dictionary.csv"]
            if "storefronts" in selected:
                qa_files += ["entities/current_storefronts.csv", "features/tract_storefront_availability.csv"]
            if "storefront_rent_stats" in selected:
                qa_files += ["features/tract_storefront_rent_context.csv", "data_dictionary.csv", "feature_readiness.csv"]
            if "weather" in selected:
                qa_files.append("features/daily_weather_central_park.csv")
            if "epa_walkability" in selected:
                qa_files += ["features/tract_walkability.csv", "data_dictionary.csv", "feature_readiness.csv"]
            if "lodes" in selected:
                qa_files += ["features/tract_workers.csv", "data_dictionary.csv", "feature_readiness.csv"]
            if "pedestrians" in selected:
                qa_files += ["entities/pedestrian_count_sites_latest.csv", "features/tract_pedestrian_access.csv",
                             "data_dictionary.csv", "feature_readiness.csv"]
            update_qa(stage, list(dict.fromkeys(qa_files + extra_qa)))
            validation = validate_release(stage, old_count, changed)
            if results["master_completion"].get("tracts"):
                from audit_training_data import quality_audit
                dictionary = {r["column"]: r for r in read_csv(stage / "data_dictionary.csv")
                              if r["file"] == "master_tract_features.csv"}
                checked_master = read_csv(stage / "master_tract_features.csv")
                profiles, issues = quality_audit(checked_master, list(checked_master[0]), dictionary)
                if issues:
                    raise ValueError(f"Completed master failed quality checks: {issues[:3]}")
                write_csv(stage / "master_feature_quality.csv", profiles, profiles[0].keys())
                validation["master_quality_issues"] = len(issues)
            if set(selected) & set(ENRICHMENT_SOURCES):
                from enrich_location_data import validate_enrichment
                validation["enrichment"] = validate_enrichment(stage)
            if "osm" in selected:
                for row in master:
                    count = row.get("food_nightlife_poi_count", "")
                    people = row.get("population_2024", "")
                    rate = row.get("food_nightlife_pois_per_1000_residents", "")
                    if count and people and float(people) > 0 and abs(float(rate) - 1000 * float(count) / float(people)) > 1e-8:
                        raise ValueError(f"OSM per-resident density mismatch: {row['geoid']}")
            audit_summary = None
            if set(selected) & {"osm", "restaurants", "mta_subway", "pluto", "citibike", "storefronts", "epa_walkability", "lodes", "pedestrians", "acs_context"}:
                from audit_scoring import audit_releases
                audit = audit_releases(active, stage)
                (stage / "score_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
                primary = audit["refresh_changes"]["format:restaurant"]
                audit_summary = {"base_restaurant_changed_fraction": primary["changed_fraction"],
                                 "base_restaurant_median_absolute_change": primary["median_absolute_change"],
                                 "base_restaurant_top_decile_overlap": primary["top_decile_overlap"],
                                 "review_flags": audit["review_flags"], "full_report": "score_audit.json"}
            scoring_inputs = ("master_tract_features.csv", "entities/current_restaurants.csv",
                              "entities/food_nightlife_pois.csv", "geography/nyc_2020_census_tracts.geojson")
            report = {"created_at": datetime.now(timezone.utc).isoformat(), "as_of": as_of.isoformat(),
                      "base_release": active.name, "sources_refreshed": list(selected), "results": results,
                      "raw_revisions": {name: revision["directory"] for name, revision in revisions.items()},
                      "raw_sha256": {name: sha256(path) for name, (path, _) in raw.items()},
                      "scoring_input_sha256": {name: sha256(stage / name) for name in scoring_inputs},
                      "score_audit": audit_summary,
                      "carried_forward_sources": [name for name in SOURCES if name not in selected],
                      "validation": validation,
                      "limitation": "Only selected signals were rebuilt; other sources retain their previous vintages."}
            (stage / "refresh_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
            if publish:
                release_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
                releases = INTEGRATED_ROOT / "releases"
                releases.mkdir(exist_ok=True)
                stage.rename(releases / release_name)
                activate(release_name)
                report["published_release"] = release_name
            else:
                report["status"] = "preview_only"
            return report
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def activate(release_name):
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}", release_name):
        raise ValueError("Invalid release name")
    target = INTEGRATED_ROOT / "releases" / release_name
    if not target.is_dir() or not (target / "refresh_manifest.json").is_file():
        raise ValueError("Release does not exist or lacks its manifest")
    temp_link = INTEGRATED_ROOT / (".current-" + uuid.uuid4().hex)
    temp_link.symlink_to(Path("releases") / release_name, target_is_directory=True)
    os.replace(temp_link, CURRENT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", choices=SUPPORTED, help="Selected transform; default all supported sources")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Event-window date, YYYY-MM-DD")
    parser.add_argument("--download", action="store_true", help="Refresh selected raw sources before rebuilding")
    parser.add_argument("--publish", action="store_true", help="Atomically activate the validated release")
    parser.add_argument("--revision", action="append", default=[], metavar="SOURCE=DIRECTORY",
                        help="Pin a raw revision for reproducibility")
    parser.add_argument("--list-releases", action="store_true", help="List available releases and exit")
    parser.add_argument("--activate", metavar="RELEASE", help="Atomically switch to an existing release")
    args = parser.parse_args()
    try:
        if args.list_releases:
            print("baseline:", BASELINE)
            print("active:", CURRENT.resolve() if CURRENT.is_dir() else BASELINE)
            for path in sorted((INTEGRATED_ROOT / "releases").glob("*")) if (INTEGRATED_ROOT / "releases").exists() else ():
                if path.is_dir() and (path / "refresh_manifest.json").exists():
                    print(path.name)
            return
        if args.activate:
            with (INTEGRATED_ROOT / ".refresh.lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                activate(args.activate)
            print("Activated", args.activate)
            return
        as_of = date.fromisoformat(args.as_of)
        pinned = dict(item.split("=", 1) for item in args.revision)
        if any(name not in SUPPORTED for name in pinned):
            raise ValueError("Pinned revision name must be a supported source")
        report = run(tuple(dict.fromkeys(args.source or SUPPORTED)), as_of, args.publish, args.download, pinned)
    except (ValueError, OSError, KeyError, IndexError) as error:
        parser.exit(2, f"Refresh failed; active release unchanged: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
