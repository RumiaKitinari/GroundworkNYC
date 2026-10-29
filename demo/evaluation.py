"""Offline evaluation; none of these probabilities are customer-facing success scores."""

import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from math import log1p
from pathlib import Path

from scoring import CUISINES, number


VERSION = "evaluation-0.3"
FEATURES = (
    "population_density_per_sq_mile", "median_household_income",
    "job_density_per_sq_mile", "national_walkability_index",
    "nearest_subway_distance_miles", "nearest_subway_weekly_ridership",
    "retail_area_sqft", "mixed_use_parcel_count",
)
HISTORICAL_CORE_FEATURES = FEATURES[:4]
OUTCOME_METADATA = (
    "business_id", "nta_code", "as_of_date", "features_observed_through",
    "features_available_on", "baseline_operating", "outcome_status",
    "outcome_observed_on", "outcome_recorded_on", "source_reference",
)


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_vector(row, features=FEATURES, allow_current_income=True):
    return [log1p(value) if (value := number(row.get(key, row.get("median_household_income_2024")
            if allow_current_income and key == "median_household_income" else None))) is not None else float("nan")
            for key in features]


def presence_cohort(package, cuisine):
    if cuisine not in CUISINES or cuisine == "any":
        raise ValueError("Select a specific supported cuisine for evaluation.")
    model = package["screening_model"]
    rows, excluded = [], Counter()
    for tract in package["tracts"]:
        inventory = model.local[tract["geoid"]]
        total = sum(inventory.values())
        known = total - inventory["unknown"]
        if not tract.get("nta_code"):
            excluded["missing_neighborhood"] += 1
        elif total < 10 or known / total < .8:
            excluded["limited_cuisine_inventory"] += 1
        else:
            rows.append({"id": tract["geoid"], "group": tract["nta_code"],
                         "borough": tract.get("borough", "Unknown"), "x": feature_vector(tract),
                         "y": int(any(inventory[label] > 0 for label in CUISINES[cuisine]))})
    return rows, dict(excluded)


def outcome_cohort(path, cutoff, today=None, features=FEATURES):
    """Reject leakage and ambiguous negatives; unresolved records stay censored."""
    today = today or date.today()
    cutoff = date.fromisoformat(cutoff)
    if cutoff > today:
        raise ValueError("The training cutoff cannot be in the future.")
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = set(OUTCOME_METADATA + tuple(features)) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Outcome file is missing columns: " + ", ".join(sorted(missing)))
        records = list(reader)
    rows, excluded, seen = [], Counter(), set()
    for line, row in enumerate(records, 2):
        business_id = row["business_id"].strip()
        if not business_id or business_id in seen:
            raise ValueError(f"Line {line}: business IDs must be unique and nonempty.")
        seen.add(business_id)
        if row["outcome_status"] == "unresolved":
            excluded["censored_unresolved"] += 1
            continue
        if row["outcome_status"] not in {"verified_operating", "verified_permanent_closure"}:
            raise ValueError(f"Line {line}: unverified or temporary closures cannot label business failure.")
        if row["baseline_operating"].lower() != "true" or not row["nta_code"] or not row["source_reference"].strip():
            raise ValueError(f"Line {line}: baseline operation, neighborhood and evidence reference are required.")
        try:
            start = date.fromisoformat(row["as_of_date"])
            observed_features = date.fromisoformat(row["features_observed_through"])
            available_features = date.fromisoformat(row["features_available_on"])
            observed = date.fromisoformat(row["outcome_observed_on"])
            recorded = date.fromisoformat(row["outcome_recorded_on"])
        except ValueError as error:
            raise ValueError(f"Line {line}: dates must use YYYY-MM-DD.") from error
        if not observed_features <= available_features <= start < observed <= recorded <= today:
            raise ValueError(f"Line {line}: feature or outcome chronology leaks future information.")
        horizon = start + timedelta(days=365)
        positive = row["outcome_status"] == "verified_operating"
        if (positive and not horizon <= observed <= horizon + timedelta(days=90)) or (not positive and observed > horizon):
            excluded["outside_outcome_window"] += 1
            continue
        if horizon > today:
            excluded["immature_followup"] += 1
            continue
        invalid = [feature for feature in features if number(row.get(feature)) is None]
        if invalid:
            excluded["missing_or_invalid_historical_feature"] += 1
            continue
        rows.append({"id": business_id, "group": row["nta_code"], "borough": row.get("borough", "Unknown"),
                     "x": feature_vector(row, features, allow_current_income=False), "y": int(positive),
                     "as_of": start, "recorded": recorded})
    return rows, dict(excluded), cutoff


