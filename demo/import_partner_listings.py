"""Validate and publish an authorized, complete partner listing snapshot."""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from shapely.geometry import Point, shape
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[1]
GEOGRAPHY = ROOT / "data/integrated/restaurant_bar_location_data_ready/geography/nyc_2020_census_tracts.geojson"
MASTER = ROOT / "data/integrated/restaurant_bar_location_data_ready/master_tract_features.csv"
DESTINATION = ROOT / "data/listings/authorized"
OUTPUT_FIELDS = (
    "listing_id", "geoid", "transaction", "address", "borough", "asking_rent_monthly",
    "asking_price", "source_url", "checked_at", "title", "sqft", "frontage",
    "condition", "availability", "image_url", "photo_display_permission", "latitude", "longitude",
    "broker_name", "broker_contact", "notes", "source_type",
)


def positive_number(value):
    try:
        number = float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def https_url(value):
    parsed = urlparse(value or "")
    return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not any(character.isspace() for character in value or ""))


def tract_lookup(geography_path):
    features = json.loads(Path(geography_path).read_text(encoding="utf-8"))["features"]
    geometries = [shape(feature["geometry"]) for feature in features]
    ids = [feature["properties"]["geoid"] for feature in features]
    tree = STRtree(geometries)

    def locate(latitude, longitude):
        point = Point(longitude, latitude)
        for index in tree.query(point, predicate="intersects"):
            if geometries[int(index)].covers(point):
                return ids[int(index)]
        return None

    return locate


def prepare_rows(input_path, geography_path=GEOGRAPHY, master_path=MASTER):
    with Path(master_path).open(newline="", encoding="utf-8-sig") as stream:
        valid_tracts = {row["geoid"] for row in csv.DictReader(stream)}
    locate = tract_lookup(geography_path)
    result = []
    seen = set()
    with Path(input_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"listing_id", "transaction", "address", "source_url", "checked_at"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Missing required columns: {', '.join(sorted(required - set(reader.fieldnames or [])))}")
        for number, raw in enumerate(reader, 2):
            row = {key: (raw.get(key) or "").strip() for key in OUTPUT_FIELDS}
            listing_id = row["listing_id"]
            if not listing_id or listing_id in seen or len(listing_id) > 100:
                raise ValueError(f"Row {number}: missing or duplicate listing_id")
            seen.add(listing_id)
            if row["transaction"] not in {"lease", "purchase"}:
                raise ValueError(f"Row {number}: transaction must be lease or purchase")
            price_field = "asking_rent_monthly" if row["transaction"] == "lease" else "asking_price"
            if positive_number(row[price_field]) is None:
                raise ValueError(f"Row {number}: positive {price_field} required")
            if not row["address"] or not https_url(row["source_url"]):
                raise ValueError(f"Row {number}: address and HTTPS source_url required")
            try:
                checked = date.fromisoformat(row["checked_at"])
            except ValueError as error:
                raise ValueError(f"Row {number}: checked_at must be YYYY-MM-DD") from error
            if not date.today() - timedelta(days=90) <= checked <= date.today():
                raise ValueError(f"Row {number}: checked_at is outside the 90-day display window")
            if bool(row["latitude"]) != bool(row["longitude"]):
                raise ValueError(f"Row {number}: both latitude and longitude are required together")
            if row["latitude"]:
                try:
                    latitude, longitude = float(row["latitude"]), float(row["longitude"])
                except ValueError as error:
                    raise ValueError(f"Row {number}: invalid coordinates") from error
                if not 40.45 <= latitude <= 40.95 or not -74.30 <= longitude <= -73.65:
                    raise ValueError(f"Row {number}: coordinates are outside NYC")
                mapped = locate(latitude, longitude)
                if not mapped or (row["geoid"] and row["geoid"] != mapped):
                    raise ValueError(f"Row {number}: coordinates do not match a NYC tract or supplied geoid")
                row["geoid"] = mapped
            if row["geoid"] not in valid_tracts:
                raise ValueError(f"Row {number}: geoid is not in the integrated tract table")
            if row["image_url"] and (not https_url(row["image_url"]) or row["photo_display_permission"].lower() != "yes"):
                raise ValueError(f"Row {number}: image_url requires HTTPS and photo_display_permission=yes")
            if row["sqft"] and positive_number(row["sqft"]) is None:
                raise ValueError(f"Row {number}: sqft must be positive when supplied")
            row["availability"] = row["availability"] or "Source-Reported; Confirm With Provider"
            row["source_type"] = "authorized_partner"
            result.append(row)
    if not result:
        raise ValueError("Snapshot is empty; refusing to remove current provider listings")
    return result


def publish(rows, input_path, provider, rights_reference, destination=DESTINATION):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", provider):
        raise ValueError("Provider must be a lowercase slug of 2-64 letters, digits, or hyphens")
    rights_file = Path(rights_reference).resolve()
    if not rights_file.is_file() or rights_file.stat().st_size == 0:
        raise ValueError("A nonempty local written permission reference is required")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{provider}.csv"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{provider}-", suffix=".csv", dir=destination)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    manifest = {"provider": provider, "source_file": str(Path(input_path).resolve()),
                "source_sha256": hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
                "rights_reference": str(rights_file), "published_at": datetime.now(timezone.utc).isoformat(),
                "listing_count": len(rows)}
    (destination / f"{provider}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Complete broker/owner CSV snapshot")
    parser.add_argument("--provider", required=True, help="Lowercase provider slug")
    parser.add_argument("--rights-reference", required=True, type=Path, help="Local written display permission file")
    parser.add_argument("--publish", action="store_true", help="Replace only this provider's prior snapshot")
    args = parser.parse_args()
    rows = prepare_rows(args.input)
    print(f"Validated {len(rows)} listings for {args.provider}.")
    if args.publish:
        print(f"Published {publish(rows, args.input, args.provider, args.rights_reference)}")
    else:
        print("Preview only. Pass --publish after reviewing the source and permission terms.")


if __name__ == "__main__":
    main()
