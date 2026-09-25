"""Offline evaluation; none of these probabilities are customer-facing success scores."""

import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from math import log1p
from pathlib import Path

from scoring import CUISINES, number


VERSION = "evaluation-0.1"
FEATURES = (
    "population_density_per_sq_mile", "median_household_income",
    "job_density_per_sq_mile", "national_walkability_index",
    "nearest_subway_distance_miles", "nearest_subway_weekly_ridership",
    "retail_area_sqft", "mixed_use_parcel_count",
)
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


def feature_vector(row):
    return [log1p(value) if (value := number(row.get(key, row.get("median_household_income_2024") if key == "median_household_income" else None))) is not None else float("nan") for key in FEATURES]


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


def outcome_cohort(path, cutoff, today=None):
    """Reject leakage and ambiguous negatives; unresolved records stay censored."""
    today = today or date.today()
    cutoff = date.fromisoformat(cutoff)
    if cutoff > today:
        raise ValueError("The training cutoff cannot be in the future.")
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = set(OUTCOME_METADATA + FEATURES) - set(reader.fieldnames or [])
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
        rows.append({"id": business_id, "group": row["nta_code"], "borough": row.get("borough", "Unknown"),
                     "x": feature_vector(row), "y": int(positive), "as_of": start, "recorded": recorded})
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


def train_benchmark(rows, target, excluded, cutoff=None):
    import numpy as np
    import sklearn
    from sklearn.dummy import DummyClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    report = {"version": VERSION, "target": target, "created_at": datetime.now(timezone.utc).isoformat(),
              "sklearn_version": sklearn.__version__, "eligible_records": len(rows), "excluded": excluded,
              "success_probability": None, "status": "insufficient_evidence", "features": list(FEATURES),
              "label_definition": "At least one recorded active same-cuisine restaurant in the tract" if target == "market_presence" else "Verified operation 365-455 days after baseline versus verified permanent closure within 365 days",
              "limitations": ["Not profitability or business success.", "Observational associations are not causal effects."]}
    if len(rows) < 100 or len({row["group"] for row in rows}) < 8:
        report["reason"] = "At least 100 labeled records and eight neighborhoods are required."
        return report
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
        return report
    report["train_prevalence"] = float(y[train].mean())
    report["test_prevalence"] = float(y[test].mean())
    report["prevalence_shift"] = {"absolute_difference": abs(report["train_prevalence"] - report["test_prevalence"]),
                                  "review_required": abs(report["train_prevalence"] - report["test_prevalence"]) > .1}
    report["status"] = "evaluated"
    configurations = {"prevalence_baseline": [], "walkability_only": [3], "demand_only": [0, 2], "location_model": list(range(len(FEATURES)))}
    predictions, models = {}, {}
    for name, columns in configurations.items():
        if not columns:
            model = DummyClassifier(strategy="prior").fit(x[train], y[train])
            probabilities = model.predict_proba(x[test])[:, 1]
        else:
            model = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(),
                                  LogisticRegression(C=1.0, max_iter=2000, random_state=440))
            model.fit(x[train][:, columns], y[train])
            probabilities = model.predict_proba(x[test][:, columns])[:, 1]
        predictions[name] = probabilities
        models[name] = metrics(y[test], probabilities)
    report["metrics"] = models
    report["model_parameters"] = {
        "estimator": "L2 Logistic Regression", "C": 1.0,
        "transform": "log1p, training-median imputation, training standardization",
        "features": list(FEATURES),
        "imputer_medians": model.steps[0][1].statistics_.tolist(),
        "scaler_mean": model.steps[1][1].mean_.tolist(),
        "scaler_scale": model.steps[1][1].scale_.tolist(),
        "coefficients": model.steps[2][1].coef_[0].tolist(),
        "intercept": float(model.steps[2][1].intercept_[0]),
    }
    full = predictions["location_model"]
    report["calibration_bins"] = []
    for lo, hi in zip([0, .2, .4, .6, .8], [.2, .4, .6, .8, 1.000001]):
        mask = (full >= lo) & (full < hi)
        if mask.any():
            report["calibration_bins"].append({"count": int(mask.sum()), "mean_prediction": float(full[mask].mean()), "observed_rate": float(y[test][mask].mean())})
    report["borough_metrics"] = {}
    boroughs = np.array([rows[i]["borough"] for i in test])
    for borough in sorted(set(boroughs)):
        mask = boroughs == borough
        report["borough_metrics"][borough] = {"count": int(mask.sum()),
                                               "small_sample": min(int(y[test][mask].sum()), int((1 - y[test][mask]).sum())) < 10,
                                               **metrics(y[test][mask], full[mask])}
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
    if target == "market_presence":
        report["limitations"] += ["Current active restaurants create survivor and inventory-selection bias.",
                                  "A negative means no recorded same-cuisine restaurant, not a failed restaurant.",
                                  "This is a spatial snapshot test, not a historical forecast or a test of the dashboard score.",
                                  "Sparse-inventory areas are excluded; results do not generalize to every NYC tract.",
                                  "No measured price, service quality, visits or business outcomes are available."]
    else:
        report["limitations"] += ["Continued operation is not profitability.", "Unresolved outcomes are censored, not counted as failures.",
                                  "Verification quality depends on supplied source evidence."]
    return report


def run_evaluation(package, data_dir, cuisine="korean", target="market_presence", cutoff=None):
    data_dir = Path(data_dir)
    if target == "market_presence":
        rows, excluded = presence_cohort(package, cuisine)
        report = train_benchmark(rows, target, excluded)
        report["cuisine"] = cuisine
        source_paths = [data_dir / "integrated/restaurant_bar_location_data_ready" / filename for filename in ("master_tract_features.csv", "entities/current_restaurants.csv")]
        name = f"market_presence_{cuisine}"
    elif target == "continued_operation":
        outcomes = data_dir / "evaluation/business_outcomes.csv"
        if not outcomes.exists():
            return {"version": VERSION, "target": target, "status": "needs_verified_outcomes", "success_probability": None,
                    "reason": "Add historical baseline features and verified operating/closure outcomes to data/evaluation/business_outcomes.csv.",
                    "required_columns": list(OUTCOME_METADATA + FEATURES)}
        if not cutoff:
            raise ValueError("A training cutoff date is required for continued-operation evaluation.")
        rows, excluded, cutoff_date = outcome_cohort(outcomes, cutoff)
        report = train_benchmark(rows, target, excluded, cutoff_date)
        source_paths = [outcomes]
        name = "continued_operation"
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
    files = sorted((directory / "reports").glob("*.json")) if (directory / "reports").exists() else []
    return {"version": VERSION, "success_probability": None, "customer_dashboard_unchanged": True,
            "available_targets": ["market_presence", "continued_operation"],
            "verified_outcome_file_present": (directory / "business_outcomes.csv").exists(),
            "reports": [str(path.relative_to(data_dir)) for path in files],
            "note": "Presence is a research proxy; verified outcomes are required to evaluate continued operation."}
