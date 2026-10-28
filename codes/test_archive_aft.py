"""Small synthetic fixtures verify research exports; never empirical validation."""
from contextlib import redirect_stdout
import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from model_feature_catalog import SPECS
from recommend import validate_temporal_model
from run_archive_research import combine_scenarios, run
from customer_access import file_hash
from validate_archive_run import validate
import train_archive_aft as research


def fixture_master():
    base = {source: .5 if domain == "share" else 25 if domain == "percent" else 12
            for _, source, domain, _, _ in SPECS}
    base.update({"land_area_sq_miles": 1, "population_2024": 1000, "total_jobs": 500,
        "median_household_income_2024": 80000, "neighbor_income_2024_estimate": 80000,
        "subway_weekly_ridership": 100, "citibike_departures_per_sq_mile_latest_month": 10,
        "taxi_zone": "fixture", "dropoffs_latest_month": 100, "pickups_latest_month": 100,
        "registered_storefronts": 10, "leased_storefronts": 8, "food_nightlife_poi_count": 20,
        "bar_nightlife_competitor_count": 5, "cafe_competitor_count": 5,
        "neighbor_geoids": "", "borough": "Manhattan"})
    return pd.DataFrame([dict(base, geoid=36061000100 + i * 100, nta_code="NTA" + str(i),
        centroid_latitude=40.7 + i * .01, centroid_longitude=-74.) for i in range(5)])


class ArchiveResearchTests(unittest.TestCase):
    def test_fit_exports_holdouts_models_and_explicit_nonproduction_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = fixture_master()
            master.to_csv(root / "master.csv", index=False)
            life = pd.DataFrame([{"camis": i, "dba": "Fixture " + str(i),
                "lat": master.iloc[i % 5].centroid_latitude, "lon": -74.,
                "open_date": "2021-01-01", "close_date": "2022-01-01" if i % 2 == 0 else "",
                "fixture_geoid": master.iloc[i % 5].geoid} for i in range(30)])
            life.to_csv(root / "life.csv", index=False)
            properties = pd.DataFrame([{"property_id": "fixture-" + str(i), "geoid": row.geoid,
                "latitude": row.centroid_latitude, "longitude": -74., "borough": "Manhattan",
                "inventory_type": "synthetic_demonstration"} for i, row in enumerate(master.itertuples())])
            properties.to_csv(root / "properties.csv", index=False)
            plan = {"schema": "archive-aft-research-plan-v1", "target": "Test-only archive proxy",
                    "production_deployment_allowed": False, "rounds": 1, "folds": 5,
                    "ablations": ["residents", "employment", "built_environment", "mobility"]}
            (root / "plan.json").write_text(json.dumps(plan))
            def assemble(life, tract, master):
                frame = life.copy()
                frame["geoid"] = frame.fixture_geoid
                frame = frame.join(tract, on="geoid")
                frame["is_chain"], frame["competitors_400m_at_open"], frame["open_year"] = 0, 2, 2021
                frame["y_lower"] = np.where(frame.camis % 2 == 0, .5, 4.)
                frame["y_upper"] = np.where(frame.camis % 2 == 0, 1., np.inf)
                return frame, pd.Timestamp("2026-10-04")
            with patch.object(research, "load_reference", return_value=SimpleNamespace(build_training_rows=assemble)), redirect_stdout(io.StringIO()):
                report = research.train(root / "master.csv", root / "life.csv", root / "properties.csv",
                    root / "reference.py", root / "run", root / "plan.json")
            self.assertEqual(report["training_rows"], 30)
            heldout = pd.read_csv(root / "run/heldout_predictions.csv")
            self.assertEqual(len(heldout), 180)
            self.assertTrue(heldout.proxy_aft_3yr.between(0, 1).all())
            for _, model in heldout.groupby("model"):
                self.assertFalse(model.camis.duplicated().any())
                self.assertTrue(model.groupby("nta_code").fold.nunique().eq(1).all())
            for name, feature_count in (("legacy_50", 50), ("corrected_context_plus_restaurant", 41)):
                meta = json.loads((root / "run" / name / "model_meta.json").read_text())
                self.assertEqual(len(meta["features"]), feature_count)
                self.assertFalse(meta["trained_on_synthetic_properties"])
                self.assertEqual(meta["deployment_status"], "offline_proxy_research_only")
                with self.assertRaisesRegex(ValueError, "rejected"):
                    validate_temporal_model(meta, "2026-10-27")
            self.assertEqual(len(pd.read_csv(root / "run/property_proxy_scores.csv")), 5)
            bundle = root / "bundle"
            shutil.copytree(root / "run", bundle / "corrected_research")
            manifest = {"status": "completed_offline_proxy_research", "deployment_allowed": False,
                "artifact_sha256": {str(path.relative_to(bundle)): file_hash(path)
                    for path in bundle.rglob("*") if path.is_file()}}
            (bundle / "run_manifest.json").write_text(json.dumps(manifest))
            with redirect_stdout(io.StringIO()):
                verification = validate(bundle, root / "validation")
            self.assertEqual(len(verification["native_fold_replays"]), 30)
            with (bundle / "corrected_research/heldout_predictions.csv").open("a") as stream:
                stream.write("tampered")
            with self.assertRaisesRegex(ValueError, "Frozen artifact changed"):
                validate(bundle, root / "invalid_validation")
            with self.assertRaises(FileExistsError):
                research.train(None, None, None, None, root / "run", None)

    def test_explicit_proxy_acknowledgement_and_private_output_required(self):
        with self.assertRaisesRegex(ValueError, "acknowledge-proxy"):
            run("/tmp/unused", False, None)
        with self.assertRaisesRegex(ValueError, "private data/output"):
            run("/tmp/unused", True, None)

    def test_missing_scenario_support_is_not_filled_with_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "corrected_research").mkdir()
            (root / "scenarios").mkdir()
            pd.DataFrame({"property_id": ["a", "b"],
                "corrected_context_plus_restaurant_proxy_aft_3yr": [.5, .7]}).to_csv(root / "corrected_research/property_proxy_scores.csv", index=False)
            for name in ("neighborhood_cafe", "office_lunch", "casual_dinner", "premium_dinner"):
                pd.DataFrame({"property_id": ["a", "b"], "cuisine_gap": [.3, .4],
                    "customer_access_percentile": [50, np.nan], "huff_percentile": [40, np.nan]}).to_csv(root / "scenarios" / (name + ".csv"), index=False)
            combine_scenarios(root)
            result = pd.read_csv(root / "scenarios/neighborhood_cafe_research_rankings.csv")
            self.assertTrue(pd.isna(result.loc[1, "research_huff_10pct"]))
            self.assertTrue(pd.isna(result.loc[1, "research_access_20pct"]))
            self.assertEqual(result.research_60_40.notna().sum(), 2)


if __name__ == "__main__":
    unittest.main()