def holdout_indices(rows, cutoff=None):
    from sklearn.model_selection import GroupShuffleSplit
    import numpy as np
    groups = [row["group"] for row in rows]
    train, test = next(GroupShuffleSplit(n_splits=1, test_size=.25, random_state=440).split(rows, groups=groups))
    if cutoff is not None:
        train = np.array([i for i in train if rows[i]["as_of"] < cutoff and rows[i]["recorded"] < cutoff], dtype=int)
        test = np.array([i for i in test if rows[i]["as_of"] >= cutoff], dtype=int)
    return train, test


def top_quintile_precision(y, probabilities):
    import numpy as np
    size = max(1, int(np.ceil(len(y) * .2)))
    threshold = np.sort(probabilities)[-size]
    above, tied = probabilities > threshold, probabilities == threshold
    # Fractional ties prevent a constant baseline from benefiting from row order.
    fraction = (size - int(above.sum())) / int(tied.sum())
    return float((y[above].sum() + fraction * y[tied].sum()) / size)


def metrics(y, probabilities):
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    prevalence = float(y.mean())
    precision = top_quintile_precision(y, probabilities)
    both = len(set(y)) == 2
    return {"roc_auc": float(roc_auc_score(y, probabilities)) if both else None,
            "average_precision": float(average_precision_score(y, probabilities)) if both else None,
            "brier_score": float(brier_score_loss(y, probabilities)),
            "top_quintile_precision": precision,
            "top_quintile_lift": precision / prevalence if prevalence else None}


