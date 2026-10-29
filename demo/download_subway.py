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
WEEKS = ("2025-03-03", "2025-06-02", "2025-09-08", "2025-12-01")
FIELDS = ("transit_timestamp", "station_complex_id", "station_complex", "latitude", "longitude", "ridership", "transfers")


def download_week(start, out_dir):
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
    temporary = destination.with_suffix(".csv.part")
    request = Request(API + "?" + urlencode(query), headers={"User-Agent": "GroundworkNYC research/0.1"})
    try:
        with urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
        hours, stations, count = set(), set(), 0
        with temporary.open(newline="", encoding="utf-8-sig") as stream:
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
        temporary.replace(destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        return {"file": destination.name, "start": start, "end_exclusive": str(last), "rows": count,
                "hours": len(hours), "stations": len(stations), "sha256": digest}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", nargs="*", default=WEEKS)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for start in args.weeks:
        print(f"Downloading MTA station hours for {start}...", flush=True)
        result = download_week(start, OUT)
        print(result, flush=True)
        records.append(result)
    (OUT / "manifest.json").write_text(json.dumps({
        "source": "https://data.ny.gov/d/5wq4-mkjj", "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "grain": "subway station complex by hour; fare categories aggregated", "weeks": records,
        "caveat": "Station entries are not pedestrian counts or restaurant visits.",
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
