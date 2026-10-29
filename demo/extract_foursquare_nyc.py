"""Extract NYC-area dining POIs from a dated public Foursquare OS mirror."""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation import fingerprint
from refresh_integrated import ROOT


RELEASE = "2025-02-06"
MIRROR = "https://data.source.coop/fused/fsq-os-places"
SOURCE = "https://source.coop/fused/fsq-os-places"
SCHEMA = "https://docs.foursquare.com/data-products/docs/places-os-data-schema"
# Geographic Parquet row-group bounds put the NYC bounding box in these two
# partitions of this pinned release; the query still applies a row-level bbox.
PARTITIONS = ("16.parquet", "17.parquet")
BBOX = (-74.26, 40.49, -73.68, 40.92)
OUTPUT_FIELDS = ("fsq_place_id", "name", "latitude", "longitude", "address",
                 "locality", "region", "postcode", "date_created", "date_refreshed",
                 "date_closed", "fsq_category_labels")


def extract(output):
    output = Path(output)
    manifest_path = output.with_suffix(".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("Foursquare extract or manifest already exists.")
    import duckdb

    urls = [f"{MIRROR}/{RELEASE}/places/{part}" for part in PARTITIONS]
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET enable_progress_bar=false")
    try:
        destination = str(output.resolve()).replace("'", "''")
        connection.execute(f"""
            COPY (
                SELECT fsq_place_id, name, latitude, longitude, address,
                       locality, region, postcode, date_created, date_refreshed,
                       date_closed, array_to_string(fsq_category_labels, ';') AS fsq_category_labels
                FROM read_parquet(?)
                WHERE longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?
                  AND region = 'NY'
                  AND list_filter(fsq_category_labels,
                                  label -> starts_with(label, 'Dining and Drinking')) <> []
            ) TO '{destination}' (HEADER, DELIMITER ',')
        """, [urls, BBOX[0], BBOX[2], BBOX[1], BBOX[3]])
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    with output.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != OUTPUT_FIELDS:
            raise ValueError("Unexpected Foursquare export schema.")
        ids, rows, closed = set(), 0, 0
        for row in reader:
            if not row["fsq_place_id"] or row["fsq_place_id"] in ids:
                raise ValueError("Missing or duplicate Foursquare place ID.")
            ids.add(row["fsq_place_id"])
            rows += 1
            closed += bool(row["date_closed"])
    if rows < 50_000:
        raise ValueError("NYC-area Foursquare extract unexpectedly small.")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(),
                "source_release": RELEASE, "source_page": SOURCE,
                "schema_page": SCHEMA, "source_partitions": urls,
                "license": "Apache-2.0, Foursquare Labs, Inc.",
                "bbox": BBOX, "filter": "region NY; Dining and Drinking category",
                "rows": rows, "dated_closure_leads": closed,
                "output_sha256": fingerprint(output), "training_eligible": False,
                "warning": "date_closed is when Foursquare marked the POI closed, not its actual closure date. This February 2025 release cannot establish later status."}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw_sources/foursquare_os/2025-02-06/nyc_dining.csv")
    args = parser.parse_args()
    print(json.dumps(extract(args.output), indent=2))


if __name__ == "__main__":
    main()
