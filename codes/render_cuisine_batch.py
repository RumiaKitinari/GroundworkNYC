"""Presentation-only maps of a verified batch; no scores or selections change."""
import argparse
import json
from pathlib import Path

import pandas as pd
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from batch_cuisine_scenarios import ROOT, PARENT, write_figure, write_viewer
from customer_access import file_hash
from evaluate_matched_results import verify_manifest


def run(batch, output):
    batch, output = Path(batch).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / "data/output"):
        raise ValueError("Use a new private output directory")
    manifest = verify_manifest(batch)
    geography = next(Path(p) for p in manifest["input_sha256"] if p.endswith("nyc_2020_census_tracts.geojson"))
    master_path = PARENT / "frozen_root/data/master_tract_features.csv"
    master = pd.read_csv(master_path, dtype={"geoid": str})
    eligible = set(master.loc[master.eligible_for_location_screening.astype(str).str.lower().isin(["true", "1"]), "geoid"])
    selected = pd.read_csv(batch / "top_selections.csv", dtype={"geoid": str})
    if set(selected.geoid) - eligible:
        raise ValueError("A selected location is outside screening geography")
    city = unary_union([shape(f["geometry"]) for f in json.loads(geography.read_text())["features"]
                        if f["properties"]["geoid"] in eligible]).simplify(.00008, preserve_topology=True)
    geo = mapping(city)
    polygons = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
    # Tiny tract seams are suppressed only for cartography, not analytical geometry.
    holes = [ring for polygon in polygons for ring in polygon[1:] if shape({"type": "Polygon", "coordinates": [ring]}).area > .000001]
    output.mkdir(parents=True)
    write_viewer(output, selected, [p[0] for p in polygons], holes)
    write_figure(output, selected, [p[0] for p in polygons], holes)
    metadata = {"basis": "Screening-eligible census tract extent; not a surveyed shoreline", "context_tracts": len(eligible),
        "scoring_changed": False, "selections_changed": False, "source_batch": str(batch)}
    (output / "context.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "manifest.json").write_text(json.dumps({"input_sha256": {str(batch / "manifest.json"): file_hash(batch / "manifest.json"),
        str(master_path): file_hash(master_path), str(geography): file_hash(geography), str(Path(__file__)): file_hash(Path(__file__))},
        "artifact_sha256": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.batch, args.output)
