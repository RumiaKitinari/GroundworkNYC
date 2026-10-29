"""Development-only proxy optimization, with locked, previously exposed assessment."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
import xgboost as xgb

from customer_access import file_hash
from survival_metrics import evaluate_predictions, fit_constant_aft, interval_nll, paired_concordance_delta
from train_archive_aft import research_matrix
from train_survival import PARAMS, survival_prob

ROOT = Path(__file__).resolve().parents[1]


def group_role(nta):
    if pd.isna(nta) or not str(nta).strip():
        raise ValueError("Explicit NTA required for grouped optimization")
    code = int(hashlib.sha256(("groundwork-opt-v1|" + str(nta)).encode()).hexdigest(), 16)
    return "reserved_assessment" if code % 5 == 0 else "development"


def feature_policies(rows):
    context = [column for column in rows if column.startswith("context_")]
    if len(context) != 38:
        raise ValueError("Expected the pinned 38-feature corrected context")
    restaurant = ["is_chain", "competitors_400m_at_open", "open_year"]
    full = context + restaurant
    return {"context_only": context,
        "context_without_current_supply": [c for c in context if c not in
            {"context_food_poi_density", "context_cafe_density", "context_bar_density"}],
        "corrected_full": full,
        "without_open_year": [c for c in full if c != "open_year"],
        "without_chain": [c for c in full if c != "is_chain"],
        "without_both": context + ["competitors_400m_at_open"],
        "without_competition": context + ["is_chain", "open_year"],
        "opening_year_only": ["open_year"], "chain_only": ["is_chain"],
        "competition_only": ["competitors_400m_at_open"]}


def fit_model(rows, columns, parameters):
    data = research_matrix(rows, columns)
    data.set_float_info("label_lower_bound", rows.y_lower.to_numpy(float))
    data.set_float_info("label_upper_bound", rows.y_upper.to_numpy(float))
    changes = {key: value for key, value in parameters.items() if key not in {"id", "rounds"}}
    return xgb.train({**PARAMS, **changes}, data, num_boost_round=parameters["rounds"])


def development_cv(development, columns, parameters, folds=3):
    if "optimization_role" in development and development.optimization_role.ne("development").any():
        raise ValueError("Reserved assessment rows cannot enter development CV")
    if development.nta_code.nunique() < folds:
        raise ValueError("Insufficient development neighborhoods")
    predictions = pd.Series(np.nan, index=development.index, dtype=float)
    assignments = pd.Series(-1, index=development.index, dtype=int)
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=folds).split(development, groups=development.nta_code)):
        training, validation = development.iloc[tr], development.iloc[te]
        if set(training.nta_code) & set(validation.nta_code):
            raise ValueError("Development neighborhood overlap")
        model = fit_model(training, columns, parameters)
        predictions.loc[validation.index] = model.predict(research_matrix(validation, columns))
        assignments.loc[validation.index] = fold
    if predictions.isna().any():
        raise ValueError("Incomplete development predictions")
    score = float(interval_nll(predictions, development.y_lower, development.y_upper).mean())
    return predictions, assignments, score


def select_candidate(development, plan, policies):
    records, predictions = [], {}
    for policy in plan["feature_policies"]:
        for parameters in plan["parameter_candidates"]:
            name = policy + "__" + parameters["id"]
            print("Development search: " + name, flush=True)
            pred, folds, score = development_cv(development, policies[policy], parameters, plan["development_folds"])
            records.append({"candidate": name, "policy": policy, "parameters": parameters,
                "development_interval_nll": score, "features": len(policies[policy])})
            predictions[name] = (pred, folds)
    selected = min(records, key=lambda row: (row["development_interval_nll"], row["candidate"]))
    return selected, records, predictions


def closure_variant(rows, captures, rule):
    captures = np.array(sorted(set(pd.to_datetime(captures))), dtype="datetime64[ns]")
    if len(captures) < 3:
        raise ValueError("Archive sensitivity needs multiple capture dates")
    result = rows.copy()
    last = pd.to_datetime(result.last_snapshot).to_numpy(dtype="datetime64[ns]")
    opportunities = (captures[None, :] > last[:, None]).sum(axis=1)
    days = (captures[-1] - last).astype("timedelta64[D]").astype(int)
    thresholds = {"one_later_capture": 1, "two_later_captures": 2,
                  "three_later_captures": 3, "two_later_captures_and_180_days": 2}
    if rule not in thresholds:
        raise ValueError("Unknown disappearance sensitivity rule")
    strong = opportunities >= thresholds[rule]
    if rule.endswith("180_days"):
        strong &= days >= 180
    finite = np.isfinite(result.y_upper.to_numpy(float))
    result.loc[finite & ~strong, "y_upper"] = np.inf
    return result, {"rule": rule, "finite_proxy_events": int(np.isfinite(result.y_upper).sum()),
        "weak_events_recensored": int((finite & ~strong).sum()),
        "basis": "Later capture dates inferred from consolidated archive endpoints, not independently verified closure observations"}


def optimize(source, output, plan_path):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT / "data/output"):
        raise ValueError("Choose a new private data/output directory")
    parent = json.loads((source / "run_manifest.json").read_text())
    if parent.get("status") != "completed_offline_proxy_research":
        raise ValueError("Completed frozen parent research run required")
    for name in ("corrected_research/training_rows.csv", "frozen_root/data/restaurants_raw.parquet"):
        if file_hash(source / name) != parent["artifact_sha256"][name]:
            raise ValueError("Parent input changed: " + name)
    plan = json.loads(Path(plan_path).read_text())
    if plan.get("schema") != "archive-optimization-plan-v1" or plan.get("globally_untouched_test") is not False:
        raise ValueError("Preserve the known prior exposure disclosure")
    rows = pd.read_csv(source / "corrected_research/training_rows.csv", dtype={"camis": str, "geoid": str},
                       low_memory=False, float_precision="round_trip")
    if rows.camis.duplicated().any():
        raise ValueError("Duplicate cohort identities")
    rows["optimization_role"] = rows.nta_code.map(group_role)
    development = rows[rows.optimization_role.eq("development")].copy()
    reserved = rows[rows.optimization_role.eq("reserved_assessment")].copy()
    if not len(reserved) or set(development.nta_code) & set(reserved.nta_code):
        raise ValueError("Invalid grouped reservation")
    policies = feature_policies(rows)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(plan_path, output / "plan.json")
    for name in ("optimize_archive_model.py", "survival_metrics.py", "train_archive_aft.py", "train_survival.py"):
        shutil.copy2(Path(__file__).with_name(name), output / name)
    rows[["camis", "nta_code", "borough", "optimization_role"]].to_csv(output / "split_assignments.csv", index=False)
    selected, search, predictions = select_candidate(development, plan, policies)
    pd.DataFrame([{**row, "parameters": json.dumps(row["parameters"], sort_keys=True)} for row in search]).to_csv(output / "development_search.csv", index=False)
    chosen_columns = policies[selected["policy"]]
    lock = {"schema": plan["schema"], "selection": selected, "features": chosen_columns,
        "parent_manifest_sha256": file_hash(source / "run_manifest.json"), "plan_sha256": file_hash(plan_path),
        "locked_before_assessment": True, "globally_untouched_test": False,
        "prior_exposure": plan["prior_exposure"], "locked_at": datetime.now(timezone.utc).isoformat()}
    (output / "selection_lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    lock_hash = file_hash(output / "selection_lock.json")
    base = plan["parameter_candidates"][0]
    diagnostic_records = []
    for policy in plan["diagnostics"]:
        print("Feature diagnostic: " + policy, flush=True)
        pred, _, _ = development_cv(development, policies[policy], base, plan["development_folds"])
        diagnostic_records.append({"feature_policy": policy,
            **evaluate_predictions(pred, development.y_lower, development.y_upper)})
    (output / "development_feature_diagnostics.json").write_text(json.dumps(diagnostic_records, indent=2, allow_nan=False) + "\n")
    raw = pd.read_parquet(source / "frozen_root/data/restaurants_raw.parquet", columns=["first_snapshot", "last_snapshot"])
    captures = pd.concat([raw.first_snapshot, raw.last_snapshot]).dropna().unique()
    sensitivity = []
    for rule in plan["closure_sensitivity"]:
        variant, audit = closure_variant(development, captures, rule)
        print("Closure sensitivity: " + rule, flush=True)
        pred, _, _ = development_cv(variant, chosen_columns, selected["parameters"], plan["development_folds"])
        sensitivity.append({**audit, **evaluate_predictions(pred, variant.y_lower, variant.y_upper),
            "predicted_time_rank_correlation_with_primary": float(pred.corr(predictions[selected["candidate"]][0], method="spearman"))})
    (output / "development_closure_sensitivity.json").write_text(json.dumps(sensitivity, indent=2, allow_nan=False) + "\n")
    # No reserved outcomes or predictions have been passed to any selection above.
    print("Selection locked; running the reserved assessment once", flush=True)
    chosen_model = fit_model(development, chosen_columns, selected["parameters"])
    default_model = fit_model(development, policies["context_only"], base)
    full_diagnostic = fit_model(development, policies["corrected_full"], base)
    pred = chosen_model.predict(research_matrix(reserved, chosen_columns))
    default_pred = default_model.predict(research_matrix(reserved, policies["context_only"]))
    full_pred = full_diagnostic.predict(research_matrix(reserved, policies["corrected_full"]))
    baseline = fit_constant_aft(development.y_lower, development.y_upper)
    assessment = {"selected": evaluate_predictions(pred, reserved.y_lower, reserved.y_upper, reserved.nta_code),
        "untuned_context_baseline": evaluate_predictions(default_pred, reserved.y_lower, reserved.y_upper, reserved.nta_code),
        "full_41_feature_diagnostic": evaluate_predictions(full_pred, reserved.y_lower, reserved.y_upper, reserved.nta_code),
        "constant_aft": evaluate_predictions(np.full(len(reserved), baseline), reserved.y_lower, reserved.y_upper, reserved.nta_code),
        "paired_selected_minus_untuned": paired_concordance_delta(default_pred, pred, reserved.y_lower, reserved.y_upper, reserved.nta_code),
        "globally_untouched_test": False, "prior_exposure": plan["prior_exposure"],
        "selection_lock_sha256": lock_hash}
    (output / "reserved_assessment.json").write_text(json.dumps(assessment, indent=2, allow_nan=False) + "\n")
    heldout = reserved[["camis", "geoid", "nta_code", "borough", "open_date", "y_lower", "y_upper"]].copy()
    heldout["selected_median_years"], heldout["default_median_years"] = pred, default_pred
    heldout["full_diagnostic_median_years"] = full_pred
    heldout["selected_proxy_aft_3yr"] = survival_prob(pred)
    heldout.to_csv(output / "reserved_predictions.csv", index=False)
    for label, model in (("selected", chosen_model), ("untuned", default_model), ("full_diagnostic", full_diagnostic)):
        model.save_model(output / (label + "_model.json"))
    pd.Series(chosen_model.get_score(importance_type="gain"), name="gain", dtype=float).sort_values(ascending=False).to_csv(output / "selected_feature_importance.csv")
    # Cohort shift is a development-only retrospective challenge, not a forecast:
    # current feature vintages and label availability remain unverified.
    earlier = development[development.open_date.lt("2024-01-01")]
    later = development[development.open_date.ge("2024-01-01")]
    if len(earlier) and len(later) and np.isfinite(earlier.y_upper).any():
        temporal_model = fit_model(earlier, chosen_columns, selected["parameters"])
        temporal_pred = temporal_model.predict(research_matrix(later, chosen_columns))
        temporal = evaluate_predictions(temporal_pred, later.y_lower, later.y_upper)
        temporal["scope"] = "Development opening-cohort shift only; not point-in-time validation or spatially independent from training"
        (output / "development_cohort_shift.json").write_text(json.dumps(temporal, indent=2, allow_nan=False) + "\n")
    metadata = {"schema": "optimized-archive-proxy-v1", "deployment_status": "offline_proxy_research_only",
        "features": chosen_columns, "parameters": selected["parameters"], "training_rows": len(development),
        "reserved_rows": len(reserved), "globally_untouched_test": False,
        "selection_lock_sha256": lock_hash, "historical_availability_verified": False,
        "permanent_closures_verified": False, "production_deployment_allowed": False}
    (output / "model_meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if file_hash(output / "selection_lock.json") != lock_hash:
        raise ValueError("Selection changed after assessment")
    manifest = {"schema": plan["schema"], "status": "completed_offline_optimization",
        "parent_run": str(source), "parent_manifest_sha256": file_hash(source / "run_manifest.json"),
        "development_rows": len(development), "reserved_rows": len(reserved),
        "development_ntas": int(development.nta_code.nunique()), "reserved_ntas": int(reserved.nta_code.nunique()),
        "selection": selected, "globally_untouched_test": False, "deployment_allowed": False,
        "software": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scipy", "xgboost", "scikit-learn")},
        "artifact_sha256": {p.name: file_hash(p) for p in output.iterdir() if p.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: manifest[k] for k in ("status", "development_rows", "reserved_rows", "selection")}, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=Path(__file__).with_name("archive_optimization_plan.json"))
    args = parser.parse_args()
    optimize(args.source, args.output, args.plan)
