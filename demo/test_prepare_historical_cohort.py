import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from evaluation import FEATURES, HISTORICAL_CORE_FEATURES, fingerprint, outcome_cohort
from prepare_historical_cohort import EVIDENCE_FIELDS, build_cohort, write_cohort


class HistoricalCohortTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name) / "data"
        self.data.mkdir()
        self.evidence = Path(self.folder.name) / "evidence.csv"
        self.manifest = Path(self.folder.name) / "snapshots.json"
        self.today = date(2024, 6, 1)

    def case(self, **changes):
        row = {"business_id": "123", "geoid": "36061000100", "nta_code": "MN01", "borough": "Manhattan",
               "as_of_date": "2022-01-01", "baseline_operating": "true",
               "baseline_source_reference": "Dated owner record", "verification_status": "independently_verified",
               "outcome_status": "verified_operating", "outcome_observed_on": "2023-01-05",
               "outcome_recorded_on": "2023-01-06", "outcome_source_reference": "Dated later record"}
        return dict(row, **changes)

    def write_evidence(self, rows):
        with self.evidence.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=EVIDENCE_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def write_snapshots(self, available="2021-12-01", observed="2020-12-31"):
        path = self.data / "historical.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["geoid", *FEATURES])
            writer.writeheader()
            writer.writerow({"geoid": "36061000100", **dict.fromkeys(FEATURES, "10")})
        entries = [{"feature": feature, "path": "historical.csv", "column": feature,
                    "observed_through": observed, "available_on": available,
                    "sha256": fingerprint(path), "source_url": "https://example.org/archive",
                    "historical_reconstruction_verified": True} for feature in FEATURES]
        self.manifest.write_text(json.dumps({"snapshots": entries}))

    def test_verified_case_joins_only_available_snapshots(self):
        self.write_evidence([self.case()])
        self.write_snapshots()
        rows, audit = build_cohort(self.evidence, self.manifest, self.data, self.today)
        self.assertEqual(audit["verified_rows"], 1)
        self.assertEqual(rows[0]["features_available_on"], "2021-12-01")
        output = Path(self.folder.name) / "cohort.csv"
        write_cohort(output, rows)
        checked, _, _ = outcome_cohort(output, "2024-01-01", today=self.today)
        self.assertEqual(len(checked), 1)
        with self.assertRaises(FileExistsError):
            write_cohort(output, rows)

    def test_future_snapshot_does_not_join(self):
        self.write_evidence([self.case()])
        self.write_snapshots(available="2022-02-01")
        rows, audit = build_cohort(self.evidence, self.manifest, self.data, self.today)
        self.assertEqual(rows, [])
        self.assertEqual(audit["excluded"]["missing_historical_population_density_per_sq_mile"], 1)

    def test_unverified_and_unresolved_remain_unlabeled(self):
        self.write_evidence([self.case(business_id="1", verification_status="independent_verification_required"),
                             self.case(business_id="2", outcome_status="unresolved")])
        self.manifest.write_text('{"snapshots": []}')
        rows, audit = build_cohort(self.evidence, self.manifest, self.data, self.today)
        self.assertEqual(rows, [])
        self.assertEqual(audit["excluded"]["unverified_evidence"], 1)
        self.assertEqual(audit["excluded"]["censored_unresolved"], 1)

    def test_core_features_use_partial_manifest_without_future_inputs(self):
        self.write_evidence([self.case()])
        self.write_snapshots()
        manifest = json.loads(self.manifest.read_text())
        manifest["snapshots"] = [entry for entry in manifest["snapshots"]
                                 if entry["feature"] in HISTORICAL_CORE_FEATURES]
        self.manifest.write_text(json.dumps(manifest))
        rows, audit = build_cohort(self.evidence, self.manifest, self.data, self.today,
                                   features=HISTORICAL_CORE_FEATURES)
        self.assertEqual(len(rows), 1)
        self.assertEqual(audit["features"], list(HISTORICAL_CORE_FEATURES))
        output = Path(self.folder.name) / "core.csv"
        write_cohort(output, rows, HISTORICAL_CORE_FEATURES)
        checked, _, _ = outcome_cohort(output, "2024-01-01", today=self.today,
                                       features=HISTORICAL_CORE_FEATURES)
        self.assertEqual(len(checked[0]["x"]), 4)
        rows, audit = build_cohort(self.evidence, self.manifest, self.data, self.today)
        self.assertEqual(rows, [])
        self.assertIn("missing_historical_nearest_subway_distance_miles", audit["excluded"])

    def test_same_evidence_cannot_verify_baseline_and_outcome(self):
        self.write_evidence([self.case(outcome_source_reference="Dated owner record")])
        self.manifest.write_text('{"snapshots": []}')
        with self.assertRaisesRegex(ValueError, "independent evidence"):
            build_cohort(self.evidence, self.manifest, self.data, self.today)

    def test_latest_available_vintage_selected_by_baseline_date(self):
        self.today = date(2026, 6, 1)
        self.write_evidence([
            self.case(business_id="early", as_of_date="2023-12-15",
                      outcome_observed_on="2024-12-20", outcome_recorded_on="2024-12-21"),
            self.case(business_id="late", as_of_date="2024-12-15",
                      outcome_observed_on="2025-12-20", outcome_recorded_on="2025-12-21"),
        ])
        self.write_snapshots(available="2023-12-07", observed="2022-12-31")
        later = self.data / "later.csv"
        with later.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["geoid", *HISTORICAL_CORE_FEATURES])
            writer.writeheader()
            writer.writerow({"geoid": "36061000100", **dict.fromkeys(HISTORICAL_CORE_FEATURES, "20")})
        manifest = json.loads(self.manifest.read_text())
        manifest["snapshots"] = [entry for entry in manifest["snapshots"]
                                 if entry["feature"] in HISTORICAL_CORE_FEATURES]
        manifest["snapshots"].extend({"feature": feature, "path": "later.csv", "column": feature,
                                      "observed_through": "2023-12-31", "available_on": "2024-12-12",
                                      "sha256": fingerprint(later), "source_url": "https://example.org/later",
                                      "historical_reconstruction_verified": True}
                                     for feature in HISTORICAL_CORE_FEATURES)
        self.manifest.write_text(json.dumps(manifest))
        rows, _ = build_cohort(self.evidence, self.manifest, self.data, self.today,
                               features=HISTORICAL_CORE_FEATURES)
        self.assertEqual([row["population_density_per_sq_mile"] for row in rows], ["10", "20"])

    def test_sample_and_changed_snapshot_rejected(self):
        self.write_evidence([self.case()])
        self.write_snapshots()
        manifest = json.loads(self.manifest.read_text())
        manifest["snapshots"][0]["sha256"] = "bad"
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            build_cohort(self.evidence, self.manifest, self.data, self.today)
        manifest["snapshots"][0]["sha256"] = fingerprint(self.data / "historical.csv")
        manifest["snapshots"][0]["path"] = "historical_SAMPLE.csv"
        self.manifest.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "SAMPLE"):
            build_cohort(self.evidence, self.manifest, self.data, self.today)


if __name__ == "__main__":
    unittest.main()
