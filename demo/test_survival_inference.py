"""HTTP integration with a real AFT fixture; never deploys synthetic models."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import h3
import pandas as pd

import app
from connect_survival_model import connect
from survival_inference import TemporalSurvivalInference, attach_model, model_state


class SurvivalDashboardTests(unittest.TestCase):
    def setUp(self):
        # Reuse the explicit synthetic evidence fixture; its lifecycle is confined
        # to a temporary directory and it is never the dashboard's active config.
        from test_temporal_survival import TemporalSurvivalTests
        from train_survival import run
        self.fixture = TemporalSurvivalTests(methodName="test_same_day_release_allowed")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        baseline, observation = self.fixture.make_population()
        bp, op = self.root / "baselines.csv", self.root / "observations.csv"
        baseline.to_csv(bp, index=False)
        observation.to_csv(op, index=False)
        self.model = self.root / "model"
        run(bp, op, [self.fixture.manifest], self.root, self.model, "2026-01-01", "2024-01-01", rounds=3)
        self.config = self.root / "dashboard_model.json"
        self.gaps = self.root / "gaps.csv"
        cell = h3.latlng_to_cell(40.7, -74.0, 9)
        pd.DataFrame([{"hex": cell, "cuisine": "Indian", "gap_score": .75}]).to_csv(self.gaps, index=False)
        connect(self.model, [self.fixture.manifest], self.root, self.gaps, self.config)

    def locations(self):
        return [{"geoid": "36061000100", "latitude": 40.7, "longitude": -74., "opportunity": 23,
                 "model_version": "screening", "score_components": []}]

    def test_native_aft_inference_and_provenance_reaches_http_dashboard(self):
        # Use the actual integrated package for the rest of the dashboard response;
        # the synthetic model only runs inside this scoped, patched HTTP test.
        package = dict(app.integrated_package())
        tract = dict(package["tracts"][0], geoid="36061000100", borough="Manhattan")
        package["tracts"] = [tract]
        with patch.dict(app.app.config, {"SURVIVAL_CONFIG": str(self.config)}), \
                patch.object(app, "integrated_package", return_value=package), app.app.test_client() as client:
            status = client.get("/api/models/survival")
            self.assertEqual(status.json["status"], "available")
            response = client.get("/api/dashboard?cuisine=indian&borough=Manhattan")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["survival_model"]["status"], "available")
        prediction = next(row["survival"] for row in response.json["locations"] if row["survival"]["status"] == "available")
        self.assertTrue(0 <= prediction["probability"] <= 1)
        self.assertEqual(prediction["horizon_years"], 3)
        self.assertTrue(all(p["available_on"] <= prediction["prediction_date"] for p in prediction["provenance"] if p["available_on"]))

    def test_true_60_40_model_ranking_uses_h3_gap(self):
        locations, status = attach_model(self.locations(), [{"geoid": "36061000100"}], "indian", self.config)
        self.assertEqual(status["ranking_mode"], "survival_cuisine_gap")
        self.assertAlmostEqual(locations[0]["opportunity"], 90)
        self.assertEqual(locations[0]["screening_opportunity"], 23)
        self.assertEqual(locations[0]["ranking_components"]["cuisine_gap"], .75)
        self.assertEqual(locations[0]["model_version"], status["model_version"])

    def test_model_metadata_checksum_mismatch_is_unavailable(self):
        artifact = self.model / "survival_model.json"
        artifact.write_text(artifact.read_text() + " ")
        engine, status = model_state(self.config)
        self.assertIsNone(engine)
        self.assertEqual(status["status"], "invalid_artifact")
        self.assertIn("checksum", status["message"])
        locations, status = attach_model(self.locations(), [{"geoid": "36061000100"}], "indian", self.config)
        self.assertEqual(locations[0]["opportunity"], 23)
        self.assertIsNone(locations[0]["survival"]["probability"])

    def test_missing_model_keeps_screening_and_reports_no_probability(self):
        self.config.write_text(json.dumps({"model_dir": str(self.root / "absent")}))
        with patch.dict(app.app.config, {"SURVIVAL_CONFIG": str(self.config)}), app.app.test_client() as client:
            status = client.get("/api/models/survival")
            response = client.get("/api/dashboard?borough=Manhattan")
        self.assertEqual(status.json["status"], "awaiting_artifact")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["meta"]["assessment_type"], "Uncalibrated Screening Index")
        self.assertIsNone(response.json["locations"][0]["survival"]["probability"])

    def test_missing_gap_and_missing_feature_do_not_become_model_rankings(self):
        self.gaps.unlink()
        rows, status = attach_model(self.locations(), [{"geoid": "36061000100"}], "indian", self.config)
        self.assertEqual(status["ranking_mode"], "screening")
        self.assertEqual(rows[0]["survival"]["status"], "available")
        self.assertEqual(rows[0]["opportunity"], 23)
        engine, _ = model_state(self.config)
        self.assertEqual(engine.predict([{"geoid": "36061099999"}]), {})

    def test_legacy_model_cannot_be_connected(self):
        metadata = self.model / "model_meta.json"
        value = json.loads(metadata.read_text())
        value["schema"] = "legacy"
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "Legacy"):
            connect(self.model, [self.fixture.manifest], self.root, self.gaps, self.root / "never_active.json")
        self.assertFalse((self.root / "never_active.json").exists())


if __name__ == "__main__":
    unittest.main()
