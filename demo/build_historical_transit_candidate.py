"""Prepare pre-2024 subway features without asserting historical availability."""

import csv
import json
from pathlib import Path

from download_subway import inspect_week
from evaluation import fingerprint
from refresh_integrated import BASELINE, CURRENT, ROOT, miles
from build_historical_snapshots import write_immutable_csv


SOURCE_DIR = ROOT / "data" / "evaluation" / "source_archives" / "mta_subway_2023"
OUTPUT_DIR = ROOT / "data" / "evaluation" / "candidates" / "mta_week_2023-12-01"
FIELDS = ("geoid", "nearest_subway_distance_miles", "nearest_subway_weekly_ridership",
          "nearest_subway_station_complex_id")


def aggregate_stations(path):
    stations = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            station_id = row["station_complex_id"]
            lat, lon = float(row["latitude"]), float(row["longitude"])
            if not 40.45 <= lat <= 40.95 or not -74.30 <= lon <= -73.65:
                raise ValueError(f"Station outside NYC bounds: {station_id}")
            station = stations.setdefault(station_id, {"ridership": 0.0, "coordinates": {}})
            station["coordinates"][(lat, lon)] = station["coordinates"].get((lat, lon), 0) + 1
            station["ridership"] += float(row["ridership"])
    if len(stations) < 400:
        raise ValueError("Historical MTA station coverage is incomplete.")
    for station_id, station in stations.items():
        locations = station.pop("coordinates")
        position = max(locations, key=lambda point: (locations[point], point))
        if any(miles(*position, *point) > .25 for point in locations):
            raise ValueError(f"Conflicting station coordinates: {station_id}")
        station["latitude"], station["longitude"] = position
    return stations


def nearest_features(master_path, stations):
    features = []
    with master_path.open(newline="", encoding="utf-8-sig") as stream:
        for tract in csv.DictReader(stream):
            lat, lon = float(tract["centroid_latitude"]), float(tract["centroid_longitude"])
            station_id, station = min(stations.items(), key=lambda item:
                                      miles(lat, lon, item[1]["latitude"], item[1]["longitude"]))
            features.append({"geoid": tract["geoid"],
                             "nearest_subway_distance_miles": round(miles(lat, lon, station["latitude"], station["longitude"]), 6),
                             "nearest_subway_weekly_ridership": round(station["ridership"], 2),
                             "nearest_subway_station_complex_id": station_id})
    if len(features) < 2200 or len({row["geoid"] for row in features}) != len(features):
        raise ValueError("Incomplete or duplicate master tract coverage.")
    return sorted(features, key=lambda row: row["geoid"])


def main():
    source = SOURCE_DIR / "station_hour_2023-12-01.csv"
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text())
    summary = inspect_week(source, "2023-12-01")
    if summary not in manifest["weeks"] or manifest["source"] != "https://data.ny.gov/d/wujg-7c2s":
        raise ValueError("Historical MTA archive does not match its manifest.")
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    master = release / "master_tract_features.csv"
    rows = nearest_features(master, aggregate_stations(source))
    path = OUTPUT_DIR / "tract_subway_candidate.csv"
    digest = write_immutable_csv(path, rows, FIELDS)
    candidate = {"status": "candidate_not_as_of_verified", "training_eligible": False,
                 "source_url": manifest["source"], "source_path": str(source.relative_to(ROOT)),
                 "source_sha256": summary["sha256"], "week_start": summary["start"],
                 "week_end_exclusive": summary["end_exclusive"], "stations": summary["stations"],
                 "tracts": len(rows), "tract_features": str(path.relative_to(ROOT)),
                 "tract_features_sha256": digest, "master_geography_sha256": fingerprint(master),
                 "caution": "The current MTA historical table may have been corrected after 2024. Do not use this reconstructed feature in the 2024 backtest without a dated public snapshot or revision evidence."}
    manifest_path = OUTPUT_DIR / "candidate_manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != candidate:
            raise ValueError("Historical transit candidate differs; use a new directory.")
    else:
        manifest_path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(candidate, indent=2))


if __name__ == "__main__":
    main()
