"""Validate complete scenario coverage artifacts without changing live scoring."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from customer_access import file_hash


def validate(run):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["status"] != "completed":
        raise ValueError("Incomplete access optimization")
    for name, expected in manifest["artifacts"].items():
        if file_hash(run / name) != expected:
            raise ValueError("Frozen scenario artifact changed: " + name)
    result = json.loads((run / "results.json").read_text())
    audit = pd.read_csv(run / "anchor_audit.csv", dtype={"geoid":str,"camis":str})
    repaired = audit[audit.status.eq("observed_restaurant_anchor")]
    if (len(repaired) != result["replaced_targets"] or len(audit) != result["failed_centroid_targets"]
            or not repaired.shift_meters.le(result["maximum_anchor_shift_meters"]).all()
            or not repaired.snap_meters.le(result["maximum_road_snap_meters"]).all()):
        raise ValueError("Anchor constraints not satisfied")
    if not result["population_origins_unchanged"] or not result["property_routes_unchanged"] or result["deployed"]:
        raise ValueError("Offline coverage scope changed")
    identifiers = None
    for name, profile in result["profiles"].items():
        frame = pd.read_csv(run / f"{name}.csv", dtype={"property_id":str,"geoid":str})
        if identifiers is None:
            identifiers = frame.property_id.tolist()
        if frame.property_id.duplicated().any() or identifiers != frame.property_id.tolist():
            raise ValueError("Candidate identity mismatch")
        columns = ["original_opportunities","repaired_opportunities","uncertain_competition_opportunities"]
        values = frame[columns].to_numpy(float)
        if np.isinf(values).any() or (values < 0).any():
            raise ValueError("Invalid opportunity scores")
        uncertain = frame.uncertain_competition_opportunities
        known = uncertain.notna() & frame.repaired_opportunities.notna()
        if (uncertain[known] > frame.repaired_opportunities[known] + 1e-8).any():
            raise ValueError("Adding competition increased captured opportunities")
        if frame.repaired_opportunities.notna().sum() != profile["anchor_comparison"]["rated"]:
            raise ValueError("Coverage report does not match scores")
        if profile["after"]["maximum_choice_mass_error"] > 1e-12:
            raise ValueError("Choice shares do not conserve mass")
    with np.load(run / "replacement_routes.npz", allow_pickle=False) as routes:
        if routes["property_ids"].tolist() != repaired.geoid.tolist():
            raise ValueError("Replacement route ordering differs")
        if (routes["distances"] < 0).any() or np.isnan(routes["distances"]).all(axis=1).any():
            raise ValueError("Replacement routes invalid")
    return {"status":"passed", "artifacts_checked":len(manifest["artifacts"]),
            "profiles_checked":len(result["profiles"]), "full_inventory_candidates":len(identifiers),
            "replaced_competitor_targets":len(repaired), "deployment_changed":False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.run),indent=2))
