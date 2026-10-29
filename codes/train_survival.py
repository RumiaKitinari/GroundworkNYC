"""Guarded opening-date XGBoost AFT research with point-in-time predictors.

Legacy restaurant_lifespans.csv is NOT verified evidence. See TEMPORAL_SURVIVAL.md
for baseline/observation schemas, snapshot manifests, and reproducible commands.
No current master, retrospective chain counts, or disappearance labels are used.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm

from paths import DATA, MODEL, find
from features import (HISTORICAL_FEATURES, TEMPORAL_SCHEMA, build_historical_features,
                      load_historical_snapshots)
from temporal_cohort import (BASELINE_FIELDS, OBSERVATION_FIELDS, outcome_intervals,
                             parse_date, three_year_outcome, validate_baselines,
                             validate_observations)
from survival_metrics import evaluate_predictions, fit_constant_aft

HORIZON_YEARS = 3.0
AFT_SCALE = 1.0
PARAMS = {
    "objective": "survival:aft", "eval_metric": "aft-nloglik",
    "aft_loss_distribution": "normal", "aft_loss_distribution_scale": AFT_SCALE,
    "tree_method": "hist", "learning_rate": 0.03, "max_depth": 5,
    "min_child_weight": 25, "subsample": 0.8, "colsample_bytree": 0.7,
    "lambda": 2.0, "seed": 440, "nthread": 1,
}
# Fixed BEFORE holdout evaluation. No early stopping or round selection on test labels.
DEFAULT_ROUNDS = 200
LIMITATIONS = [
    "Availability/provenance declarations require independent source review; hashes alone do not verify them.",
    "Inferred opening is an uncertain time origin, not a verified first trading date; opening-date uncertainty is not modeled.",
    "Dated operation and permanent-closure evidence must refer to the same business/location spell; identity reconciliation remains necessary.",
    "Operating observations do not establish uninterrupted operation between observations; censoring may be informative.",
    "Chain, opening-time competition, and current-only neighborhood features are excluded until historically available evidence exists.",
    "Three-year probabilities assume a log-normal AFT distribution; unresolved three-year outcomes are not classified as survival.",
    "A temporal/spatial holdout tests only its specified period and coverage, not future stability or population representativeness.",
]


def fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def survival_prob(pred_time, horizon=HORIZON_YEARS, scale=AFT_SCALE):
    mu = np.log(np.clip(pred_time, 1e-6, None))
    return norm.sf((np.log(horizon) - mu) / scale)


def concordance(pred_time, lower, upper, n_pairs=300_000, seed=440):
    """Sampled interval-order concordance, not an exact-event Harrell estimator."""
    pred_time, lower, upper = map(np.asarray, (pred_time, lower, upper))
    valid = np.isfinite(pred_time) & np.isfinite(lower)
    pred_time, lower, upper = pred_time[valid], lower[valid], upper[valid]
    if len(pred_time) < 2:
        return None
    rng = np.random.default_rng(seed)
    i, j = rng.integers(0, len(pred_time), (2, n_pairs))
    comparable = np.isfinite(upper[i]) & (upper[i] < lower[j]) & (i != j)
    if not comparable.any():
        return None
    a, b = pred_time[i[comparable]], pred_time[j[comparable]]
    return float(np.mean((a < b) + 0.5 * (a == b)))


def build_training_rows(baselines, observations, snapshots, as_of, strict_before=False):
    rows, excluded = outcome_intervals(baselines, observations, as_of, strict_before)
    features, provenance = build_historical_features(rows, snapshots)
    usable = features.notna().any(axis=1)
    excluded["no_historical_features"] = int((~usable).sum())
    rows = rows.loc[usable].copy()
    rows[list(HISTORICAL_FEATURES)] = features.loc[usable]
    return rows, excluded, provenance


def fold_for_nta(nta, folds=5):
    return int(hashlib.sha256(str(nta).encode()).hexdigest(), 16) % folds


def temporal_folds(baselines, observations, snapshots, cutoff, as_of, folds=5):
    if not parse_date(cutoff) < parse_date(as_of):
        raise ValueError("Temporal cutoff must precede analysis as-of date")
    # Both baseline and label information must predate the deployment cutoff.
    prior = baselines[baselines.open_date < cutoff]
    later = baselines[baselines.open_date >= cutoff]
    training, train_excluded, _ = build_training_rows(prior, observations, snapshots, cutoff, True)
    testing, test_excluded, _ = build_training_rows(later, observations, snapshots, as_of)
    for fold in range(folds):
        train = training[training.nta_code.map(lambda g: fold_for_nta(g, folds) != fold).astype(bool)].copy()
        test = testing[testing.nta_code.map(lambda g: fold_for_nta(g, folds) == fold).astype(bool)].copy()
        assert set(train.nta_code).isdisjoint(test.nta_code)
        assert not len(train) or (train.label_available_on < cutoff).all()
        yield fold, train, test, {"training": train_excluded, "testing": test_excluded}


def matrix(rows, labels=True):
    dm = xgb.DMatrix(rows[list(HISTORICAL_FEATURES)].to_numpy(dtype=float),
                     feature_names=list(HISTORICAL_FEATURES))
    if labels:
        dm.set_float_info("label_lower_bound", rows.y_lower.to_numpy(dtype=float))
        dm.set_float_info("label_upper_bound", rows.y_upper.to_numpy(dtype=float))
    return dm


def has_training_information(rows):
    # An all-censored dataset does not identify this restaurant-exit model.
    return len(rows) >= 2 and np.isfinite(rows.y_upper.astype(float)).any()


def run(baseline_path, observation_path, manifests, data_dir, output, as_of,
        cutoff=None, rounds=DEFAULT_ROUNDS, folds=5, audit_only=False, evaluation_plan=None):
    if parse_date(as_of) > date.today():
        raise ValueError("Analysis date cannot be in the future")
    if rounds < 1 or not 2 <= folds <= 10:
        raise ValueError("Use positive rounds and 2-10 spatial folds")
    if not audit_only and (not cutoff or not observation_path):
        raise ValueError("Training requires --cutoff and --observations with dated verified evidence")
    if cutoff and not parse_date(cutoff) < parse_date(as_of):
        raise ValueError("Temporal cutoff must precede analysis as-of date")
    if evaluation_plan:
        plan = json.loads(Path(evaluation_plan).read_text())
        expected = {"schema": "groundwork-evaluation-plan-v1", "cutoff": cutoff, "as_of": as_of,
                    "rounds": rounds, "folds": folds, "horizon_years": HORIZON_YEARS,
                    "predictors": list(HISTORICAL_FEATURES)}
        if any(plan.get(key) != value for key, value in expected.items()):
            raise ValueError("Run arguments disagree with the frozen evaluation plan")
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Choose a new run directory; preserving existing files: {output}")
    baseline_path = Path(baseline_path)
    source_paths = [baseline_path, *map(Path, manifests)]
    if observation_path:
        source_paths.append(Path(observation_path))
    if evaluation_plan:
        source_paths.append(Path(evaluation_plan))
    # Pin the actual bytes read; detect concurrent replacement before publication.
    input_hashes = {str(p.resolve()): fingerprint(p) for p in source_paths}
    raw = pd.read_csv(baseline_path, dtype=str, keep_default_na=False)
    audit = {"schema": TEMPORAL_SCHEMA, "as_of": as_of, "cutoff": cutoff,
             "training_performed": False, "input_rows": len(raw), "limitations": LIMITATIONS,
             "source_sha256": input_hashes, "excluded_features": [
                 "is_chain", "competitors_400m_at_open", "open_year",
                 "all current-master features and neighbor imputations"],
             "features": list(HISTORICAL_FEATURES)}
    if evaluation_plan:
        audit["evaluation_plan_version"] = plan["version"]
    missing = sorted(set(BASELINE_FIELDS) - set(raw.columns))
    if missing:
        audit.update(status="needs_dated_baseline_evidence", missing_baseline_fields=missing)
        if not audit_only:
            raise ValueError("Legacy lifespan input lacks dated baseline evidence: " + ", ".join(missing))
        # Still check manifests in audit mode: bad provenance must never be masked.
        load_historical_snapshots(manifests, data_dir, as_of)
        output.mkdir(parents=True, exist_ok=False)
        (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
        return audit
    baselines, excluded = validate_baselines(raw, as_of)
    ledger = (pd.read_csv(observation_path, dtype=str, keep_default_na=False) if observation_path
              else pd.DataFrame(columns=OBSERVATION_FIELDS))
    observations = validate_observations(ledger, baselines)
    snapshots = load_historical_snapshots(manifests, data_dir, as_of)
    rows, label_excluded, provenance = build_training_rows(baselines, observations, snapshots, as_of)
    audit.update(baseline_exclusions=excluded, label_exclusions=label_excluded,
                 eligible_rows=len(rows), verified_observations=len(observations))
    models, predictions, fold_audits, assignments = {}, [], [], []
    if not audit_only and has_training_information(rows):
        for fold, tr, te, rejection in temporal_folds(baselines, observations, snapshots, cutoff, as_of, folds):
            record = {"fold": fold, "train_rows": len(tr), "test_rows": len(te),
                      "train_ntas": sorted(set(tr.nta_code)), "test_ntas": sorted(set(te.nta_code)),
                      "excluded": rejection, "status": "insufficient_training_or_test_evidence"}
            for role, group in (("train", tr), ("test", te)):
                assignments.extend({"fold": fold, "role": role, "camis": r.camis,
                                    "open_date": r.open_date, "nta_code": r.nta_code,
                                    "y_lower": r.y_lower, "y_upper": r.y_upper,
                                    "label_available_on": r.label_available_on}
                                   for r in group.itertuples())
            if has_training_information(tr) and len(te):
                # No eval/test DMatrix is passed to fit. Uniform weights; no
                # learned imputation, income quantiles, or full-cohort statistics.
                model = xgb.train(PARAMS, matrix(tr), num_boost_round=rounds)
                pred = model.predict(matrix(te, labels=False))
                record.update(status="evaluated", interval_concordance=concordance(pred, te.y_lower, te.y_upper))
                baseline_median = fit_constant_aft(tr.y_lower, tr.y_upper, AFT_SCALE)
                record["evaluation"] = evaluate_predictions(pred, te.y_lower, te.y_upper, te.nta_code, AFT_SCALE)
                record["constant_aft_baseline"] = evaluate_predictions(
                    np.full(len(te), baseline_median), te.y_lower, te.y_upper, te.nta_code, AFT_SCALE)
                record["feature_ablations"] = {}
                for feature in HISTORICAL_FEATURES:
                    train_drop, test_drop = tr.copy(), te.copy()
                    train_drop[feature], test_drop[feature] = np.nan, np.nan
                    ablated = xgb.train(PARAMS, matrix(train_drop), num_boost_round=rounds)
                    ablated_prediction = ablated.predict(matrix(test_drop, labels=False))
                    record["feature_ablations"]["without_" + feature] = evaluate_predictions(
                        ablated_prediction, te.y_lower, te.y_upper, scale=AFT_SCALE)
                results = te[["camis", "open_date", "nta_code", "y_lower", "y_upper"]].copy()
                results["fold"] = fold
                results["survival_3yr"] = survival_prob(pred)
                results["known_3yr_outcome"] = three_year_outcome(te.y_lower, te.y_upper)
                results["median_years"] = pred
                results["baseline_median_years"] = baseline_median
                results["baseline_survival_3yr"] = survival_prob(np.full(len(te), baseline_median))
                predictions.append(results)
                models[f"fold_{fold}.json"] = model
            fold_audits.append(record)
        # Refuse a final artifact advertised as temporally evaluated when no
        # chronological/spatial holdout can actually be evaluated.
        if predictions:
            models["survival_model.json"] = xgb.train(PARAMS, matrix(rows), num_boost_round=rounds)
            audit.update(training_performed=True, status="research_model_trained")
        else:
            audit["status"] = "insufficient_temporal_validation_evidence"
    else:
        audit["status"] = "audit_only" if audit_only else "insufficient_verified_outcomes"
    audit["folds"] = fold_audits
    audit["params"] = PARAMS
    audit["n_rounds"] = rounds
    audit["preprocessing"] = "fixed log1p; missing remains NaN; uniform weights; no fitted preprocessing"
    audit["fold_rule"] = f"SHA256(NTA) mod {folds}; train openings and label availability strictly before cutoff"
    audit["software"] = {package: importlib.metadata.version(package)
                         for package in ("numpy", "pandas", "scipy", "xgboost", "scikit-learn")}
    audit["python"] = platform.python_version()
    audit["code_sha256"] = {name: fingerprint(Path(__file__).with_name(name)) for name in
                             ("train_survival.py", "features.py", "temporal_cohort.py", "recommend.py", "survival_metrics.py")}
    shared = Path(__file__).resolve().parents[1] / "demo" / "prepare_historical_cohort.py"
    audit["code_sha256"]["demo/prepare_historical_cohort.py"] = fingerprint(shared)
    for p in source_paths:
        if fingerprint(p) != input_hashes[str(p.resolve())]:
            raise ValueError(f"Input changed during training: {p}")
    for entries in snapshots.values():
        for item in entries:
            if fingerprint(Path(data_dir) / item["path"]) != item["sha256"]:
                raise ValueError("Historical snapshot changed during training")
    output.mkdir(parents=True, exist_ok=False)
    rows.to_csv(output / "training_rows.csv", index=False)
    pd.DataFrame(provenance).to_csv(output / "feature_provenance.csv", index=False)
    pd.DataFrame(assignments).to_csv(output / "fold_assignments.csv", index=False)
    report = ["Opening-date temporal/spatial holdout (research only)",
              f"Training labels strictly before {cutoff}; test follow-up through {as_of}",
              "Boosting rounds fixed before evaluation; no test-label early stopping."]
    report += [f"Fold {r['fold']}: {r['status']}; train={r['train_rows']}; test={r['test_rows']}; "
               f"interval concordance={r.get('interval_concordance')}" for r in fold_audits]
    report += ["", "Limitations:", *LIMITATIONS]
    (output / "cv_report.txt").write_text("\n".join(report) + "\n")
    if predictions:
        heldout = pd.concat(predictions, ignore_index=True)
        heldout.to_csv(output / "heldout_predictions.csv", index=False)
        evaluation = {"scope": "Frozen temporal/geographic holdout; no test-label tuning",
            "overall": evaluate_predictions(heldout.median_years, heldout.y_lower, heldout.y_upper, heldout.nta_code),
            "baseline": evaluate_predictions(heldout.baseline_median_years, heldout.y_lower, heldout.y_upper, heldout.nta_code),
            "folds": fold_audits}
        (output / "evaluation.json").write_text(json.dumps(evaluation, indent=2, allow_nan=False) + "\n")
    for name, model in models.items():
        model.save_model(output / name)
    if audit["training_performed"]:
        meta = {"schema": TEMPORAL_SCHEMA, "features": list(HISTORICAL_FEATURES),
                "aft_scale": AFT_SCALE, "horizon_years": HORIZON_YEARS, "trained_as_of": as_of,
                "n_rounds": rounds, "n_training_rows": len(rows), "deployment_status": "research_only",
                "preprocessing": audit["preprocessing"], "limitations": LIMITATIONS}
        (output / "model_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        pd.Series(models["survival_model.json"].get_score(importance_type="gain"), dtype=float,
                  name="gain").sort_values(ascending=False).to_csv(output / "feature_importance.csv")
    audit["artifact_sha256"] = {p.name: fingerprint(p) for p in output.iterdir() if p.is_file()}
    (output / "audit.json").write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", "--lifespans", dest="baselines", type=Path,
                        default=find("restaurant_lifespans.csv"), help="Dated baseline evidence, not legacy lifespan summaries")
    parser.add_argument("--observations", type=Path, help="Verified dated operation/closure evidence ledger")
    parser.add_argument("--snapshots", type=Path, action="append", required=True, help="Pinned historical manifest; repeat to combine vintages")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--as-of", required=True, help="Freeze analysis/label availability at YYYY-MM-DD")
    parser.add_argument("--cutoff", help="Predeclared future-cohort validation cutoff, YYYY-MM-DD")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--evaluation-plan", type=Path, help="Reject runs that disagree with this pinned evaluation plan")
    parser.add_argument("--out-dir", type=Path, default=MODEL / datetime.now(timezone.utc).strftime("temporal_%Y%m%dT%H%M%S%fZ"))
    a = parser.parse_args()
    try:
        result = run(a.baselines, a.observations, a.snapshots, a.data_dir, a.out_dir,
                     a.as_of, a.cutoff, a.rounds, a.folds, a.audit_only, a.evaluation_plan)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Temporal survival training stopped: {error}\n")
    print(json.dumps({"status": result["status"], "training_performed": result["training_performed"],
                      "output": str(a.out_dir)}, indent=2))
    if not a.audit_only and not result["training_performed"]:
        parser.exit(2, "No final survival model: inspect audit.json for missing dated evidence.\n")


if __name__ == "__main__":
    main()
