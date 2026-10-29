"""Match dated Foursquare place-status leads to the full DOHMH review cohort."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address, normalized_name
from refresh_integrated import ROOT


EXTRA_FIELDS = ("fsq_match_status", "fsq_match_method", "fsq_candidate_count",
                "fsq_place_ids", "fsq_names", "fsq_marked_closed_dates",
                "fsq_distance_meters", "fsq_place_urls", "fsq_later_dohmh_snapshot")


def distance_meters(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    p1, p2 = radians(lat1), radians(lat2)
    delta_p, delta_l = p2 - p1, radians(lon2 - lon1)
    a = sin(delta_p / 2) ** 2 + cos(p1) * cos(p2) * sin(delta_l / 2) ** 2
    return 2 * radius * asin(min(1, sqrt(a)))


def load_places(path):
    by_address, by_name_zip, seen = defaultdict(list), defaultdict(list), set()
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        needed = {"fsq_place_id", "name", "latitude", "longitude", "address",
                  "postcode", "date_closed"}
        if not needed <= set(reader.fieldnames or []):
            raise ValueError("Foursquare export has missing fields.")
        for row in reader:
            identity = row["fsq_place_id"]
            if not identity or identity in seen:
                raise ValueError("Foursquare place IDs must be unique and nonempty.")
            seen.add(identity)
            name = normalized_name(row["name"])
            street, zipcode = normalized_address(row["address"], row["postcode"])
            if not name or not zipcode or not row["latitude"] or not row["longitude"]:
                continue
            row["_name"] = name
            row["_street"] = street
            row["_zip"] = zipcode
            row["_lat"] = float(row["latitude"])
            row["_lon"] = float(row["longitude"])
            if street:
                by_address[(street, zipcode)].append(row)
            by_name_zip[(name, zipcode)].append(row)
    return by_address, by_name_zip, len(seen)


def match_case(case, location, by_address, by_name_zip):
    name = normalized_name(case["candidate_name"])
    street, zipcode = candidate_address(case["candidate_address"])
    if not name or not street or not zipcode or not location.get("latitude") or not location.get("longitude"):
        return [], ""
    lat, lon = float(location["latitude"]), float(location["longitude"])
    candidates = {}
    for place in by_address.get((street, zipcode), []):
        distance = distance_meters(lat, lon, place["_lat"], place["_lon"])
        if distance > 150:
            continue
        similarity = SequenceMatcher(None, name, place["_name"]).ratio()
        if name == place["_name"]:
            method = "exact_name_address_zip_within_150m"
        elif similarity >= .9:
            method = "similar_name_exact_address_zip_within_150m"
        else:
            continue
        candidates[place["fsq_place_id"]] = (place, distance, method)
    for place in by_name_zip.get((name, zipcode), []):
        distance = distance_meters(lat, lon, place["_lat"], place["_lon"])
        if distance <= 50 and place["fsq_place_id"] not in candidates:
            candidates[place["fsq_place_id"]] = (place, distance, "exact_name_zip_within_50m")
    results = sorted(candidates.values(), key=lambda item: (item[1], item[0]["fsq_place_id"]))
    return results, results[0][2] if len(results) == 1 else "multiple_identity_candidates" if results else ""


def attach_leads(queue_path, lifespans_path, places_path):
    with Path(lifespans_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"camis", "latitude", "longitude", "first_cycle_inspection"} <= set(reader.fieldnames or []):
            raise ValueError("Lifespan table lacks geography or inspection baseline.")
        locations = {row["camis"]: row for row in reader}
    by_address, by_name_zip, place_count = load_places(places_path)
    with Path(queue_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if not {"business_id", "candidate_name", "candidate_address", "outcome_status"} <= set(fields):
            raise ValueError("Expected full lifespan review queue.")
        if set(EXTRA_FIELDS) & set(fields):
            raise ValueError("Queue already contains Foursquare lead fields.")
        cases = list(reader)
    seen, counts = set(), Counter()
    for case in cases:
        identifier = case["business_id"]
        if identifier in seen or identifier not in locations or case["outcome_status"] != "unresolved":
            raise ValueError("Queue must have unique, unresolved cases in the lifespan table.")
        seen.add(identifier)
        matches, method = match_case(case, locations[identifier], by_address, by_name_zip)
        if not matches:
            status = "no_conservative_match"
        elif len(matches) > 1:
            status = "ambiguous_multiple_matches"
        elif matches[0][0]["date_closed"]:
            baseline = locations[identifier]["first_cycle_inspection"]
            marked = matches[0][0]["date_closed"][:10]
            later_snapshot = locations[identifier]["last_snapshot"] > marked
            status = ("marked_closed_before_cycle_baseline_review"
                      if baseline and date.fromisoformat(marked) < date.fromisoformat(baseline)
                      else "marked_closed_but_later_dohmh_listing_review" if later_snapshot
                      else "marked_closed_by_2025_review")
        else:
            status = "not_marked_closed_by_2025_review"
        counts[status] += 1
        case.update(dict.fromkeys(EXTRA_FIELDS, ""))
        case["fsq_match_status"] = status
        case["fsq_match_method"] = method
        case["fsq_candidate_count"] = str(len(matches))
        case["fsq_place_ids"] = ";".join(item[0]["fsq_place_id"] for item in matches)
        case["fsq_names"] = ";".join(item[0]["name"] for item in matches)
        case["fsq_marked_closed_dates"] = ";".join(item[0]["date_closed"] for item in matches if item[0]["date_closed"])
        case["fsq_distance_meters"] = ";".join(str(round(item[1], 1)) for item in matches)
        case["fsq_place_urls"] = ";".join(
            "https://foursquare.com/placemakers/review-place/" + item[0]["fsq_place_id"]
            for item in matches)
        case["fsq_later_dohmh_snapshot"] = (
            "true" if len(matches) == 1 and matches[0][0]["date_closed"]
            and locations[identifier]["last_snapshot"] > matches[0][0]["date_closed"][:10]
            else "false")
    return cases, fields + list(EXTRA_FIELDS), {
        "queue_rows": len(cases), "foursquare_source_rows": place_count,
        "match_status_counts": dict(counts)}


def write_leads(queue_path, lifespans_path, places_path, output_path):
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("Foursquare lead output or manifest already exists.")
    rows, fields, summary = attach_leads(queue_path, lifespans_path, places_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), **summary,
                "source_sha256": {"queue": fingerprint(queue_path),
                                  "lifespans": fingerprint(lifespans_path),
                                  "foursquare": fingerprint(places_path)},
                "output_sha256": fingerprint(output_path), "training_eligible": False,
                "warning": "Foursquare date_closed is a database marking date, not the actual closure date. A null date_closed in the February 2025 archive is not proof of operation in 2026. Identity and closure status both require review."}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=ROOT / "data/evaluation/lifespans/review_queue_20261020_v4.csv")
    parser.add_argument("--lifespans", type=Path, default=ROOT / "data/evaluation/lifespans/restaurant_lifespans_20261020_v4.csv")
    parser.add_argument("--places", type=Path, default=ROOT / "data/raw_sources/foursquare_os/2025-02-06/nyc_dining.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/evaluation/lifespans/foursquare_review_leads_20261020_v2.csv")
    args = parser.parse_args()
    print(json.dumps(write_leads(args.queue, args.lifespans, args.places, args.output), indent=2))


if __name__ == "__main__":
    main()
