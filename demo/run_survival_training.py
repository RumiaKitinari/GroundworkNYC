"""Run the guarded, offline one-year restaurant survival benchmark."""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation import (HISTORICAL_CORE_FEATURES, FEATURES, fingerprint,
                        outcome_cohort, train_benchmark)
from prepare_historical_cohort import build_cohort, write_cohort
from refresh_integrated import ROOT


def run_training(evidence, snapshots, data_dir, output_dir, cutoff=None,
                 feature_set="historical_core", validation_mode="temporal_spatial", today=None):
    today = today or date.today()
    data_dir = Path(data_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_relative_to(data_dir):
        raise ValueError("Research cohorts and models must remain under the private data directory.")
    if output_dir.exists():
        raise FileExistsError(f"Research run already exists: {output_dir}")
    if feature_set not in {"historical_core", "full"}:
        raise ValueError("Unknown historical feature set.")
    if validation_mode not in {"temporal_spatial", "spatial_exploratory"}:
        raise ValueError("Unknown validation mode.")
    if validation_mode == "temporal_spatial" and not cutoff:
        raise ValueError("A predeclared YYYY-MM-DD cutoff is required for temporal validation.")
    if validation_mode == "spatial_exploratory" and cutoff:
        raise ValueError("Spatial exploratory validation cannot use a temporal cutoff.")
    cutoff_date = date.fromisoformat(cutoff) if cutoff else None
    if cutoff_date and cutoff_date > today:
        raise ValueError("The cutoff cannot be in the future.")
    features = HISTORICAL_CORE_FEATURES if feature_set == "historical_core" else FEATURES
    cohort, audit = build_cohort(evidence, snapshots, data_dir, today=today, features=features)
    if not cohort:
        return {"status": audit["status"], "training_performed": False, "audit": audit}

    with TemporaryDirectory() as folder:
        temporary = Path(folder) / "cohort.csv"
        write_cohort(temporary, cohort, features)
        rows, excluded, _ = outcome_cohort(temporary, cutoff or today.isoformat(), today=today,
                                           features=features)
    report, estimators = train_benchmark(rows, "continued_operation", excluded,
                                         cutoff_date if validation_mode == "temporal_spatial" else None,
                                         features=features, capture_estimators=True)
    report["feature_set"] = feature_set
    report["validation_mode"] = validation_mode
    report["source_fingerprints"] = {"evidence": fingerprint(evidence),
                                     "snapshots_manifest": fingerprint(snapshots)}
    report["class_counts"] = dict(Counter("verified_operating" if row["y"] else
                                          "verified_permanent_closure" for row in rows))
    report["deployment_status"] = "research_only"
    if validation_mode == "spatial_exploratory":
        report["limitations"].append("No future-year holdout; do not interpret as prospective accuracy.")

    output_dir.mkdir(parents=True, exist_ok=False)
    cohort_path = output_dir / "cohort.csv"
    write_cohort(cohort_path, cohort, features)
    audit["cohort_sha256"] = fingerprint(cohort_path)
    (output_dir / "cohort.audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    if report["status"] == "evaluated":
        import joblib
        report["model_artifacts"] = {}
        for name, estimator in estimators.items():
            model_path = output_dir / f"{name}.joblib"
            joblib.dump({"estimator": estimator, "features": list(features),
                         "input_transform": "log1p of nonnegative raw feature values; NaN for missing",
                         "target": "verified one-year continued operation",
                         "deployment_status": "research_only"}, model_path, compress=3)
            report["model_artifacts"][name] = {"path": model_path.name,
                                               "sha256": fingerprint(model_path)}
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                            encoding="utf-8")
    return {"status": report["status"], "training_performed": bool(estimators),
            "output_dir": str(output_dir), "audit": audit, "report": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True,
                        help="Independently reviewed evidence CSV; raw inspection exports are not labels")
    parser.add_argument("--snapshots", type=Path, default=ROOT / "data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, help="New private run directory; existing files are never replaced")
    parser.add_argument("--cutoff", help="Predeclared YYYY-MM-DD temporal test cutoff")
    parser.add_argument("--feature-set", choices=("historical_core", "full"), default="historical_core")
    parser.add_argument("--validation-mode", choices=("temporal_spatial", "spatial_exploratory"),
                        default="temporal_spatial")
    args = parser.parse_args()
    output_dir = args.output_dir or (args.data_dir / "evaluation/runs" /
                                      datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    try:
        result = run_training(args.evidence, args.snapshots, args.data_dir, output_dir, args.cutoff,
                              args.feature_set, args.validation_mode)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(2, f"Survival training failed: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
