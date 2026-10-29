"""Optional, checked inference for the opening-date AFT model.

Loads trusted native model files only. Never trains during a dashboard request,
loads pickle, or substitutes an archive-reobservation model for restaurant exit.
"""
from datetime import date
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
            "tract_scores": resolve(os.environ.get("GROUNDWORK_ATHARV_SCORES") or config["tract_scores"]) if os.environ.get("GROUNDWORK_ATHARV_SCORES") or config.get("tract_scores") else None,
            "cuisine_scores": resolve(config.get("cuisine_scores", "data/output/atharv_model/hex_cuisine_scores.csv"))}


class TemporalSurvivalInference:
    def __init__(self, model_dir, manifests, data_dir, prediction_date):
        import xgboost as xgb
        from survival_features import HISTORICAL_FEATURES, load_historical_snapshots
        from survival_features import validate_temporal_model
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
        from survival_features import HISTORICAL_FEATURES, build_historical_features
        from survival_features import survival_prob
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
        if config["tract_scores"] is not None:
            from atharv_export import export_state
            return export_state(config["tract_scores"])
        required = [config["model_dir"] / name for name in ("survival_model.json", "model_meta.json", "audit.json")]
        if any(not p.is_file() for p in required):
            return None, {"status": "awaiting_artifact", "label": "Survival model awaiting trained artifact",
                          "message": "A compatible audited historical-AFT bundle and dated snapshots have not been supplied.",
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


def attach_predictions(locations, config_path=DEFAULT_CONFIG):
    """Attach estimates by GEOID without changing screening scores or ranking."""
    engine, status = model_state(config_path)
    predictions = {}
    if engine is not None:
        try:
            predictions = engine.predict(locations)
        except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
            status = {**status, "status": "inference_unavailable", "label": "Survival inference unavailable", "message": str(error)}
    for row in locations:
        row["survival"] = predictions.get(str(row["geoid"]), {
            "status": "missing_historical_features" if status["status"] == "available" else status["status"],
            "probability": None,
        })
    return status
