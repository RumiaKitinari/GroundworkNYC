"""Build interval-censored restaurant lifespan candidates from archived DOHMH snapshots."""

import argparse
import bisect
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from evaluation import fingerprint
from refresh_integrated import ROOT


SOURCE_COMMIT = "20db98e6d2a1b2699b7a42c2e90df2edaed154e5"
SOURCE_URL = f"https://github.com/CharlesFainLehman/nyc-cuisine-atlas/tree/{SOURCE_COMMIT}"
DOHMH_URL = "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j"
FIELDS = ("camis", "dba", "address", "borough", "latitude", "longitude", "geoid", "nta_code",
          "cuisine", "first_snapshot", "last_snapshot", "next_snapshot", "first_insp", "first_prepermit",
          "first_operational_prepermit", "first_cycle_inspection", "last_operational_inspection",
          "followup_inspection_365_455",
          "open_date", "open_date_basis", "survival_lower_years", "survival_upper_years",
          "clean_cohort", "observation_status", "outcome_status", "source_url")


def _day(value):
    return value.date() if isinstance(value, datetime) else value


def _years(start, end):
    return round((end - start).days / 365.25, 4) if start and end and end >= start else ""


def load_archive(restaurants_path, inspections_path):
    import duckdb
    connection = duckdb.connect()
    try:
        restaurants = connection.execute("SELECT * FROM read_parquet(?)", [str(restaurants_path)]).fetchall()
        names = [column[0] for column in connection.description]
        needed = {"camis", "dba", "boro", "lat", "lon", "first_snapshot", "last_snapshot",
                  "first_insp", "first_prepermit"}
        if not needed <= set(names):
            raise ValueError("Restaurant archive is missing: " + ", ".join(sorted(needed - set(names))))
        restaurants = [dict(zip(names, row)) for row in restaurants]
        inspections = connection.execute("SELECT camis, date, type FROM read_parquet(?)",
                                         [str(inspections_path)]).fetchall()
    finally:
        connection.close()
    return restaurants, inspections


def tract_lookup(geojson_path):
    from shapely import STRtree
    from shapely.geometry import Point, shape
    features = json.loads(Path(geojson_path).read_text(encoding="utf-8"))["features"]
    geometries = [shape(feature["geometry"]) for feature in features]
    tree = STRtree(geometries)
    properties = [feature["properties"] for feature in features]

    def locate(lat, lon):
        if lat is None or lon is None or not math.isfinite(lat) or not math.isfinite(lon):
            return "", ""
        matches = tree.query(Point(lon, lat), predicate="within")
        if len(matches) != 1:
            return "", ""
        match = properties[int(matches[0])]
        return match["geoid"], match.get("nta2020", "")

    return locate


