import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from evaluation import FEATURES, OUTCOME_METADATA, feature_vector, holdout_indices, outcome_cohort, presence_cohort, train_benchmark
from scoring import ScreeningModel


class EvaluationTests(unittest.TestCase):
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
        self.assertEqual(report["deployment_status"], "research_only")


if __name__ == "__main__":
    unittest.main()
