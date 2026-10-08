"""Compare single H3 grids with official 2020 NYC census-block geometry."""

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from shutil import which

import h3
from shapely.geometry import shape
from shapely.ops import unary_union

from hex_demand import boundary, grid


COUNTIES = {
    "36005": "Bronx",
    "36047": "Brooklyn",
    "36061": "Manhattan",
    "36081": "Queens",
    "36085": "Staten Island",
}
MATERIAL_OVERLAP = 0.05
MIN_LAND_SHARE = 0.10


@lru_cache(maxsize=120000)
def cell_polygon(cell):
    return shape(boundary(cell))


def iter_census_blocks(directory):
    """Stream zipped TIGER/Line shapefiles without unpacking the source files."""
    if not which("ogr2ogr"):
        raise RuntimeError("Install GDAL's ogr2ogr to read the Census shapefiles.")
    for county in COUNTIES:
        path = Path(directory) / f"tl_2020_{county}_tabblock20.zip"
        if not path.exists():
            raise FileNotFoundError(f"Missing Census block file: {path}")
        command = ["ogr2ogr", "-f", "GeoJSONSeq", "/vsistdout/", f"/vsizip/{path}",
                   "-select", "GEOID20,ALAND20", "-t_srs", "EPSG:4326"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for line in process.stdout:
                yield json.loads(line)
        finally:
            process.stdout.close()
            error = process.stderr.read()
            if process.wait() != 0:
                raise RuntimeError(f"ogr2ogr failed for {path}: {error.strip()}")


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_blocks(features, resolutions=(8, 9, 10)):
    resolutions = tuple(sorted(set(resolutions)))
    if not resolutions or any(resolution not in {8, 9, 10} for resolution in resolutions):
        raise ValueError("This audit supports H3 resolutions 8, 9 and 10.")
    groups = defaultdict(lambda: {"blocks": 0, "land_m2": 0, "covered_land_m2": 0,
                                  "split_blocks": 0, "missed_blocks": 0, "cells": {}})
    for feature in features:
        properties = feature.get("properties") or {}
        geoid = str(properties.get("GEOID20", ""))
        if len(geoid) != 15 or geoid[:5] not in COUNTIES:
            continue
        land_m2 = int(properties.get("ALAND20") or 0)
        if land_m2 <= 0:
            continue
        block = shape(feature["geometry"])
        if not block.is_valid:
            block = block.buffer(0)
        if block.is_empty or block.area <= 0:
            continue
        county = geoid[:5]
        h3shape = h3.geo_to_h3shape(block.__geo_interface__)
        for resolution in resolutions:
            group = groups[(county, resolution)]
            group["blocks"] += 1
            group["land_m2"] += land_m2
            fractions = []
            # H3's overlap mode can omit narrow boundary fragments. The bounding-box
            # candidate set is broader; the polygon intersection below is exact.
            for cell in h3.h3shape_to_cells_experimental(h3shape, resolution, contain="bbox_overlap"):
                fraction = block.intersection(cell_polygon(cell)).area / block.area
                if fraction <= 1e-8:
                    continue
                fractions.append(fraction)
                record = group["cells"].setdefault(cell, {"blocks": 0, "material_blocks": 0,
                                                           "equivalent_blocks": 0, "land_m2": 0,
                                                           "tracts": set()})
                record["blocks"] += 1
                record["material_blocks"] += fraction >= MATERIAL_OVERLAP
                record["equivalent_blocks"] += fraction
                record["land_m2"] += land_m2 * fraction
                record["tracts"].add(geoid[:11])
            total = sum(fractions)
            group["covered_land_m2"] += land_m2 * min(1, total)
            group["split_blocks"] += sum(fraction >= MATERIAL_OVERLAP for fraction in fractions) >= 2
            group["missed_blocks"] += total < 0.995
    results = []
    for (county, resolution), group in sorted(groups.items()):
        cells = group["cells"]
        eligible = [record for cell, record in cells.items()
                    if record["land_m2"] / h3.cell_area(cell, unit="m^2") >= MIN_LAND_SHARE]
        results.append({
            "borough": COUNTIES[county], "county_fips": county, "resolution": resolution,
            "average_hex_area_m2": round(h3.average_hexagon_area(resolution, unit="m^2")),
            "census_blocks_with_land": group["blocks"], "cells_touching_land_blocks": len(cells),
            "cells_at_least_10pct_land": len(eligible),
            "block_land_coverage_pct": round(100 * group["covered_land_m2"] / group["land_m2"], 3),
            "blocks_with_incomplete_hex_coverage": group["missed_blocks"],
            "blocks_split_across_cells_pct": round(100 * group["split_blocks"] / group["blocks"], 1),
            "material_blocks_per_cell_p10_p50_p90": [round(percentile([row["material_blocks"] for row in eligible], q), 1)
                                                     for q in (.1, .5, .9)],
            "full_block_equivalents_per_cell_p10_p50_p90": [round(percentile([row["equivalent_blocks"] for row in eligible], q), 1)
                                                            for q in (.1, .5, .9)],
            "distinct_tracts_per_cell_p50_p90": [round(percentile([len(row["tracts"]) for row in eligible], q), 1)
                                                  for q in (.5, .9)],
        })
    return {"method": "Exact H3/block polygon overlap; 2020 Census tabulation blocks, not physical street blocks",
            "material_overlap_threshold_pct_of_block": MATERIAL_OVERLAP * 100,
            "cell_land_threshold_pct": MIN_LAND_SHARE * 100,
            "limitations": ["No block-level restaurant-demand observations are inferred from these boundaries.",
                            "ALAND20 is allocated uniformly over each block polygon for approximate cell land share.",
                            "Finer cells may repeat the same tract-level input score; geometry alone adds no signal."],
            "results": results}


def live_grid_coverage(directory, resolutions=(8, 9)):
    """Measure the area actually displayed by the existing eligible-tract grid."""
    directory = Path(directory)
    with (directory / "master_tract_features.csv").open(newline="", encoding="utf-8-sig") as stream:
        eligible = {row["geoid"] for row in csv.DictReader(stream)
                    if row.get("eligible_for_location_screening", "").lower() in {"true", "1"}
                    and row.get("borough") != "Staten Island"}
    features = json.loads((directory / "geography/nyc_2020_census_tracts.geojson").read_text())["features"]
    target = unary_union([shape(feature["geometry"]) for feature in features
                          if feature["properties"]["geoid"] in eligible])
    results = []
    for resolution in resolutions:
        cells = grid(str(directory), resolution, resolution - 1)
        footprint = unary_union([cell_polygon(cell) for cell, *_ in cells])
        results.append({"resolution": resolution, "cells": len(cells),
                        "eligible_tract_polygon_coverage_pct": round(100 * target.intersection(footprint).area / target.area, 3)})
    return {"eligible_tracts": len(eligible), "excludes": "Staten Island and tracts not eligible for location screening",
            "area_method": "WGS84 planar ratio over the same local geometry", "results": results}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data/raw_sources/census_blocks_2020")
    parser.add_argument("--resolutions", nargs="+", type=int, default=[8, 9, 10])
    parser.add_argument("--integrated-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "data/integrated/restaurant_bar_location_data_ready")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize_blocks(iter_census_blocks(args.blocks_dir), args.resolutions)
    report["h3_version"] = h3.__version__
    report["source_sha256"] = {f"tl_2020_{county}_tabblock20.zip": file_sha256(args.blocks_dir / f"tl_2020_{county}_tabblock20.zip")
                               for county in COUNTIES}
    if args.integrated_dir.exists() and any(resolution in {8, 9} for resolution in args.resolutions):
        report["live_grid_coverage"] = live_grid_coverage(args.integrated_dir,
                                                          [resolution for resolution in args.resolutions if resolution in {8, 9}])
    output = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