def build_candidates(restaurants, inspections, locate):
    if len({row["camis"] for row in restaurants}) != len(restaurants):
        raise ValueError("The restaurant archive contains duplicate CAMIS IDs.")
    snapshot_dates = sorted({_day(row[key]) for row in restaurants
                             for key in ("first_snapshot", "last_snapshot") if row[key]})
    if len(snapshot_dates) < 2:
        raise ValueError("At least two dated snapshots are required for lifespan intervals.")
    events = defaultdict(set)
    for camis, inspected, kind in inspections:
        if inspected and kind and (kind.startswith("Pre-permit (Operational)")
                                   or kind.startswith("Cycle Inspection")):
            events[camis].add((_day(inspected), kind))
    rows, qa = [], Counter()
    for item in restaurants:
        camis = item["camis"]
        first, last = _day(item["first_snapshot"]), _day(item["last_snapshot"])
        if not first or not last or first > last or first not in snapshot_dates or last not in snapshot_dates:
            raise ValueError(f"Invalid snapshot dates for CAMIS {camis}.")
        index = bisect.bisect_right(snapshot_dates, last)
        next_snapshot = snapshot_dates[index] if index < len(snapshot_dates) else None
        relevant = sorted(events[camis])
        preoperational = [day for day, kind in relevant if kind.startswith("Pre-permit (Operational)")]
        first_preop = min(preoperational, default=None)
        first_cycle = min((day for day, kind in relevant if kind.startswith("Cycle Inspection")
                           and (not first_preop or day > first_preop)), default=None)
        last_operational = max((day for day, _ in relevant), default=None)
        first_inspection = _day(item["first_insp"])
        geoid, nta = locate(item["lat"], item["lon"])
        clean = bool(first_preop and first_preop >= date(2020, 11, 6)
                     and first > date(2020, 11, 6) and first_preop <= first
                     and (first - first_preop).days <= 365
                     and first_inspection and first_inspection >= first_preop and geoid)
        if first_preop and first_preop > first:
            qa["operational_prepermit_after_first_snapshot"] += 1
        if first_preop and first >= first_preop and (first - first_preop).days > 365:
            qa["operational_prepermit_to_first_snapshot_over_365_days"] += 1
        if first_preop and first_inspection and first_inspection < first_preop:
            qa["earlier_inspection_than_operational_prepermit"] += 1
        if not geoid:
            qa["missing_tract"] += 1
        if clean:
            qa["clean_temporal_candidates"] += 1
            if first_cycle:
                qa["clean_candidates_with_cycle_inspection_lead"] += 1
        baseline = first_preop if clean else None
        followup = min((day for day, _ in relevant
                        if baseline and baseline + timedelta(days=365) <= day
                        <= baseline + timedelta(days=455)), default=None)
        if followup:
            qa["candidates_with_followup_inspection_lead"] += 1
        status = "right_censored_active_listing" if next_snapshot is None else "disappeared_between_snapshots"
        qa[status] += 1
        rows.append({
            "camis": camis, "dba": item["dba"] or "",
            "address": " ".join(part for part in (item.get("building"), item.get("street"), item.get("zipcode")) if part),
            "borough": item["boro"] or "",
            "cuisine": item.get("cuisine") or "",
            "latitude": item["lat"] if item["lat"] is not None else "",
            "longitude": item["lon"] if item["lon"] is not None else "",
            "geoid": geoid, "nta_code": nta, "first_snapshot": first.isoformat(),
            "last_snapshot": last.isoformat(), "next_snapshot": next_snapshot.isoformat() if next_snapshot else "",
            "first_insp": first_inspection.isoformat() if first_inspection else "",
            "first_prepermit": _day(item["first_prepermit"]).isoformat() if item["first_prepermit"] else "",
            "first_operational_prepermit": first_preop.isoformat() if first_preop else "",
            "first_cycle_inspection": first_cycle.isoformat() if first_cycle else "",
            "last_operational_inspection": last_operational.isoformat() if last_operational else "",
            "followup_inspection_365_455": followup.isoformat() if followup else "",
            "open_date": baseline.isoformat() if baseline else "",
            "open_date_basis": "first_prepermit_operational_inspection_not_confirmed_opening" if baseline else "",
            "survival_lower_years": _years(baseline, last),
            "survival_upper_years": ("inf" if next_snapshot is None else _years(baseline, next_snapshot)) if baseline else "",
            "clean_cohort": "true" if clean else "false", "observation_status": status,
            "outcome_status": "unresolved", "source_url": DOHMH_URL,
        })
    qa["total_restaurants"] = len(rows)
    qa["snapshot_count"] = len(snapshot_dates)
    return rows, dict(qa), [day.isoformat() for day in snapshot_dates]


def build_file(restaurants_path, inspections_path, geojson_path, output_path):
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("Lifespan output or manifest already exists; choose a new path.")
    restaurants, inspections = load_archive(restaurants_path, inspections_path)
    rows, qa, snapshots = build_candidates(restaurants, inspections, tract_lookup(geojson_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(), "source_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT, "dohmh_url": DOHMH_URL,
        "source_sha256": {"restaurants": fingerprint(restaurants_path),
                          "inspections": fingerprint(inspections_path), "tracts": fingerprint(geojson_path)},
        "output_sha256": fingerprint(output_path), "output": str(output_path),
        "qa": qa, "snapshot_dates": snapshots, "training_eligible": False,
        "warning": "A pre-operational inspection precedes operation and is not an opening date. Snapshot disappearance is not verified permanent closure. No success/failure labels have been assigned.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = ROOT / "data/raw_sources/nyc_cuisine_atlas" / SOURCE_COMMIT
    parser.add_argument("--restaurants", type=Path, default=source / "restaurants_raw.parquet")
    parser.add_argument("--inspections", type=Path, default=source / "inspections.parquet")
    parser.add_argument("--tracts", type=Path, default=ROOT / "data/integrated/current/geography/nyc_2020_census_tracts.geojson")
    parser.add_argument("--output", type=Path, default=ROOT / "data/evaluation/lifespans" /
                        f"restaurant_lifespans_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.csv")
    args = parser.parse_args()
    try:
        result = build_file(args.restaurants, args.inspections, args.tracts, args.output)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(2, f"Lifespan build failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
