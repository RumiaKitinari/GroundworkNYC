#!/usr/bin/env python3
"""Stream useful, tagged OpenStreetMap features from a PBF into CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import osmium


FIELDNAMES = [
    "osm_type",
    "osm_id",
    "osm_url",
    "name",
    "category",
    "feature_key",
    "feature_value",
    "latitude",
    "longitude",
    "min_latitude",
    "min_longitude",
    "max_latitude",
    "max_longitude",
    "geometry_type",
    "geometry_geojson",
    "node_count",
    "member_count",
    "street",
    "house_number",
    "city",
    "postcode",
    "operator",
    "access",
    "website",
    "phone",
    "opening_hours",
    "wheelchair",
    "tags_json",
]

# Ordered by how specifically each key describes the feature. This captures
# map-ready objects while excluding the millions of untagged support nodes.
FEATURE_KEYS = {
    "amenity": "community_and_amenities",
    "healthcare": "community_and_amenities",
    "emergency": "community_and_amenities",
    "shop": "community_and_amenities",
    "tourism": "community_and_amenities",
    "historic": "community_and_amenities",
    "office": "community_and_amenities",
    "craft": "community_and_amenities",
    "leisure": "parks_and_recreation",
    "landuse": "environment_and_land_use",
    "natural": "environment_and_land_use",
    "waterway": "environment_and_land_use",
    "power": "environment_and_land_use",
    "highway": "transportation",
    "railway": "transportation",
    "public_transport": "transportation",
    "route": "transportation",
    "aeroway": "transportation",
    "building": "built_environment",
    "building:part": "built_environment",
    "man_made": "built_environment",
    "barrier": "built_environment",
    "entrance": "built_environment",
    "place": "places_and_boundaries",
    "boundary": "places_and_boundaries",
}

POLYGON_KEYS = {
    "amenity",
    "healthcare",
    "shop",
    "tourism",
    "historic",
    "office",
    "craft",
    "leisure",
    "landuse",
    "natural",
    "building",
    "building:part",
    "man_made",
    "place",
    "boundary",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stream tagged, map-ready nodes/ways/relations from an OSM PBF "
            "to CSV without loading the whole extract into memory."
        )
    )
    parser.add_argument("input", type=Path, help="Input .osm.pbf file")
    parser.add_argument("output", type=Path, help="Destination CSV file")
    parser.add_argument(
        "--sample-output",
        type=Path,
        help="Optional second CSV containing the first sample rows",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=25,
        help="Rows written to --sample-output (default: 25)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output files",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1_000_000,
        help="Report progress after this many scanned OSM objects; 0 disables it",
    )
    return parser.parse_args()


def classify(tags: dict[str, str]) -> tuple[str, str, str] | None:
    """Return category, primary key, and value for a map-ready feature."""
    for key, category in FEATURE_KEYS.items():
        value = tags.get(key)
        if value:
            return category, key, value

    if tags.get("addr:housenumber"):
        return "built_environment", "address", "address_point"

    return None


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def coordinate_bounds(
    coordinates: Iterable[tuple[float, float]],
) -> tuple[list[list[float]], tuple[float, float, float, float] | None]:
    points: list[list[float]] = []
    min_lat = min_lon = float("inf")
    max_lat = max_lon = float("-inf")

    for lon, lat in coordinates:
        points.append([lon, lat])
        min_lat = min(min_lat, lat)
        min_lon = min(min_lon, lon)
        max_lat = max(max_lat, lat)
        max_lon = max(max_lon, lon)

    if not points:
        return points, None
    return points, (min_lat, min_lon, max_lat, max_lon)


def is_polygon(tags: dict[str, str], coordinates: list[list[float]]) -> bool:
    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
        return False
    if tags.get("area") == "no":
        return False
    if tags.get("area") == "yes":
        return True
    if tags.get("natural") in {"cliff", "coastline", "ridge", "tree_row"}:
        return False
    return any(key in tags for key in POLYGON_KEYS)


class FeatureCsvHandler(osmium.SimpleHandler):
    def __init__(
        self,
        writer: csv.DictWriter,
        sample_writer: csv.DictWriter | None,
        sample_rows: int,
        progress_every: int,
    ) -> None:
        super().__init__()
        self.writer = writer
        self.sample_writer = sample_writer
        self.sample_rows = sample_rows
        self.progress_every = progress_every
        self.scanned = 0
        self.written = 0
        self.by_type: Counter[str] = Counter()
        self.started_at = time.monotonic()

    def _scanned_one(self) -> None:
        self.scanned += 1
        if self.progress_every and self.scanned % self.progress_every == 0:
            elapsed = time.monotonic() - self.started_at
            rate = self.scanned / elapsed if elapsed else 0
            print(
                f"Scanned {self.scanned:,} objects; wrote {self.written:,} rows "
                f"({rate:,.0f} objects/second)",
                file=sys.stderr,
                flush=True,
            )

    def _base_row(
        self,
        osm_type: str,
        osm_id: int,
        tags: dict[str, str],
        classification: tuple[str, str, str],
    ) -> dict[str, Any]:
        category, feature_key, feature_value = classification
        return {
            "osm_type": osm_type,
            "osm_id": osm_id,
            "osm_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "name": tags.get("name") or tags.get("official_name", ""),
            "category": category,
            "feature_key": feature_key,
            "feature_value": feature_value,
            "latitude": "",
            "longitude": "",
            "min_latitude": "",
            "min_longitude": "",
            "max_latitude": "",
            "max_longitude": "",
            "geometry_type": "",
            "geometry_geojson": "",
            "node_count": "",
            "member_count": "",
            "street": tags.get("addr:street", ""),
            "house_number": tags.get("addr:housenumber", ""),
            "city": tags.get("addr:city", ""),
            "postcode": tags.get("addr:postcode", ""),
            "operator": tags.get("operator", ""),
            "access": tags.get("access", ""),
            "website": tags.get("website") or tags.get("contact:website", ""),
            "phone": tags.get("phone") or tags.get("contact:phone", ""),
            "opening_hours": tags.get("opening_hours", ""),
            "wheelchair": tags.get("wheelchair", ""),
            "tags_json": compact_json(tags),
        }

    def _write(self, row: dict[str, Any]) -> None:
        self.writer.writerow(row)
        if self.sample_writer is not None and self.written < self.sample_rows:
            self.sample_writer.writerow(row)
        self.written += 1
        self.by_type[row["osm_type"]] += 1

    def node(self, node: osmium.osm.Node) -> None:
        self._scanned_one()
        if len(node.tags) == 0:
            return
        tags = dict(node.tags)
        classification = classify(tags)
        if classification is None or not node.location.valid():
            return

        lon = node.location.lon
        lat = node.location.lat
        row = self._base_row("node", node.id, tags, classification)
        row.update(
            {
                "latitude": lat,
                "longitude": lon,
                "min_latitude": lat,
                "min_longitude": lon,
                "max_latitude": lat,
                "max_longitude": lon,
                "geometry_type": "Point",
                "geometry_geojson": compact_json(
                    {"type": "Point", "coordinates": [lon, lat]}
                ),
            }
        )
        self._write(row)

    def way(self, way: osmium.osm.Way) -> None:
        self._scanned_one()
        if len(way.tags) == 0:
            return
        tags = dict(way.tags)
        classification = classify(tags)
        if classification is None:
            return

        node_count = len(way.nodes)
        coordinates, bounds = coordinate_bounds(
            (node.lon, node.lat) for node in way.nodes if node.location.valid()
        )
        row = self._base_row("way", way.id, tags, classification)
        row["node_count"] = node_count

        # Only publish geometry when every referenced node has a valid location.
        if bounds is not None and len(coordinates) == node_count:
            min_lat, min_lon, max_lat, max_lon = bounds
            polygon = is_polygon(tags, coordinates)
            geometry_type = "Polygon" if polygon else "LineString"
            geometry_coordinates: Any = [coordinates] if polygon else coordinates
            row.update(
                {
                    "latitude": (min_lat + max_lat) / 2,
                    "longitude": (min_lon + max_lon) / 2,
                    "min_latitude": min_lat,
                    "min_longitude": min_lon,
                    "max_latitude": max_lat,
                    "max_longitude": max_lon,
                    "geometry_type": geometry_type,
                    "geometry_geojson": compact_json(
                        {"type": geometry_type, "coordinates": geometry_coordinates}
                    ),
                }
            )
        self._write(row)

    def relation(self, relation: osmium.osm.Relation) -> None:
        self._scanned_one()
        if len(relation.tags) == 0:
            return
        tags = dict(relation.tags)
        classification = classify(tags)
        if classification is None:
            return

        row = self._base_row("relation", relation.id, tags, classification)
        row["geometry_type"] = "Relation"
        row["member_count"] = len(relation.members)
        self._write(row)


def ensure_destination(path: Path, overwrite: bool) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists (use --overwrite): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def temporary_csv(path: Path) -> tuple[Any, Path]:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    return handle, Path(handle.name)


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2
    if args.sample_rows < 0:
        print("--sample-rows must be zero or greater", file=sys.stderr)
        return 2
    if args.progress_every < 0:
        print("--progress-every must be zero or greater", file=sys.stderr)
        return 2

    try:
        output_path = ensure_destination(args.output, args.overwrite)
        sample_path = (
            ensure_destination(args.sample_output, args.overwrite)
            if args.sample_output
            else None
        )
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 2

    if input_path == output_path or (sample_path and input_path == sample_path):
        print("Input and output paths must be different", file=sys.stderr)
        return 2
    if sample_path and sample_path == output_path:
        print("Full and sample output paths must be different", file=sys.stderr)
        return 2

    output_handle = sample_handle = None
    output_temp = sample_temp = None
    started_at = time.monotonic()
    try:
        output_handle, output_temp = temporary_csv(output_path)
        writer = csv.DictWriter(output_handle, fieldnames=FIELDNAMES)
        writer.writeheader()

        sample_writer = None
        if sample_path:
            sample_handle, sample_temp = temporary_csv(sample_path)
            sample_writer = csv.DictWriter(sample_handle, fieldnames=FIELDNAMES)
            sample_writer.writeheader()

        handler = FeatureCsvHandler(
            writer=writer,
            sample_writer=sample_writer,
            sample_rows=args.sample_rows,
            progress_every=args.progress_every,
        )

        # A file-backed sparse index keeps the full node coordinate table off
        # the Python heap and is removed automatically after the conversion.
        with tempfile.TemporaryDirectory(
            prefix="osmium-node-index-", dir=output_path.parent
        ) as index_directory:
            index_path = Path(index_directory) / "locations.idx"
            handler.apply_file(
                str(input_path),
                locations=True,
                idx=f"sparse_file_array,{index_path}",
            )

        output_handle.flush()
        os.fsync(output_handle.fileno())
        output_handle.close()
        output_handle = None
        os.replace(output_temp, output_path)
        output_temp = None

        if sample_handle and sample_temp and sample_path:
            sample_handle.flush()
            os.fsync(sample_handle.fileno())
            sample_handle.close()
            sample_handle = None
            os.replace(sample_temp, sample_path)
            sample_temp = None

        elapsed = time.monotonic() - started_at
        counts = ", ".join(
            f"{osm_type}={count:,}" for osm_type, count in sorted(handler.by_type.items())
        )
        print(f"Wrote {handler.written:,} rows to {output_path}")
        print(f"Rows by type: {counts or 'none'}")
        print(f"Scanned {handler.scanned:,} OSM objects in {elapsed:,.1f} seconds")
        if sample_path:
            print(f"Wrote up to {args.sample_rows:,} sample rows to {sample_path}")
        return 0
    except Exception as exc:
        print(f"Conversion failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if output_handle is not None:
            output_handle.close()
        if sample_handle is not None:
            sample_handle.close()
        if output_temp is not None:
            output_temp.unlink(missing_ok=True)
        if sample_temp is not None:
            sample_temp.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
