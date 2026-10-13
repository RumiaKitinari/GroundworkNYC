import json
from hashlib import sha256

import numpy as np
import pytest


@pytest.fixture
def artifact(tmp_path):
    import xgboost as xgb

    rng = np.random.default_rng(42)
    values = rng.normal(size=(100, 2)).astype(np.float32)
    data = xgb.DMatrix(values, label=(values[:, 0] > 0).astype(int), feature_names=["residents", "workers"])
    booster = xgb.train({"objective": "binary:logistic", "max_depth": 2, "nthread": 1, "seed": 42}, data, 4)
    path = tmp_path / "test.json"
    booster.save_model(path)
    metadata = {
        "version": "test_v1",
        "features": ["residents", "workers"],
        "positive_class": "survived",
        "resolution": 8,
        "prediction_unit": "hex_location",
        "horizon_months": 24,
        "artifact_sha256": sha256(path.read_bytes()).hexdigest(),
        "training_cutoff": "2024-01-01",
        "validation": {"status": "synthetic test only"},
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(metadata))
    return path, manifest, metadata
