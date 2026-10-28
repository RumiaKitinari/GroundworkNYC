"""Optional, checked inference for the opening-date AFT model.

Loads trusted native model files only. Never trains during a dashboard request,
loads pickle, or substitutes an archive-reobservation model for restaurant exit.
"""
from datetime import date
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
from evidence_policy import THRESHOLDS

ROOT = Path(__file__).resolve().parents[1]
CODES = str(ROOT / "codes")
if CODES not in sys.path:
    sys.path.append(CODES)

DEFAULT_CONFIG = ROOT / "data/output/atharv_model/dashboard_model.json"
DEFAULT_MODEL = ROOT / "data/output/atharv_model/model"
DEFAULT_MANIFESTS = [ROOT / "data/evaluation/snapshots" / p for p in (
    "2023-04-v0/historical_core_snapshots.json",
    "2023-12-v1/historical_core_snapshots.json",
    "2024-12-v2/partial_historical_snapshots.json",
)]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def options(config_path=DEFAULT_CONFIG):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    def resolve(value):
        path = Path(value).expanduser()
        return path if path.is_absolute() else ROOT / path
    return {"model_dir": resolve(config.get("model_dir", str(DEFAULT_MODEL))),
            "data_dir": resolve(config.get("data_dir", str(ROOT / "data"))),
            "manifests": [resolve(p) for p in config.get("snapshots", list(map(str, DEFAULT_MANIFESTS)))],
            "cuisine_scores": resolve(config.get("cuisine_scores", "data/output/atharv_model/hex_cuisine_scores.csv"))}


class TemporalSurvivalInference:
    def __init__(self, model_dir, manifests, data_dir, prediction_date):
        import xgboost as xgb
        from features import HISTORICAL_FEATURES, load_historical_snapshots
        from recommend import validate_temporal_model
        self.model_dir = Path(model_dir)
        self.metadata = json.loads((self.model_dir / "model_meta.json").read_text())
        validate_temporal_model(self.metadata, prediction_date)
        audit = json.loads((self.model_dir / "audit.json").read_text())
        if (audit.get("status") != "research_model_trained" or audit.get("training_performed") is not True
                or not any(f.get("status") == "evaluated" for f in audit.get("folds", []))):
            raise ValueError("Model needs a completed temporal/spatial training audit")
        artifact = self.model_dir / "survival_model.json"
        if audit.get("artifact_sha256", {}).get(artifact.name) != digest(artifact):
            raise ValueError("Survival artifact checksum does not match the training audit")
        if (audit.get("features") != self.metadata["features"]
                or audit.get("as_of") != self.metadata["trained_as_of"]
                or audit.get("eligible_rows") != self.metadata["n_training_rows"]):
            raise ValueError("Model metadata disagrees with the training audit")
        self.booster = xgb.Booster()
        self.booster.load_model(artifact)
        native = json.loads(self.booster.save_config())["learner"]
        if native["objective"]["name"] != "survival:aft" or self.booster.feature_names != list(HISTORICAL_FEATURES):
            raise ValueError("Expected the historical AFT feature schema")
        distribution = native["objective"]["aft_loss_param"]
        if (distribution["aft_loss_distribution"] != "normal"
                or float(distribution["aft_loss_distribution_scale"]) != self.metadata["aft_scale"]
                or self.metadata["horizon_years"] != 3.0):
            raise ValueError("AFT distribution/horizon does not match model metadata")
        self.booster.set_param({"nthread": 1})
        self.snapshots = load_historical_snapshots(manifests, data_dir, prediction_date)
        self.prediction_date = prediction_date
        self.model_id = "historical-aft-" + digest(artifact)[:12]

    def predict(self, rows):
        import numpy as np
        import pandas as pd
        import xgboost as xgb
        from features import HISTORICAL_FEATURES, build_historical_features
        from train_survival import survival_prob
        if not rows:
            return {}
        baselines = pd.DataFrame([{"geoid": str(r["geoid"]), "open_date": self.prediction_date} for r in rows])
        features, provenance = build_historical_features(baselines, self.snapshots)
        usable = features.notna().any(axis=1)
        predictions = {}
        if not usable.any():
            return predictions
        matrix = xgb.DMatrix(features.loc[usable].to_numpy(dtype=float), feature_names=list(HISTORICAL_FEATURES))
        values = survival_prob(self.booster.predict(matrix), self.metadata["horizon_years"], self.metadata["aft_scale"])
        for index, value in zip(features.index[usable], values):
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Model produced an invalid survival probability")
            predictions[str(baselines.loc[index, "geoid"])] = {
                "status": "available", "probability": float(value), "horizon_years": 3,
                "model_version": self.model_id, "assessment_type": "Experimental survival estimate",
                "prediction_date": self.prediction_date, "trained_as_of": self.metadata["trained_as_of"],
                "feature_coverage": float(features.loc[index].notna().mean()),
                "features": {key: (float(features.loc[index, key]) if pd.notna(features.loc[index, key]) else None)
                             for key in HISTORICAL_FEATURES},
                "feature_transform": "log1p", "provenance": provenance[index * len(HISTORICAL_FEATURES):(index + 1) * len(HISTORICAL_FEATURES)],
            }
        return predictions