def train_benchmark(rows, target, excluded, cutoff=None, features=FEATURES, capture_estimators=False):
    import numpy as np
    import sklearn
    from sklearn.dummy import DummyClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    report = {"version": VERSION, "target": target, "created_at": datetime.now(timezone.utc).isoformat(),
              "sklearn_version": sklearn.__version__, "eligible_records": len(rows), "excluded": excluded,
              "success_probability": None, "status": "insufficient_evidence", "features": list(features),
              "label_definition": ("At least one recorded active same-cuisine restaurant in the tract" if target == "market_presence"
                                   else "Any inspection-archive reobservation at least 365 days after the first cycle inspection; absence is not closure" if target == "archive_reobservation"
                                   else "Verified operation 365-455 days after baseline versus verified permanent closure within 365 days"),
              "limitations": ["Not profitability or business success.", "Observational associations are not causal effects."]}
    if len(rows) < 100 or len({row["group"] for row in rows}) < 8:
        report["reason"] = "At least 100 labeled records and eight neighborhoods are required."
        return (report, {}) if capture_estimators else report
    train, test = holdout_indices(rows, cutoff)
    report["split"] = {"seed": 440, "method": "neighborhood_holdout" if cutoff is None else "temporal_and_neighborhood_holdout",
                       "cutoff": cutoff.isoformat() if cutoff else None,
                       "train_records": len(train), "test_records": len(test),
                       "train_neighborhoods": len({rows[i]["group"] for i in train}),
                       "test_neighborhoods": len({rows[i]["group"] for i in test}),
                       "neighborhood_overlap": len({rows[i]["group"] for i in train} & {rows[i]["group"] for i in test})}
    x = np.array([row["x"] for row in rows], dtype=float)
    y = np.array([row["y"] for row in rows], dtype=int)
    if len(train) < 60 or len(test) < 30 or any(int((y[index] == label).sum()) < 10 for index in (train, test) for label in (0, 1)):
        report["reason"] = "The fixed split needs at least 60 training rows, 30 test rows and ten examples of each outcome per partition."
        return (report, {}) if capture_estimators else report
    report["train_prevalence"] = float(y[train].mean())
    report["test_prevalence"] = float(y[test].mean())
    report["prevalence_shift"] = {"absolute_difference": abs(report["train_prevalence"] - report["test_prevalence"]),
                                  "review_required": abs(report["train_prevalence"] - report["test_prevalence"]) > .1}
    report["status"] = "evaluated"
    configurations = {"prevalence_baseline": [], "walkability_only": [features.index("national_walkability_index")],
                      "demand_only": [features.index("population_density_per_sq_mile"),
                                      features.index("job_density_per_sq_mile")],
                      "location_model": list(range(len(features)))}
    configurations.update({f"without_{feature}": [index for index in range(len(features)) if index != removed]
                           for removed, feature in enumerate(features)})
    predictions, models = {}, {}
    full_estimator = None
    fitted_estimators = {}
    for name, columns in configurations.items():
        if not columns:
            model = DummyClassifier(strategy="prior").fit(x[train], y[train])
            probabilities = model.predict_proba(x[test])[:, 1]
        else:
            model = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True, add_indicator=True), StandardScaler(),
                                  LogisticRegression(C=1.0, max_iter=2000, random_state=440))
            model.fit(x[train][:, columns], y[train])
            probabilities = model.predict_proba(x[test][:, columns])[:, 1]
        predictions[name] = probabilities
        models[name] = metrics(y[test], probabilities)
        if name == "location_model":
            full_estimator = model
            if capture_estimators:
                fitted_estimators["location_model"] = model
    if target in {"continued_operation", "archive_reobservation"}:
        from sklearn.ensemble import HistGradientBoostingClassifier
        booster = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True, add_indicator=True),
                                HistGradientBoostingClassifier(learning_rate=.05, max_iter=100,
                                                               max_leaf_nodes=7, min_samples_leaf=10,
                                                               l2_regularization=1.0, early_stopping=False,
                                                               random_state=440))
        booster.fit(x[train], y[train])
        if capture_estimators:
            fitted_estimators["hist_gradient_boosting"] = booster
        predictions["hist_gradient_boosting"] = booster.predict_proba(x[test])[:, 1]
        models["hist_gradient_boosting"] = metrics(y[test], predictions["hist_gradient_boosting"])
        report["gradient_boosting_parameters"] = {"estimator": "HistGradientBoostingClassifier",
                                                  "learning_rate": .05, "max_iter": 100,
                                                  "max_leaf_nodes": 7, "min_samples_leaf": 10,
                                                  "l2_regularization": 1.0, "early_stopping": False,
                                                  "random_state": 440,
                                                  "transform": "log1p, training-median imputation and training-fitted missingness indicators"}
    report["metrics"] = models
    full_metrics = models["location_model"]
    report["feature_ablation"] = [
        {"omitted_feature": feature,
         "brier_increase_without_feature": round(models[f"without_{feature}"]["brier_score"] - full_metrics["brier_score"], 6),
         "average_precision_drop_without_feature": round((full_metrics["average_precision"] or 0) -
                                                          (models[f"without_{feature}"]["average_precision"] or 0), 6)}
        for feature in features]
    report["feature_ablation_note"] = "Single fixed holdout; correlated inputs and sampling variation can reverse signs. Ablations do not establish causality or validate the dashboard Ground Score."
    model = full_estimator
    report["model_parameters"] = {
        "estimator": "L2 Logistic Regression", "C": 1.0,
        "transform": "log1p, training-median imputation, training-fitted missingness indicators, training standardization",
        "features": list(features),
        "missingness_indicator_features": [features[int(i)] for i in model.steps[0][1].indicator_.features_],
        "imputer_medians": model.steps[0][1].statistics_.tolist(),
        "scaler_mean": model.steps[1][1].mean_.tolist(),
        "scaler_scale": model.steps[1][1].scale_.tolist(),
        "coefficients": model.steps[2][1].coef_[0].tolist(),
        "intercept": float(model.steps[2][1].intercept_[0]),
    }
    full = predictions["location_model"]
    calibration = {}
    for model_name in ("location_model", "hist_gradient_boosting"):
        if model_name not in predictions:
            continue
        values = predictions[model_name]
        calibration[model_name] = []
        for lo, hi in zip([0, .2, .4, .6, .8], [.2, .4, .6, .8, 1.000001]):
            mask = (values >= lo) & (values < hi)
            if mask.any():
                calibration[model_name].append({"count": int(mask.sum()),
                    "mean_prediction": float(values[mask].mean()), "observed_rate": float(y[test][mask].mean())})
    report["calibration_bins"] = calibration if target in {"continued_operation", "archive_reobservation"} else calibration["location_model"]
    report["borough_metrics"] = {}
    boroughs = np.array([rows[i]["borough"] for i in test])
    for borough in sorted(set(boroughs)):
        mask = boroughs == borough
        report["borough_metrics"][borough] = {"count": int(mask.sum()),
                                               "small_sample": min(int(y[test][mask].sum()), int((1 - y[test][mask]).sum())) < 10,
                                               **metrics(y[test][mask], full[mask])}
        if "hist_gradient_boosting" in predictions:
            report["borough_metrics"][borough]["hist_gradient_boosting"] = metrics(
                y[test][mask], predictions["hist_gradient_boosting"][mask])
    groups = np.array([rows[i]["group"] for i in test])
    unique = np.unique(groups)
    rng = np.random.default_rng(440)
    differences = []
    for _ in range(200):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(groups == group) for group in sampled])
        if len(set(y[test][indices])) < 2:
            continue
        differences.append(float(np.mean((y[test][indices] - predictions["prevalence_baseline"][indices]) ** 2 - (y[test][indices] - full[indices]) ** 2)))
    interval = np.quantile(differences, [.025, .975]).tolist() if differences else None
    report["brier_improvement_vs_prevalence_95_interval"] = interval
    report["bootstrap"] = {"unit": "neighborhood", "requested_resamples": 200, "valid_resamples": len(differences)}
    report["conclusion"] = "Evidence of improvement over the prevalence baseline on this holdout." if interval and interval[0] > 0 else "No clear improvement over the prevalence baseline on this holdout."
    report["deployment_status"] = "research_only"
    if target == "archive_reobservation":
        report["deployment_status"] = "not_deployable_not_business_survival"
        report["limitations"] += ["A missing later archive record is not a permanent closure.",
                                  "A later record does not establish continuous operation or operation exactly at one year.",
                                  "The archived snapshots are incomplete and third-party consolidated; inclusion is selection-biased.",
                                  "This is a retrospective pipeline test, not a validated survival model or commercial recommendation."]
    elif target == "market_presence":
        report["limitations"] += ["Current active restaurants create survivor and inventory-selection bias.",
                                  "A negative means no recorded same-cuisine restaurant, not a failed restaurant.",
                                  "This is a spatial snapshot test, not a historical forecast or a test of the dashboard score.",
                                  "Sparse-inventory areas are excluded; results do not generalize to every NYC tract.",
                                  "No measured price, service quality, visits or business outcomes are available."]
    else:
        report["limitations"] += ["Continued operation is not profitability.", "Unresolved outcomes are censored, not counted as failures.",
                                  "Verification quality depends on supplied source evidence."]
    return (report, fitted_estimators) if capture_estimators else report


