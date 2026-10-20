from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

import numpy as np


class SurvivalModel:
    """Trusted XGBoost JSON/UBJ artifact only; native TreeSHAP computed offline."""

    def __init__(self, artifact, manifest):
        self.metadata = json.loads(Path(manifest).read_text())
        required = {
            "version",
            "features",
            "horizon_months",
            "positive_class",
            "artifact_sha256",
            "training_cutoff",
            "resolution",
            "prediction_unit",
            "validation",
        }
        if not required <= self.metadata.keys():
            raise ValueError(f"Model manifest is missing {sorted(required - self.metadata.keys())}.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.metadata["version"]):
            raise ValueError("Invalid model version.")
        if self.metadata["positive_class"] != "survived":
            raise ValueError("Positive class must represent survived, not closed.")
        if not isinstance(self.metadata["horizon_months"], int) or self.metadata["horizon_months"] <= 0:
            raise ValueError("A positive survival horizon is required.")
        if self.metadata["resolution"] not in {7, 8, 9} or self.metadata["prediction_unit"] != "hex_location":
            raise ValueError("Model must declare an H3 resolution and hex_location prediction unit.")
        self.features = self.metadata["features"]
        if (
            not self.features
            or len(set(self.features)) != len(self.features)
            or not all(isinstance(x, str) for x in self.features)
        ):
            raise ValueError("Feature names must be nonempty and unique.")
        path = Path(artifact)
        if path.suffix not in {".json", ".ubj"}:
            raise ValueError("Use XGBoost JSON/UBJ, never pickle.")
        if sha256(path.read_bytes()).hexdigest() != self.metadata["artifact_sha256"]:
            raise ValueError("Model checksum does not match manifest.")
        import xgboost as xgb

        self.xgb = xgb
        self.booster = xgb.Booster()
        self.booster.load_model(path)
        config = json.loads(self.booster.save_config())
        if config["learner"]["objective"]["name"] != "binary:logistic":
            raise ValueError("Survival model must use binary:logistic.")
        if self.booster.feature_names != self.features:
            raise ValueError("Artifact feature order must exactly match manifest.")
        self.booster.set_param({"nthread": 2})

    def predict_batch(self, rows):
        # Reject missing data instead of silently inventing feature values.
        values = []
        for row in rows:
            if any(
                name not in row or row[name] is None or isinstance(row[name], bool) for name in self.features
            ):
                raise ValueError("Missing required model feature.")
            vector = [float(row[name]) for name in self.features]
            if not np.isfinite(vector).all():
                raise ValueError("Model features must be finite.")
            values.append(vector)
        matrix = self.xgb.DMatrix(np.asarray(values, dtype=np.float32), feature_names=self.features)
        probabilities = self.booster.predict(matrix)
        contributions = self.booster.predict(matrix, pred_contribs=True)
        margins = self.booster.predict(matrix, output_margin=True)
        if not np.allclose(contributions.sum(axis=1), margins, atol=1e-4):
            raise ValueError("SHAP contributions do not reconstruct model margin.")
        return [
            {
                "survival_probability": float(probability),
                "horizon_months": self.metadata["horizon_months"],
                "model_version": self.metadata["version"],
                "explanation_scale": "log_odds",
                "base_value": float(shap[-1]),
                "shap_values": dict(zip(self.features, map(float, shap[:-1]))),
                "features": dict(zip(self.features, vector)),
                "assessment_type": "Model estimate; see validation metadata",
            }
            for probability, shap, vector in zip(probabilities, contributions, values)
        ]
