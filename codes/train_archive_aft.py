"""Explicitly labeled retrospective AFT research; never bypasses verified training."""
import argparse
from datetime import date
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
import xgboost as xgb

from features import CompetitionIndex, build_tract_features, model_columns
from model_feature_catalog import current_context_features
from survival_metrics import evaluate_predictions, fit_constant_aft
from train_survival import PARAMS, survival_prob
from customer_access import file_hash

SCHEMA = "archive-aft-proxy-v1"
RESTAURANT_FEATURES = ["is_chain", "competitors_400m_at_open", "open_year"]


def load_reference(path):
    spec = importlib.util.spec_from_file_location("pinned_archive_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def research_matrix(rows, columns):
    values = rows[columns].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return xgb.DMatrix(values.to_numpy(float), feature_names=list(columns))


def fit(rows, columns, rounds):
    data = research_matrix(rows, columns)
    data.set_float_info("label_lower_bound", rows.y_lower.to_numpy(float))
    data.set_float_info("label_upper_bound", rows.y_upper.to_numpy(float))
    return xgb.train(PARAMS, data, num_boost_round=rounds)


def assemble(master, life, reference):
    legacy = build_tract_features(master)
    rows, latest = reference.build_training_rows(life, legacy, master)
    rows = rows.reset_index(drop=True)
    rows["geoid"] = rows.geoid.astype(str)
    if rows.camis.duplicated().any() or not len(rows):
        raise ValueError("Archive cohort must contain unique restaurant identities")
    if (rows.y_lower.le(0).any() or rows.y_upper.lt(rows.y_lower).any()
            or not np.isfinite(rows.y_lower).all()):
        raise ValueError("Invalid archive interval bounds")
    context, dictionary = current_context_features(master.assign(geoid=master.geoid.astype(str)))
    context = context.set_index("geoid").add_prefix("context_")
    rows = rows.join(context, on="geoid", validate="many_to_one")
    legacy_columns = model_columns(legacy) + RESTAURANT_FEATURES
    corrected_columns = list(context.columns) + RESTAURANT_FEATURES
    groups = {str(group): ["context_" + str(name) for name in block.feature]
              for group, block in dictionary.groupby("group")}
    return rows, latest, legacy_columns, corrected_columns, dictionary, groups


def train(master_path, life_path, listings_path, reference_path, output, plan_path):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Preserving previous model outputs; choose a new directory")
    plan = json.loads(Path(plan_path).read_text())
    if plan.get("schema") != "archive-aft-research-plan-v1" or plan.get("production_deployment_allowed") is not False:
        raise ValueError("Explicit nonproduction archive research plan required")
    master = pd.read_csv(master_path)
    life = pd.read_csv(life_path, low_memory=False)
    reference = load_reference(reference_path)
    rows, latest, legacy_columns, corrected_columns, dictionary, groups = assemble(master, life, reference)
    rounds, folds = int(plan["rounds"]), int(plan["folds"])
    if rounds < 1 or folds != 5:
        raise ValueError("Use the declared positive rounds and five NTA folds")
    configurations = {"legacy_50": legacy_columns, "corrected_context_plus_restaurant": corrected_columns}
    for group in plan["ablations"]:
        configurations["corrected_without_" + group] = [c for c in corrected_columns if c not in groups[group]]
    output.mkdir(parents=True, exist_ok=False)
    rows.to_csv(output / "training_rows.csv", index=False)
    dictionary.to_csv(output / "corrected_feature_dictionary.csv", index=False)
    records, metrics, assignments = [], [], []
    split = GroupKFold(n_splits=folds)
    for fold, (tr, te) in enumerate(split.split(rows, groups=rows.nta_code.fillna("NA"))):
        training, testing = rows.iloc[tr], rows.iloc[te]
        if set(training.nta_code) & set(testing.nta_code):
            raise ValueError("Training and testing neighborhoods overlap")
        assignments.extend({"camis": str(row.camis), "nta_code": row.nta_code, "fold": fold}
                           for row in testing.itertuples())
        baseline = fit_constant_aft(training.y_lower, training.y_upper)
        for name, columns in configurations.items():
            print(f"Fold {fold + 1}/{folds}: {name} ({len(columns)} features)", flush=True)
            model = fit(training, columns, rounds)
            prediction = model.predict(research_matrix(testing, columns))
            model.save_model(output / f"{name}_fold_{fold}.json")
            part = testing[["camis", "geoid", "nta_code", "borough", "open_date", "y_lower", "y_upper"]].copy()
            part["fold"], part["model"] = fold, name
            part["median_years"], part["constant_aft_median_years"] = prediction, baseline
            part["proxy_aft_3yr"] = survival_prob(prediction)
            part["outcome_basis"] = "archive_disappearance_proxy"
            records.append(part)
            metrics.append({"fold": fold, "model": name, "training_rows": len(training),
                **evaluate_predictions(prediction, testing.y_lower, testing.y_upper)})
    heldout = pd.concat(records, ignore_index=True)
    heldout.to_csv(output / "heldout_predictions.csv", index=False)
    pd.DataFrame(assignments).to_csv(output / "fold_assignments.csv", index=False)
    summary, borough_metrics = {}, []
    for name, group in heldout.groupby("model"):
        summary[name] = evaluate_predictions(group.median_years, group.y_lower, group.y_upper,
            group.nta_code if name in ("legacy_50", "corrected_context_plus_restaurant") else None)
        for borough, subset in group.groupby("borough"):
            borough_metrics.append({"model": name, "borough": borough,
                **evaluate_predictions(subset.median_years, subset.y_lower, subset.y_upper)})
    baseline_rows = heldout[heldout.model.eq("legacy_50")]
    summary["constant_aft"] = evaluate_predictions(baseline_rows.constant_aft_median_years,
        baseline_rows.y_lower, baseline_rows.y_upper, baseline_rows.nta_code)
    full_models = {}
    for name in ("legacy_50", "corrected_context_plus_restaurant"):
        print("Fitting full research artifact: " + name, flush=True)
        columns = configurations[name]
        model = fit(rows, columns, rounds)
        folder = output / name
        folder.mkdir()
        model.save_model(folder / "survival_model.json")
        pd.Series(model.get_score(importance_type="gain"), name="gain", dtype=float).sort_values(ascending=False).to_csv(folder / "feature_importance.csv")
        meta = {"schema": SCHEMA, "target": plan["target"], "features": columns,
            "horizon_years": 3.0, "aft_scale": 1.0, "n_rounds": rounds,
            "n_training_rows": len(rows), "archive_observed_through": str(latest.date()),
            "analysis_as_of": date.today().isoformat(), "deployment_status": "offline_proxy_research_only",
            "artifact_sha256": file_hash(folder / "survival_model.json"),
            "trained_on_synthetic_properties": False,
            "limitations": ["Current context is attached retrospectively; this is not a historically leakage-free forecast.",
                "First pre-permit inspection and archive disappearance are uncertain time-origin/event proxies.",
                "Full-archive name counts and reconstructed competitors can contain future information.",
                "Cuisine and rent are excluded. Current walking/Huff features remain separate scenario outputs.",
                "The AFT CDF is a research proxy output, not calibrated permanent-closure survival."]}
        (folder / "model_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        full_models[name] = (model, columns)
    properties = pd.read_csv(listings_path, dtype={"property_id": str, "geoid": str})
    legacy = build_tract_features(master)
    legacy.index = legacy.index.astype(str)
    context, _ = current_context_features(master.assign(geoid=master.geoid.astype(str)))
    context = context.set_index("geoid").add_prefix("context_")
    property_features = properties.join(legacy, on="geoid", rsuffix="_context", validate="many_to_one")
    property_features = property_features.join(context, on="geoid", validate="many_to_one")
    interval_life = life.assign(open_date=pd.to_datetime(life.open_date, errors="coerce"),
                                close_date=pd.to_datetime(life.close_date, errors="coerce"))
    competition = CompetitionIndex(interval_life, latest)
    property_features["competitors_400m_at_open"] = [competition.count(row.latitude, row.longitude, latest)
                                                    for row in properties.itertuples()]
    property_features["is_chain"], property_features["open_year"] = 0, date.today().year
    scenarios = properties.copy()
    for name, (model, columns) in full_models.items():
        scenarios[name + "_proxy_aft_3yr"] = survival_prob(model.predict(research_matrix(property_features, columns)))
    scenarios["prediction_scope"] = "Synthetic property; retrospective archive-proxy model scenario, not validated survival"
    scenarios.to_csv(output / "property_proxy_scores.csv", index=False)
    report = {"schema": SCHEMA, "plan": plan, "params": PARAMS, "training_rows": len(rows),
        "assumed_event_intervals": int(np.isfinite(rows.y_upper).sum()),
        "right_censored_rows": int(np.isposinf(rows.y_upper).sum()),
        "nta_groups": int(rows.nta_code.nunique()), "summary": summary,
        "fold_metrics": metrics, "borough_metrics": borough_metrics,
        "claim_scope": "Retrospective archive-proxy discrimination and scenario checks only; no verified survival accuracy or predictive feature improvement established"}
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    pd.DataFrame([{ "model": name, "rows": value["rows"],
        "interval_nll": value["interval_negative_log_likelihood"],
        "interval_concordance": value["concordance"]["estimate"],
        "resolved_3yr": value["resolved_3yr_rows"], "unresolved_3yr": value["unresolved_3yr_rows"]}
        for name, value in summary.items()]).to_csv(output / "model_comparison.csv", index=False)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("master", "lifespans", "listings", "reference", "output", "plan"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    train(args.master, args.lifespans, args.listings, args.reference, args.output, args.plan)
