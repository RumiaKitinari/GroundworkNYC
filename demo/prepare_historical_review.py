"""Review candidates from official historical DOT outdoor-dining inspections."""

import argparse
import csv
import hashlib
import html
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from build_historical_snapshots import download_archive
from evaluation import fingerprint
from prepare_historical_cohort import EVIDENCE_FIELDS
from refresh_integrated import BASELINE, CURRENT, ROOT


SOURCE_URL = "https://data.cityofnewyork.us/Transportation/Open-Restaurants-Inspections-Historical-/4dx7-axux"
DOWNLOAD_URL = "https://data.cityofnewyork.us/api/views/4dx7-axux/rows.csv?accessType=DOWNLOAD"
SOURCE_PATH = ROOT / "data/evaluation/source_archives/dot_open_restaurants_history/source.csv"
START = date(2023, 12, 7)
END = date(2024, 5, 1)
CONTEXT_FIELDS = ("candidate_name", "candidate_address", "candidate_baseline_on",
                  "source_inspection_id", "candidate_source_url", "current_inventory_match_basis",
                  "candidate_match_name", "sampling_stratum", "selection_probability", "review_note")
REVIEW_FIELDS = EVIDENCE_FIELDS + CONTEXT_FIELDS
WARNING = ("Outdoor-dining participants are a selected subset of NYC restaurants. "
           "A historical setup inspection is a baseline lead, not proof of operation. "
           "A missing current-inventory match is not a closure label. Verify both dates independently.")


def normalized(value):
    return " ".join(re.findall(r"[a-z0-9]+", html.unescape(value or "").lower()))


def normalized_address(value):
    aliases = {"avenue": "ave", "street": "st", "boulevard": "blvd", "road": "rd",
               "highway": "hwy", "place": "pl", "drive": "dr", "east": "e", "west": "w",
               "north": "n", "south": "s"}
    return " ".join(aliases.get(token, token) for token in normalized(value).split())


