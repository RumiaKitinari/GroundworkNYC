"""Replay immutable research predictions without retuning or promoting models."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from customer_access import file_hash
from optimize_archive_model import feature_policies
from survival_metrics import evaluate_predictions
from train_archive_aft import research_matrix


def validate(run):
    run = Path(run).resolve()
    manifest = json.loads((run / "manifest.json").read_text())
    for name, expected in manifest["artifact_sha256"].items():
        if file_hash(run / name) != expected:
            raise ValueError("Frozen artifact changed: " + name)
    parent = Path(manifest["parent_run"])
    if file_hash(parent / "run_manifest.json") != manifest["parent_manifest_sha256"]:
        raise ValueError("Frozen parent changed")
    parent_manifest = json.loads((parent / "run_manifest.json").read_text())
    for name, expected in parent_manifest["artifact_sha256"].items():
        if file_hash(parent / name) != expected:
            raise ValueError("Parent artifact changed: " + name)
    rows = pd.read_csv(parent / "corrected_research/training_rows.csv", dtype={"camis":str,"geoid":str}, float_precision="round_trip", low_memory=False)
    split = pd.read_csv(run / "split_assignments.csv", dtype={"camis":str})
    assessment = pd.read_csv(run / "reserved_predictions.csv", dtype={"camis":str,"geoid":str}, float_precision="round_trip")
    reserved = rows.set_index("camis").loc[assessment.camis].reset_index()
    roles = split.groupby("nta_code").optimization_role.nunique()
    if not roles.eq(1).all() or len(split) != len(rows):
        raise ValueError("Neighborhood overlap or missing cohort rows")
    if set(assessment.camis) != set(split.loc[split.optimization_role.eq("reserved_assessment"), "camis"]):
        raise ValueError("Assessment identities differ from reservation")
    lock = json.loads((run / "selection_lock.json").read_text())
    results = json.loads((run / "reserved_assessment.json").read_text())
    if file_hash(run / "selection_lock.json") != results["selection_lock_sha256"]:
        raise ValueError("Selection lock changed")
    policies = feature_policies(rows)
    for model_name, columns, saved in (("selected", lock["features"], "selected_median_years"),
        ("untuned",policies["context_only"],"default_median_years"),
        ("full_diagnostic",policies["corrected_full"],"full_diagnostic_median_years")):
        model = xgb.Booster()
        model.load_model(run / f"{model_name}_model.json")
        predictions = model.predict(research_matrix(reserved, columns))
        np.testing.assert_allclose(predictions, assessment[saved], rtol=1e-6, atol=1e-6)
    boroughs = {str(b):evaluate_predictions(frame.selected_median_years, frame.y_lower, frame.y_upper)
                for b, frame in assessment.groupby("borough")}
    report = {"status":"passed", "run":str(run), "models_replayed":3,
              "optimization_artifacts_checked":len(manifest["artifact_sha256"]),
              "parent_artifacts_checked":len(parent_manifest["artifact_sha256"]),
              "neighborhood_overlap":False, "reserved_rows":len(reserved),
              "globally_untouched_test":False, "deployment_allowed":False, "borough_diagnostics":boroughs}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",required=True)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    report = validate(args.run)
    output = Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise ValueError("Do not overwrite earlier validation")
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k!="borough_diagnostics"},indent=2))
