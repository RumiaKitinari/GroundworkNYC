"""Validate frozen research outputs against native saved fold models, not refits."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from customer_access import file_hash
from survival_metrics import paired_concordance_delta


def validate(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Choose a new validation directory")
    manifest = json.loads((run / "run_manifest.json").read_text())
    if manifest.get("status") != "completed_offline_proxy_research" or manifest.get("deployment_allowed") is not False:
        raise ValueError("A completed nonproduction proxy run is required")
    for name, digest in manifest["artifact_sha256"].items():
        path = (run / name).resolve()
        if not path.is_relative_to(run) or file_hash(path) != digest:
            raise ValueError("Frozen artifact changed: " + name)
    folder = run / "corrected_research"
    rows = pd.read_csv(folder / "training_rows.csv", dtype={"camis": str, "geoid": str},
                       low_memory=False, float_precision="round_trip").set_index("camis")
    predictions = pd.read_csv(folder / "heldout_predictions.csv", dtype={"camis": str, "geoid": str},
                              float_precision="round_trip")
    assignments = pd.read_csv(folder / "fold_assignments.csv", dtype={"camis": str})
    if (rows.index.duplicated().any() or assignments.camis.duplicated().any()
            or set(assignments.camis) != set(rows.index)
            or not assignments.groupby("nta_code").fold.nunique().eq(1).all()):
        raise ValueError("Invalid restaurant or neighborhood holdout assignments")
    if not predictions.proxy_aft_3yr.between(0, 1).all():
        raise ValueError("Invalid proxy CDF probabilities")
    checks = []
    for (name, fold), heldout in predictions.groupby(["model", "fold"]):
        expected = set(assignments.loc[assignments.fold.eq(fold), "camis"])
        if heldout.camis.duplicated().any() or set(heldout.camis) != expected:
            raise ValueError("Held-out prediction identities differ from frozen folds")
        model = xgb.Booster()
        model.load_model(folder / f"{name}_fold_{fold}.json")
        test = rows.reindex(heldout.camis)
        columns = model.feature_names
        values = test[columns].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        replay = model.predict(xgb.DMatrix(values.to_numpy(float), feature_names=columns))
        np.testing.assert_allclose(replay, heldout.median_years.to_numpy(float), rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(test.y_lower, heldout.y_lower)
        np.testing.assert_allclose(test.y_upper, heldout.y_upper)
        if not np.array_equal(test.geoid.to_numpy(), heldout.geoid.to_numpy()):
            raise ValueError("Prediction tract identifiers changed")
        checks.append({"model": name, "fold": int(fold), "rows": len(heldout),
                       "native_prediction_replay": True})
    for name, group in predictions.groupby("model"):
        if group.camis.duplicated().any() or set(group.camis) != set(rows.index):
            raise ValueError("Each model must predict every cohort restaurant exactly once")
    # Keep the frozen OOF row order so sampled comparable pairs exactly match
    # the original evaluation, while explicitly aligning the second model.
    left = predictions[predictions.model.eq("legacy_50")].set_index("camis")
    right = predictions[predictions.model.eq("corrected_context_plus_restaurant")].set_index("camis").reindex(left.index)
    if not left.index.equals(right.index):
        raise ValueError("Model comparison is not paired")
    comparison = paired_concordance_delta(left.median_years, right.median_years,
        left.y_lower, left.y_upper, left.nta_code)
    report = json.loads((folder / "evaluation.json").read_text())
    result = {"schema": "archive-run-validation-v1", "status": "passed",
        "training_run": str(run), "run_manifest_sha256": file_hash(run / "run_manifest.json"),
        "source_artifacts_checked": len(manifest["artifact_sha256"]), "cohort_rows": len(rows),
        "heldout_rows": len(predictions), "native_fold_replays": checks,
        "paired_corrected_vs_legacy": comparison, "verified_survival_accuracy": False,
        "validated_claim": "Frozen artifacts, complete group holdouts, native-model prediction fidelity and archive-proxy metrics",
        "not_validated": ["Permanent closure labels", "Historical feature availability", "Individual restaurant profitability",
                          "Calibrated real-world survival or visits", "Synthetic listing availability"],
        "validation_code_sha256": {name: file_hash(Path(__file__).with_name(name)) for name in
                                  ("validate_archive_run.py", "survival_metrics.py")}}
    output.mkdir(parents=True, exist_ok=False)
    (output / "validation.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    summary = report["summary"]
    text = ["# Frozen Archive-AFT Research Results", "",
        "These are retrospective archive-disappearance proxy results, not verified restaurant-survival accuracy.", "",
        f"Cohort: {len(rows):,} restaurants; {report['nta_groups']} NTA groups; five held-out neighborhood folds.",
        f"Assumed event intervals: {report['assumed_event_intervals']:,}; right-censored: {report['right_censored_rows']:,}.", "",
        "| Fixed-Round Model | Interval Concordance | Interval NLL |", "| --- | ---: | ---: |"]
    for name in ("constant_aft", "legacy_50", "corrected_context_plus_restaurant"):
        record = summary[name]
        text.append(f"| {name} | {record['concordance']['estimate']:.4f} | {record['interval_negative_log_likelihood']:.4f} |")
    text += ["", f"Paired corrected-minus-legacy concordance: {comparison['candidate_minus_reference']:.4f}.",
        f"Conditional NTA-bootstrap 95% interval: {comparison['paired_nta_bootstrap_95_ci']}.", "",
        "The original early-stopped reference run reports approximately 0.566, but its test folds also select stopping rounds. It is not directly comparable to the fixed-round table above.",
        "The pooled constant-AFT comparator varies by training fold, so pooled concordance need not equal 0.5; each fold's constant predictor has tied scores.",
        "The corrected model is not automatically selected as better. Small differences and uncertainty must be reported.", "",
        f"Replayed all {len(checks)} native held-out model/fold combinations and verified every saved artifact hash.",
        "The original code's pre-permit opening proxy, inferred archive exits, retrospective neighborhood data and full-archive chain reconstruction remain limitations.",
        "Use held-out predictions for model diagnostics, not fitted full-cohort or property predictions. Do not tune on these results and call a later rerun an untouched final test.", "",
        "## Files", "",
        "- `reference_model/`: original recipe's model, metadata, CV report, importance and tract scores.",
        "- `corrected_research/`: fixed-round models, native fold models, full training matrix, fold assignments, held-out predictions, comparisons and evaluations.",
        "- `scenarios/`: frozen access/Huff outputs, synthetic-property research rankings and optional-weight sensitivity.",
        "- `frozen_root/data/`: exact input copies; `code_snapshot/`: source snapshot; `logs/`: processing/training logs.",
        "- `run_manifest.json`: hashes and environment; current validation is stored separately so the completed training run stays unchanged."]
    (output / "RESULTS.md").write_text("\n".join(text) + "\n")
    print(json.dumps({"status": result["status"], "native_fold_replays": len(checks),
        "cohort_rows": len(rows), "paired_comparison": comparison, "output": str(output)}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate(args.run, args.output)
