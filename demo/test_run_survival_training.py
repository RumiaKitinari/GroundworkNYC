import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from evaluation import HISTORICAL_CORE_FEATURES, fingerprint
from prepare_historical_cohort import EVIDENCE_FIELDS
from run_survival_training import run_training


class SurvivalTrainingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name) / "data"
        self.data.mkdir()
        self.evidence = self.data / "evidence.csv"
        self.snapshots = self.data / "snapshots.json"
        feature_file = self.data / "tracts.csv"
        with feature_file.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("geoid", *HISTORICAL_CORE_FEATURES))
            writer.writeheader()
            for group in range(20):
                writer.writerow({"geoid": f"36061{group:06d}",
                                 "population_density_per_sq_mile": 1000 + group * 200,
                                 "median_household_income": 50000 + group * 1000,
                                 "job_density_per_sq_mile": 500 + group * 100,
                                 "national_walkability_index": 5 + group % 10})
        self.snapshots.write_text(json.dumps({"snapshots": [
            {"feature": feature, "path": "tracts.csv", "column": feature,
             "observed_through": "2022-01-01", "available_on": "2022-12-01",
             "sha256": fingerprint(feature_file), "source_url": "https://example.org/archive",
             "historical_reconstruction_verified": True}
            for feature in HISTORICAL_CORE_FEATURES]}))

    def write_evidence(self, rows):
        with self.evidence.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=EVIDENCE_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def case(self, group=0, number=0, year=2023, verified=True):
        positive = number % 2 == 0
        return {"business_id": f"{group}-{year}-{number}", "geoid": f"36061{group:06d}",
                "nta_code": f"MN{group:02d}", "borough": "Manhattan",
                "as_of_date": f"{year}-01-01", "baseline_operating": "true",
                "baseline_source_reference": f"baseline-{group}-{year}-{number}",
                "verification_status": "independently_verified" if verified else "independent_verification_required",
                "outcome_status": "verified_operating" if positive else "verified_permanent_closure",
                "outcome_observed_on": f"{year + 1}-01-10" if positive else f"{year}-06-01",
                "outcome_recorded_on": f"{year + 1}-01-12" if positive else f"{year}-06-02",
                "outcome_source_reference": f"followup-{group}-{year}-{number}"}

    def test_unverified_packet_never_trains_or_writes_cohort(self):
        self.write_evidence([self.case(verified=False)])
        output = self.data / "evaluation/runs/blocked"
        result = run_training(self.evidence, self.snapshots, self.data, output, cutoff="2025-01-01",
                              today=date(2026, 10, 20))
        self.assertEqual(result["status"], "needs_verified_outcomes")
        self.assertFalse(result["training_performed"])
        self.assertFalse(output.exists())

    def test_verified_fixture_produces_private_models_and_audit(self):
        self.write_evidence([self.case(group, number, year)
                             for group in range(20) for year in (2023, 2025) for number in range(10)])
        output = self.data / "evaluation/runs/test"
        result = run_training(self.evidence, self.snapshots, self.data, output, cutoff="2025-01-01",
                              today=date(2026, 10, 20))
        self.assertEqual(result["status"], "evaluated")
        self.assertTrue(result["training_performed"])
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["deployment_status"], "research_only")
        self.assertEqual(report["split"]["neighborhood_overlap"], 0)
        self.assertEqual(report["split"]["method"], "temporal_and_neighborhood_holdout")
        self.assertEqual(len(report["model_artifacts"]), 2)
        self.assertTrue((output / "hist_gradient_boosting.joblib").is_file())
        import joblib
        saved = joblib.load(output / "hist_gradient_boosting.joblib")
        self.assertEqual(saved["features"], list(HISTORICAL_CORE_FEATURES))
        self.assertEqual(saved["deployment_status"], "research_only")
        self.assertEqual(saved["estimator"].n_features_in_, 4)
        self.assertEqual(result["audit"]["cohort_sha256"], fingerprint(output / "cohort.csv"))
        with self.assertRaises(FileExistsError):
            run_training(self.evidence, self.snapshots, self.data, output, cutoff="2025-01-01",
                         today=date(2026, 10, 20))

    def test_missing_cutoff_and_public_output_rejected(self):
        self.write_evidence([self.case()])
        with self.assertRaisesRegex(ValueError, "cutoff"):
            run_training(self.evidence, self.snapshots, self.data, self.data / "run")
        with self.assertRaisesRegex(ValueError, "private data directory"):
            run_training(self.evidence, self.snapshots, self.data, Path(self.folder.name) / "public",
                         cutoff="2025-01-01")


if __name__ == "__main__":
    unittest.main()