def run_evaluation(package, data_dir, cuisine="korean", target="market_presence", cutoff=None,
                   feature_set="full", validation_mode="temporal_spatial"):
    data_dir = Path(data_dir)
    if target == "market_presence":
        rows, excluded = presence_cohort(package, cuisine)
        report = train_benchmark(rows, target, excluded)
        report["cuisine"] = cuisine
        release = data_dir.parent / package["data_path"]
        source_paths = [release / filename for filename in ("master_tract_features.csv", "entities/current_restaurants.csv")]
        name = f"market_presence_{cuisine}"
    elif target == "continued_operation":
        if feature_set not in {"full", "historical_core"}:
            raise ValueError("Unknown historical feature set.")
        if validation_mode not in {"temporal_spatial", "spatial_exploratory"}:
            raise ValueError("Unknown survival validation mode.")
        if validation_mode == "spatial_exploratory" and cutoff:
            raise ValueError("The spatial exploratory mode does not use a temporal cutoff.")
        features = FEATURES if feature_set == "full" else HISTORICAL_CORE_FEATURES
        filename = "business_outcomes.csv" if feature_set == "full" else "business_outcomes_core.csv"
        outcomes = data_dir / "evaluation" / filename
        if not outcomes.exists():
            return {"version": VERSION, "target": target, "status": "needs_verified_outcomes", "success_probability": None,
                    "reason": f"Add independently verified operating/closure outcomes to data/evaluation/{filename}.",
                    "feature_set": feature_set, "validation_mode": validation_mode,
                    "required_columns": list(OUTCOME_METADATA + features)}
        if validation_mode == "temporal_spatial" and not cutoff:
            raise ValueError("A training cutoff date is required for continued-operation evaluation.")
        rows, excluded, cutoff_date = outcome_cohort(outcomes, cutoff or date.today().isoformat(),
                                                      features=features)
        report = train_benchmark(rows, target, excluded,
                                 cutoff_date if validation_mode == "temporal_spatial" else None,
                                 features=features)
        report["feature_set"] = feature_set
        report["validation_mode"] = validation_mode
        if validation_mode == "spatial_exploratory":
            report["limitations"].append("Neighborhood-only holdout: no prospective temporal generalization tested; probabilities are not deployment-calibrated.")
        source_paths = [outcomes]
        name = f"continued_operation_{feature_set}_{validation_mode}"
    else:
        raise ValueError("Unknown evaluation target.")
    report["source_fingerprints"] = {str(path.relative_to(data_dir)): fingerprint(path) for path in source_paths}
    directory = data_dir / "evaluation/reports"
    directory.mkdir(parents=True, exist_ok=True)
    # Unique reports preserve prior experiments; no dataset is overwritten.
    destination = directory / f"{name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    report["report_file"] = str(destination.relative_to(data_dir))
    return report