def distance_meters(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    haversine = (math.sin((lat2 - lat1) / 2) ** 2 +
                 math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 12_742_000 * math.asin(min(1, math.sqrt(haversine)))


def match_inventory(name, address, geoid, latitude, longitude, current_keys, current_by_tract):
    key = (geoid, normalized(name), normalized_address(address))
    if key in current_keys:
        return "exact_name_address", current_keys[key]
    from difflib import SequenceMatcher
    for current in current_by_tract.get(geoid, []):
        if current["coordinates"] is None or distance_meters((latitude, longitude), current["coordinates"]) > 75:
            continue
        other = normalized(current["name"])
        similar = SequenceMatcher(None, key[1], other).ratio() >= .84
        contained = min(len(key[1]), len(other)) >= 7 and (key[1] in other or other in key[1])
        if similar or contained:
            return "nearby_name", current["name"]
    return "none", ""


def field(row, name):
    return next((value or "" for key, value in row.items()
                 if re.sub(r"[^a-z0-9]", "", key.lower()) == name), "")


def inspection_day(value):
    text = (value or "").strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return datetime.strptime(text.split(" ", 1)[0], "%m/%d/%Y").date()


def tract_lookup(geojson_path):
    data = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    polygons = [shape(feature["geometry"]) for feature in data["features"]]
    geoids = [feature["properties"]["geoid"] for feature in data["features"]]
    return STRtree(polygons), polygons, geoids


def build_review_queue(history_path, master_path, geography_path, current_path,
                       per_borough_per_group=10, seed=440):
    with Path(master_path).open(newline="", encoding="utf-8-sig") as stream:
        tracts = {row["geoid"]: row for row in csv.DictReader(stream)}
    current_keys = {}
    current_by_tract = defaultdict(list)
    with Path(current_path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            name = row["dba"]
            current_keys[(row.get("geoid", ""), normalized(name),
                          normalized_address(row["building"] + " " + row["street"]))] = name
            try:
                coordinates = (float(row["latitude"]), float(row["longitude"]))
            except (KeyError, ValueError):
                coordinates = None
            current_by_tract[row.get("geoid", "")].append({"name": name, "coordinates": coordinates})
    tree, polygons, geoids = tract_lookup(geography_path)
    candidates = {}
    counts = Counter()
    with Path(history_path).open(newline="", encoding="utf-8-sig") as stream:
        for record in csv.DictReader(stream):
            counts["source_rows"] += 1
            try:
                day = inspection_day(field(record, "inspectedon"))
            except ValueError:
                counts["invalid_inspection_date"] += 1
                continue
            if not START <= day <= END or field(record, "skippedreason").strip():
                continue
            name = field(record, "restaurantname").strip()
            address = field(record, "businessaddress").strip()
            borough = field(record, "borough").strip()
            key = (normalized(borough), normalized(name), normalized(address))
            if not all(key):
                counts["missing_identity"] += 1
                continue
            if key in candidates and day <= candidates[key]["day"]:
                continue
            try:
                point = Point(float(field(record, "longitude")), float(field(record, "latitude")))
            except ValueError:
                counts["missing_coordinates"] += 1
                continue
            matches = [int(index) for index in tree.query(point) if polygons[int(index)].covers(point)]
            if len(matches) != 1:
                counts["unmatched_geography"] += 1
                continue
            tract = tracts.get(geoids[matches[0]])
            if not tract or normalized(tract["borough"]) != key[0] or not tract.get("nta_code"):
                counts["inconsistent_geography"] += 1
                continue
            basis, match_name = match_inventory(name, address, tract["geoid"], point.y, point.x,
                                                current_keys, current_by_tract)
            candidates[key] = {"record": record, "day": day, "name": name, "address": address,
                               "tract": tract, "match_basis": basis, "match_name": match_name}
    groups = defaultdict(list)
    for key, candidate in candidates.items():
        groups[(candidate["tract"]["borough"], candidate["match_basis"] != "none")].append((key, candidate))
    rng = random.Random(seed)
    queue = []
    for (borough, current_match), group in sorted(groups.items()):
        sampled = rng.sample(group, min(per_borough_per_group, len(group)))
        selection_probability = len(sampled) / len(group)
        for key, candidate in sampled:
            row = dict.fromkeys(REVIEW_FIELDS, "")
            row.update(business_id="dot-" + hashlib.sha256("|".join(key).encode()).hexdigest()[:16],
                       geoid=candidate["tract"]["geoid"], nta_code=candidate["tract"]["nta_code"],
                       borough=borough, verification_status="independent_verification_required",
                       outcome_status="unresolved", candidate_name=candidate["name"],
                       candidate_address=candidate["address"],
                       candidate_baseline_on=candidate["day"].isoformat(),
                       source_inspection_id=field(candidate["record"], "restaurantinspectionid"),
                       candidate_source_url=SOURCE_URL,
                       current_inventory_match_basis=candidate["match_basis"],
                       candidate_match_name=candidate["match_name"],
                       sampling_stratum=f"{borough}:{'matched' if current_match else 'unmatched'}",
                       selection_probability=round(selection_probability, 8),
                       review_note="Review historical operation and a dated follow-up; inventory match is not an outcome.")
            queue.append(row)
    return queue, {"source_rows": counts["source_rows"], "unique_geocoded_candidates": len(candidates),
                   "by_current_match_basis": dict(Counter(candidate["match_basis"]
                                                          for candidate in candidates.values())),
                   "excluded": {key: value for key, value in counts.items() if key != "source_rows"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--per-borough-per-group", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.per_borough_per_group < 1:
        parser.error("--per-borough-per-group must be positive")
    if args.source == SOURCE_PATH:
        download_archive(SOURCE_PATH, DOWNLOAD_URL, 1_000_000)
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    master = release / "master_tract_features.csv"
    geography = release / "geography/nyc_2020_census_tracts.geojson"
    current = release / "entities/current_restaurants.csv"
    queue, audit = build_review_queue(args.source, master, geography, current,
                                      args.per_borough_per_group)
    if not queue:
        raise ValueError("No review candidates matched the observation window and geography; inspect source schema.")
    output = args.output or ROOT / "data/evaluation" / f"historical_review_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Review queue already exists; choose a new output path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(queue)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "review_only",
                "training_eligible": False, "rows": len(queue), "sampled_by_borough_and_match":
                dict(Counter(row["sampling_stratum"] for row in queue)),
                "source_url": SOURCE_URL, "source_observation_window": [START.isoformat(), END.isoformat()],
                "source_fingerprints": {str(path): fingerprint(path) for path in
                                        (args.source, master, geography, current)},
                "audit": audit, "warning": WARNING}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, indent=2))


if __name__ == "__main__":
    main()
