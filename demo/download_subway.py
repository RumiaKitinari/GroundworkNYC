"""Download complete station-hour MTA subway observations for reproducible analysis."""

import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "subway"
API = "https://data.ny.gov/resource/5wq4-mkjj.csv"
HISTORICAL_API = "https://data.ny.gov/resource/wujg-7c2s.csv"
WEEKS = ("2025-03-03", "2025-06-02", "2025-09-08", "2025-12-01")
FIELDS = ("transit_timestamp", "station_complex_id", "station_complex", "latitude", "longitude", "ridership", "transfers")


def inspect_week(path, start):
    first = date.fromisoformat(start)
    last = first + timedelta(days=7)
    hours, stations, count = set(), set(), 0
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected MTA response: {reader.fieldnames}")
        for row in reader:
            moment = datetime.fromisoformat(row["transit_timestamp"])
            if (not first <= moment.date() < last or float(row["ridership"]) < 0
                    or not math.isfinite(float(row["transfers"]))):
                raise ValueError("Out-of-range date or invalid activity")
            hours.add(moment.strftime("%Y-%m-%dT%H"))
            stations.add(row["station_complex_id"])
            count += 1
    if len(hours) != 168 or len(stations) < 400 or count < 60000:
        raise ValueError(f"Incomplete week: {count} rows, {len(hours)} hours, {len(stations)} stations")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"file": path.name, "start": start, "end_exclusive": str(last), "rows": count,
            "hours": len(hours), "stations": len(stations), "sha256": digest}


def download_week(start, out_dir, api=API, preserve_existing=False):
    first = date.fromisoformat(start)
    last = first + timedelta(days=7)
    query = {
        "$select": "transit_timestamp,station_complex_id,max(station_complex) as station_complex,"
        "max(latitude) as latitude,max(longitude) as longitude,sum(ridership) as ridership,"
        "sum(transfers) as transfers",
        "$where": f"transit_mode = 'subway' AND transit_timestamp >= '{first}T00:00:00' "
        f"AND transit_timestamp < '{last}T00:00:00'",
        "$group": "transit_timestamp,station_complex_id",
        "$order": "transit_timestamp,station_complex_id",
        "$limit": 100000,
    }
    destination = out_dir / f"station_hour_{start}.csv"
    if preserve_existing and destination.exists():
        return inspect_week(destination, start)
    temporary = destination.with_suffix(".csv.part")
    request = Request(api + "?" + urlencode(query), headers={"User-Agent": "GroundworkNYC research/0.1"})
    try:
        with urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        result = inspect_week(temporary, start)
        if preserve_existing and destination.exists():
            raise FileExistsError(f"Historical source appeared during download: {destination}")
        temporary.replace(destination)
        return {**result, "file": destination.name}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", nargs="*")
    parser.add_argument("--historical", action="store_true", help="Archive a pre-2025 week separately for historical evaluation")
    args = parser.parse_args()
    out = ROOT / "data" / "evaluation" / "source_archives" / "mta_subway_2023" if args.historical else OUT
    api = HISTORICAL_API if args.historical else API
    weeks = args.weeks if args.weeks is not None else (["2023-12-01"] if args.historical else WEEKS)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for start in weeks:
        print(f"Downloading MTA station hours for {start}...", flush=True)
        result = download_week(start, out, api=api, preserve_existing=args.historical)
        print(result, flush=True)
        records.append(result)
    manifest = {
        "source": "https://data.ny.gov/d/wujg-7c2s" if args.historical else "https://data.ny.gov/d/5wq4-mkjj",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "grain": "subway station complex by hour; fare categories aggregated", "weeks": records,
        "caveat": "Station entries are not pedestrian counts or restaurant visits.",
    }
    if args.historical:
        manifest["evaluation_status"] = "source_archive_only; not an as-of-verified training feature"
        manifest["timing_note"] = "The live historical table may contain later corrections. Verify a dated public release before using it as a 2024 baseline feature."
    manifest_path = out / "manifest.json"
    if args.historical and manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if {key: value for key, value in previous.items() if key != "retrieved_at"} != {key: value for key, value in manifest.items() if key != "retrieved_at"}:
            raise ValueError("Historical manifest differs; do not overwrite a pinned source archive.")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