def evaluation_status(data_dir):
    directory = Path(data_dir) / "evaluation"
    permit_status_path = directory / "permit_presence/status.json"
    permit_status = None
    if permit_status_path.is_file():
        try:
            permit_status = json.loads(permit_status_path.read_text(encoding="utf-8"))
            permit_status = {key: permit_status.get(key) for key in
                             ("status", "target", "first_record_date", "latest_record_date",
                              "distinct_snapshot_dates", "review_leads", "one_year_training_ready")}
        except (OSError, ValueError):
            permit_status = {"status": "invalid_status_file", "one_year_training_ready": False}
    files = sorted((directory / "reports").glob("*.json")) if (directory / "reports").exists() else []
    historical = {"verified_features": [], "candidate_features": [], "missing_features": list(FEATURES),
                  "inputs_present_for_outcome_cohort": False}
    manifest = directory / "snapshots/2023-04-v0/historical_core_snapshots.json"
    if not manifest.is_file():
        manifest = directory / "snapshots/2023-12-v1/historical_core_snapshots.json"
    if not manifest.exists():
        manifest = directory / "snapshots/2024-12-v2/partial_historical_snapshots.json"
    if manifest.exists():
        try:
            from prepare_historical_cohort import read_snapshots
            snapshots = read_snapshots(manifest, data_dir)
            historical["verified_features"] = [feature for feature in FEATURES if snapshots[feature]]
            historical["missing_features"] = [feature for feature in FEATURES if not snapshots[feature]]
        except (OSError, ValueError, KeyError) as error:
            historical["snapshot_error"] = str(error)
    candidate = directory / "candidates/mta_week_2023-12-01/candidate_manifest.json"
    if candidate.exists():
        try:
            metadata = json.loads(candidate.read_text())
            if not isinstance(metadata, dict):
                raise ValueError("Historical subway candidate metadata must be an object.")
            candidate_path = (Path(data_dir).resolve().parent / metadata.get("tract_features", "")).resolve()
            if (metadata.get("status") == "candidate_not_as_of_verified" and metadata.get("training_eligible") is False
                    and candidate_path.is_relative_to(Path(data_dir).resolve()) and candidate_path.is_file()
                    and fingerprint(candidate_path) == metadata.get("tract_features_sha256")):
                historical["candidate_features"] = ["nearest_subway_distance_miles", "nearest_subway_weekly_ridership"]
            else:
                historical["candidate_error"] = "Historical subway candidate is missing or its fingerprint does not match."
        except (OSError, ValueError):
            historical["candidate_error"] = "Historical subway candidate metadata could not be read."
    outcome_present = (directory / "business_outcomes.csv").exists()
    core_outcome_present = (directory / "business_outcomes_core.csv").exists()
    historical["inputs_present_for_outcome_cohort"] = not historical["missing_features"] and outcome_present
    historical["historical_core_features_ready"] = all(feature in historical["verified_features"]
                                                      for feature in HISTORICAL_CORE_FEATURES)
    historical["historical_core_outcomes_present"] = core_outcome_present
    historical["historical_core_training_inputs_present"] = (historical["historical_core_features_ready"]
                                                              and core_outcome_present)
    historical["snapshot_manifest"] = str(manifest.relative_to(data_dir)) if manifest.exists() else None
    return {"version": VERSION, "success_probability": None, "customer_dashboard_unchanged": True,
            "available_targets": ["market_presence", "continued_operation"],
            "permit_presence_tracking": permit_status,
            "verified_outcome_file_present": outcome_present,
            "historical_readiness": historical,
            "reports": [str(path.relative_to(data_dir)) for path in files],
            "note": "Presence is a research proxy; verified outcomes are required to evaluate continued operation."}
