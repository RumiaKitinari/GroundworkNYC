import csv
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from evaluation import FEATURES, HISTORICAL_CORE_FEATURES, OUTCOME_METADATA, evaluation_status, feature_vector, fingerprint, holdout_indices, outcome_cohort, presence_cohort, run_evaluation, train_benchmark
from scoring import ScreeningModel


class EvaluationTests(unittest.TestCase):
    def test_imputation_and_indicators_are_fitted_on_training_only(self):
        import numpy as np
        rows = [dict(id=str(i), group=f"N{i // 10}", borough="Test", y=i % 2,
                     x=[2.0] * len(FEATURES)) for i in range(400)]
        train, test = holdout_indices(rows, None)
        rows[train[0]]["x"][0] = float("nan")
        for i in test:
            rows[i]["x"][0] = 999999.0
            rows[i]["x"][1] = float("nan")
        report, models = train_benchmark(rows, "market_presence", {}, capture_estimators=True)
        imputer = models["location_model"].steps[0][1]
        self.assertEqual(imputer.statistics_[0], 2.0)
        self.assertEqual(imputer.indicator_.features_.tolist(), [0])
        self.assertEqual(report["model_parameters"]["missingness_indicator_features"], [FEATURES[0]])
        transformed = imputer.transform(np.array([rows[i]["x"] for i in test]))
        self.assertTrue(np.isfinite(transformed).all())

    def test_permit_tracking_is_readiness_only(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            status_path = data / "evaluation/permit_presence/status.json"
            status_path.parent.mkdir(parents=True)
            status_path.write_text(json.dumps({
                "status": "collecting_history", "target": "one_year_permit_presence_not_restaurant_survival",
                "first_record_date": "2026-09-30", "latest_record_date": "2026-10-16",
                "distinct_snapshot_dates": 9, "review_leads": 55, "one_year_training_ready": False}))
            result = evaluation_status(data)
            self.assertEqual(result["permit_presence_tracking"]["review_leads"], 55)
            self.assertFalse(result["permit_presence_tracking"]["one_year_training_ready"])
            self.assertNotIn("permit_persistence", result["available_targets"])
            self.assertIsNone(result["success_probability"])

    def test_candidate_transit_is_not_verified_history(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            candidate_dir = data / "evaluation/candidates/mta_week_2023-12-01"
            candidate_dir.mkdir(parents=True)
            source = candidate_dir / "tract_subway_candidate.csv"
            source.write_text("geoid,nearest_subway_distance_miles\n36061000100,0.1\n")
            metadata = {"status": "candidate_not_as_of_verified", "training_eligible": False,
                        "tract_features": str(source.relative_to(folder)), "tract_features_sha256": fingerprint(source)}
            (candidate_dir / "candidate_manifest.json").write_text(json.dumps(metadata))
            status = evaluation_status(data)["historical_readiness"]
            self.assertIn("nearest_subway_distance_miles", status["candidate_features"])
            self.assertIn("nearest_subway_distance_miles", status["missing_features"])
            self.assertFalse(status["inputs_present_for_outcome_cohort"])
            source.write_text("changed")
            self.assertEqual(evaluation_status(data)["historical_readiness"]["candidate_features"], [])

    def test_presence_report_fingerprints_active_release(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            release = data / "integrated" / "releases" / "current"
            (release / "entities").mkdir(parents=True)
            (release / "master_tract_features.csv").write_text("active master\n")
            (release / "entities" / "current_restaurants.csv").write_text("active restaurants\n")
            package = {"data_path": "data/integrated/releases/current"}
            with patch("evaluation.presence_cohort", return_value=([], {})), \
                    patch("evaluation.train_benchmark", return_value={"status": "insufficient_evidence"}):
                report = run_evaluation(package, data, cuisine="korean")
            self.assertEqual(set(report["source_fingerprints"]), {
                "integrated/releases/current/master_tract_features.csv",
                "integrated/releases/current/entities/current_restaurants.csv",
            })

    def write_outcomes(self, row):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "outcomes.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(OUTCOME_METADATA + FEATURES))
            writer.writeheader()
            writer.writerow(row)
        return path

    def row(self, **changes):
        row = dict.fromkeys(FEATURES, "10")
        row.update(business_id="test1", nta_code="N1", as_of_date="2020-01-01",
                   features_observed_through="2019-01-01", features_available_on="2019-12-01",
                   baseline_operating="true", outcome_status="verified_operating",
                   outcome_observed_on="2021-01-05", outcome_recorded_on="2021-01-06", source_reference="Test evidence")
        return dict(row, **changes)

    def test_future_features_rejected(self):
        path = self.write_outcomes(self.row(features_available_on="2020-02-01"))
        with self.assertRaisesRegex(ValueError, "chronology"):
            outcome_cohort(path, "2022-01-01")

    def test_temporary_closure_is_not_failure(self):
        path = self.write_outcomes(self.row(outcome_status="health_department_closure"))
        with self.assertRaisesRegex(ValueError, "temporary"):
            outcome_cohort(path, "2022-01-01")

    def test_censoring_and_horizon(self):
        rows, excluded, _ = outcome_cohort(self.write_outcomes(self.row(outcome_status="unresolved")), "2022-01-01")
        self.assertEqual(rows, [])
        self.assertEqual(excluded["censored_unresolved"], 1)
        rows, excluded, _ = outcome_cohort(self.write_outcomes(self.row(outcome_status="verified_permanent_closure")), "2022-01-01")
        self.assertEqual(rows, [])
        self.assertEqual(excluded["outside_outcome_window"], 1)

    def test_valid_operating_outcome(self):
        rows, _, _ = outcome_cohort(self.write_outcomes(self.row()), "2022-01-01")
        self.assertEqual(rows[0]["y"], 1)

    def test_missing_historical_predictor_is_excluded(self):
        row = self.row()
        row["national_walkability_index"] = ""
        rows, excluded, _ = outcome_cohort(self.write_outcomes(row), "2022-01-01")
        self.assertEqual(rows, [])
        self.assertEqual(excluded["missing_or_invalid_historical_feature"], 1)

    def test_neighborhood_and_temporal_holdouts(self):
        rows = [dict(group=f"N{i // 10}", as_of=date(2020, 1, 1) if i % 2 else date(2023, 1, 1),
                     recorded=date(2021, 1, 1) if i % 2 else date(2024, 1, 1)) for i in range(200)]
        cutoff = date(2022, 1, 1)
        train, test = holdout_indices(rows, cutoff)
        self.assertTrue(len(train) and len(test))
        self.assertFalse({rows[i]["group"] for i in train} & {rows[i]["group"] for i in test})
        self.assertTrue(all(rows[i]["recorded"] < cutoff for i in train))
        self.assertTrue(all(rows[i]["as_of"] >= cutoff for i in test))

    def test_target_derived_features_excluded(self):
        self.assertFalse(any("cuisine" in key or "restaurant" in key or "score" in key for key in FEATURES))
        first = self.row()
        second = dict(first, active_restaurant_count=999, business_draw=100, cuisine_categories="Korean")
        self.assertEqual(feature_vector(first), feature_vector(second))

    def test_known_absence_is_not_a_failure_label(self):
        tract = {"geoid": "a", "nta_code": "n1"}
        records = [dict(camis=str(i), geoid="a", cuisine_description="Italian", active_establishment="True") for i in range(10)]
        package = {"tracts": [tract], "screening_model": ScreeningModel([tract], records)}
        rows, _ = presence_cohort(package, "korean")
        self.assertEqual(rows[0]["y"], 0)
        report = train_benchmark(rows, "market_presence", {})
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertIsNone(report["success_probability"])

    def test_full_pipeline_and_constant_baseline_ties(self):
        rows = [dict(id=str(i), group=f"N{i // 10}", borough="Test", y=i % 2,
                     x=[float(i % 2)] + [float(i % 7)] * (len(FEATURES) - 1)) for i in range(400)]
        report = train_benchmark(rows, "market_presence", {})
        self.assertEqual(report["status"], "evaluated")
        self.assertEqual(report["split"]["neighborhood_overlap"], 0)
        self.assertAlmostEqual(report["metrics"]["prevalence_baseline"]["top_quintile_lift"], 1)
        self.assertEqual({item["omitted_feature"] for item in report["feature_ablation"]}, set(FEATURES))
        self.assertEqual(len(report["model_parameters"]["coefficients"]), len(FEATURES))
        self.assertEqual(report["deployment_status"], "research_only")

    def test_core_survival_model_requires_verified_file(self):
        with tempfile.TemporaryDirectory() as folder:
            report = run_evaluation({}, Path(folder), target="continued_operation",
                                    feature_set="historical_core")
        self.assertEqual(report["status"], "needs_verified_outcomes")
        self.assertEqual(report["validation_mode"], "temporal_spatial")
        self.assertEqual(report["required_columns"][-4:], list(HISTORICAL_CORE_FEATURES))

    def test_unknown_historical_feature_set_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "feature set"):
                run_evaluation({}, Path(folder), target="continued_operation", feature_set="invented")

    def test_spatial_exploratory_mode_cannot_take_cutoff(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "does not use a temporal cutoff"):
                run_evaluation({}, Path(folder), target="continued_operation", feature_set="historical_core",
                               validation_mode="spatial_exploratory", cutoff="2025-06-01")

    def test_core_survival_comparison_uses_fixed_holdout(self):
        rows = [dict(id=str(i), group=f"N{i // 10}", borough="Test", y=(i // 2) % 2,
                     x=[float((i // 2) % 2)] + [float(i % 7)] * 3,
                     as_of=date(2020, 1, 1) if i % 2 else date(2023, 1, 1),
                     recorded=date(2021, 1, 1) if i % 2 else date(2024, 1, 1)) for i in range(400)]
        report = train_benchmark(rows, "continued_operation", {}, date(2022, 1, 1),
                                 HISTORICAL_CORE_FEATURES)
        self.assertEqual(report["status"], "evaluated")
        self.assertEqual(report["split"]["neighborhood_overlap"], 0)
        self.assertIn("hist_gradient_boosting", report["metrics"])
        self.assertIn("hist_gradient_boosting", report["calibration_bins"])
        self.assertEqual(report["deployment_status"], "research_only")


if __name__ == "__main__":
    unittest.main()