@lru_cache(maxsize=2)
def _load(model_dir, manifests, data_dir, prediction_date, signature):
    return TemporalSurvivalInference(model_dir, manifests, data_dir, prediction_date)


def model_state(config_path=DEFAULT_CONFIG, prediction_date=None):
    prediction_date = prediction_date or date.today().isoformat()
    try:
        config = options(config_path)
        required = [config["model_dir"] / name for name in ("survival_model.json", "model_meta.json", "audit.json")]
        if any(not p.is_file() for p in required):
            return None, {"status": "awaiting_artifact", "label": "Survival model awaiting trained artifact",
                          "message": "Dated baseline and outcome evidence are required to train the corrected model.",
                          "assessment_type": "Uncalibrated Screening Index", "ranking_mode": "screening"}
        paths = [*required, *config["manifests"]]
        for manifest in config["manifests"]:
            content = json.loads(manifest.read_text())
            paths.extend(config["data_dir"] / row["path"] for row in content["snapshots"])
        signature = tuple((str(p.resolve()), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        engine = _load(str(config["model_dir"].resolve()), tuple(map(str, config["manifests"])),
                       str(config["data_dir"].resolve()), prediction_date, signature)
        return engine, {"status": "available", "label": "Experimental survival model connected",
                        "model_version": engine.model_id, "horizon_years": 3,
                        "trained_as_of": engine.metadata["trained_as_of"], "prediction_date": prediction_date,
                        "assessment_type": "Experimental survival estimate", "ranking_mode": "screening",
                        "limitations": engine.metadata.get("limitations", [])}
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        return None, {"status": "invalid_artifact", "label": "Survival model unavailable",
                      "message": str(error), "ranking_mode": "screening",
                      "assessment_type": "Uncalibrated Screening Index"}


# Explicit UI-category mapping: broader labels are not silently equated to a
# single narrower cuisine in Atharv's 50-category heatmap.
CUISINE_LABELS = {
    "southern_soul": "Southern / Soul Food", "cajun_creole": "Cajun / Creole",
    "german_central": "German / Central European", "eastern_european": "Eastern European",
    "pakistani_bangladeshi": "Pakistani / Bangladeshi", "west_african": "West African",
    "indonesian_malaysian": "Indonesian / Malaysian", "middle_eastern": "Middle Eastern",
    "persian_iranian": "Persian / Iranian", "sandwiches_deli": "Sandwiches / Deli",
    "sandwiches": "Sandwiches / Deli", "bakery": "Bakery / Pastries", "bakery_pastries": "Bakery / Pastries",
    "coffee_tea": "Coffee / Tea", "desserts": "Desserts / Ice Cream", "desserts_ice_cream": "Desserts / Ice Cream",
    "salads": "Salads / Bowls", "salads_bowls": "Salads / Bowls", "breakfast_brunch": "Breakfast / Brunch",
    "health_focused": "Health-Focused",
}


@lru_cache(maxsize=2)
def _gap_table(path, signature):
    import csv
    import h3
    table = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"hex", "cuisine", "gap_score"} <= set(reader.fieldnames or []):
            raise ValueError("Cuisine scores need hex, cuisine, gap_score")
        for row in reader:
            key = row["hex"], row["cuisine"]
            value = float(row["gap_score"])
            if key in table or not h3.is_valid_cell(key[0]) or h3.get_resolution(key[0]) != 9 or not 0 <= value <= 1:
                raise ValueError("Invalid/duplicate H3 resolution-9 cuisine score")
            table[key] = value
    return table


def attach_model(locations, tracts, cuisine, config_path=DEFAULT_CONFIG):
    """Attach batch inference; blend only with available actual res-9 gap data.

    Existing screening components remain contextual diagnostics. Separate fields
    hold model-ranking components, so UI explanations cannot relabel heuristics
    as learned model contributions.
    """
    original_scores = [(row["opportunity"], row.get("model_version"), row.get("recommendation")) for row in locations]
    engine, status = model_state(config_path)
    if engine is None:
        for row in locations:
            row["survival"] = {"status": status["status"], "probability": None}
        return locations, status
    try:
        predictions = engine.predict(tracts)
        for row in locations:
            row["survival"] = predictions.get(row["geoid"], {"status": "missing_historical_features", "probability": None})
        # New policy-aware consumers can retain concept-specific general fit
        # without pretending a sparse cuisine surface is measured demand.
        policy_aware = bool(locations) and all("support" in row.get("concept_evidence", {}) for row in locations)
        if policy_aware and any(row["concept_evidence"]["support"]["mode"] != "cuisine_supply_supported" for row in locations):
            return general_model_ranking(locations, status, engine.model_id)
        config = options(config_path)
        path = config["cuisine_scores"]
        label = CUISINE_LABELS.get(cuisine, cuisine.replace("_", " ").title())
        if not path.is_file():
            if policy_aware:
                return general_model_ranking(locations, status, engine.model_id)
            status["ranking_message"] = "Survival estimates connected; cuisine-gap artifact is unavailable. Ranking uses screening."
            return locations, status
        table = _gap_table(str(path.resolve()), (path.stat().st_mtime_ns, path.stat().st_size))
        if not any(key[1] == label for key in table):
            if policy_aware:
                return general_model_ranking(locations, status, engine.model_id)
            status["ranking_message"] = "No matching cuisine-gap category. Ranking uses screening."
            return locations, status
        eligible = [row for row in locations if row["survival"]["status"] == "available"]
        if len(eligible) != len(locations) or not eligible:
            status["ranking_message"] = "Historical feature coverage is incomplete. Ranking uses screening."
            return locations, status
        import pandas as pd
        import h3
        percentiles = pd.Series([row["survival"]["probability"] for row in eligible]).rank(pct=True)
        for index, row in enumerate(eligible):
            cell = h3.latlng_to_cell(row["latitude"], row["longitude"], 9)
            # The experimental gap export omits all-zero cells. Missing entries
            # within this explicit cuisine surface therefore retain its zero rule.
            gap = table.get((cell, label), 0.0)
            row["screening_opportunity"] = row["opportunity"]
            row["opportunity"] = round(100 * (.6 * float(percentiles.iloc[index]) + .4 * gap), 2)
            row["model_version"] = engine.model_id
            row["ranking_components"] = {"survival_percentile": float(percentiles.iloc[index]),
                                          "cuisine_gap": gap, "weights": {"survival": .6, "cuisine_gap": .4},
                                          "h3_resolution": 9, "cuisine": label}
            row["recommendation"] = "Compare the experimental survival estimate and cuisine gap; confirm property suitability."
        status.update(ranking_mode="survival_cuisine_gap", assessment_type="Experimental survival/cuisine-gap ranking",
                      ranking_scope="Eligible tract screening points in the selected borough filter; not property-level ranks")
        return sorted(locations, key=lambda row: row["opportunity"], reverse=True), status
    except (OSError, ValueError, KeyError, ImportError) as error:
        for row, (score, version, recommendation) in zip(locations, original_scores):
            row.update(opportunity=score, model_version=version, recommendation=recommendation)
            row.pop("ranking_components", None)
            row.pop("screening_opportunity", None)
            row.setdefault("survival", {"status": "inference_unavailable", "probability": None})
        status.update(status="inference_unavailable", label="Survival ranking unavailable", message=str(error), ranking_mode="screening")
        return locations, status


def general_model_ranking(locations, status, model_id):
    """Explicit research blend, never a cuisine demand or success probability.

    The general-fit part retains price/format/audience/daypart effects. Missing
    predictions or poor feature coverage keep the whole batch on screening,
    rather than comparing two different score definitions in one ranking.
    """
    import math
    import pandas as pd
    def supported(row):
        prediction = row.get("survival",{})
        probability,coverage = prediction.get("probability"),prediction.get("feature_coverage")
        numeric = lambda value: isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
        return (prediction.get("status")=="available" and numeric(probability) and 0<=probability<=1
                and numeric(coverage) and THRESHOLDS["minimum_model_feature_coverage"]<=coverage<=1
                and numeric(row.get("opportunity")) and 0<=row["opportunity"]<=100
                and row.get("assessment_policy",{}).get("recommendation_eligible",False))
    if not locations or not all(supported(row) for row in locations):
        status["ranking_message"] = "General screening retained; model or location evidence is incomplete."
        return locations,status
    percentiles = pd.Series([row["survival"]["probability"] for row in locations]).rank(pct=True)
    for index,row in enumerate(locations):
        original = row["opportunity"]
        row["screening_opportunity"] = original
        row["opportunity"] = round(.6*100*float(percentiles.iloc[index])+.4*original,2)
        row["model_version"] = model_id
        row["ranking_components"] = {"survival_percentile":float(percentiles.iloc[index]),
            "general_fit_index":original,"cuisine_gap":None,"weights":{"survival":.6,"general_fit":.4},
            "weights_calibrated":False,"fallback_reason":"Cuisine surface unsupported or unavailable"}
        row["recommendation"] = "General Location Fit; Cuisine-Specific Demand Requires Review."
    status.update(ranking_mode="survival_general_fit",assessment_type="Experimental survival/general-fit ranking",
                  ranking_weights={"survival":.6,"general_fit":.4},
                  ranking_method="60% Survival Percentile + 40% Concept-Specific General Fit",
                  ranking_scope="One consistent fallback basis for the entire eligible cohort; not a success probability")
    return sorted(locations,key=lambda row:row["opportunity"],reverse=True),status
