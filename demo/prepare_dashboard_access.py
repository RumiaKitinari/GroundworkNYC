"""Prepare matching tract-point and property access bundles for the local dashboard."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codes"))

import pandas as pd
from engineer_customer_access import build


def prepare(property_run, output):
    property_run, output = Path(property_run).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Choose a new dashboard-access run directory")
    manifest = json.loads((property_run / "manifest.json").read_text())
    source = manifest["sources"]
    master = pd.read_csv(source["master"]["path"], dtype={"geoid": str})
    candidates = master[["geoid", "borough", "centroid_latitude", "centroid_longitude"]].rename(
        columns={"centroid_latitude": "latitude", "centroid_longitude": "longitude"})
    candidates["property_id"] = candidates.geoid
    candidates["inventory_type"] = "tract_screening_point"
    output.mkdir(parents=True, exist_ok=False)
    points = output / "tract_screening_points.csv"
    candidates.to_csv(points, index=False)
    result = build(source["master"]["path"], points, source["network"]["path"], output / "tracts",
                   config_path=source["config"]["path"])
    if not result["checks_passed"]:
        raise ValueError("Dashboard-access validation failed; active configuration unchanged")
    config = {"schema": "dashboard-customer-access-v1", "tract_run": str(output / "tracts"),
              "property_run": str(property_run), "prepared_at": datetime.now(timezone.utc).isoformat()}
    target = ROOT / "data/output/customer_access_dashboard/dashboard_access.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n")
    temporary.replace(target)
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--property-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.property_run, args.output), indent=2))
