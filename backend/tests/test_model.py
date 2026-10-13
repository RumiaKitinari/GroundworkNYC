import json

import numpy as np
import pytest

from groundwork_backend.model import SurvivalModel


def test_probabilities_and_native_shap_reconstruct_log_odds(artifact):
    path, manifest, _ = artifact
    model = SurvivalModel(path, manifest)
    results = model.predict_batch([{"residents": -1, "workers": 0}, {"residents": 1, "workers": 0}])
    assert results[0]["survival_probability"] < results[1]["survival_probability"]
    for row in results:
        margin = row["base_value"] + sum(row["shap_values"].values())
        assert 1 / (1 + np.exp(-margin)) == pytest.approx(row["survival_probability"], abs=1e-6)
        assert row["horizon_months"] == 24


def test_missing_features_rejected(artifact):
    model = SurvivalModel(artifact[0], artifact[1])
    with pytest.raises(ValueError):
        model.predict_batch([{"residents": 1}])
    with pytest.raises(ValueError):
        model.predict_batch([{"residents": 1, "workers": float("nan")}])


@pytest.mark.parametrize(
    "change",
    [{"positive_class": "closed"}, {"artifact_sha256": "wrong"}, {"features": ["workers", "residents"]}],
)
def test_invalid_manifest_is_rejected(artifact, change):
    path, manifest, metadata = artifact
    manifest.write_text(json.dumps({**metadata, **change}))
    with pytest.raises(ValueError):
        SurvivalModel(path, manifest)
