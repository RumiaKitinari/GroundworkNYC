import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from evaluation import HISTORICAL_CORE_FEATURES, fingerprint
from train_archive_reobservation import build_proxy_cohort


class ArchiveReobservationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.lifespans = self.data / "lifespans.csv"
        self.snapshots = self.data / "manifest.json"
        self.snapshot_csv = self.data / "tracts.csv"
        with self.snapshot_csv.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["geoid", *HISTORICAL_CORE_FEATURES])
            writer.writeheader()
            writer.writerow({"geoid": "36061000100", **dict.fromkeys(HISTORICAL_CORE_FEATURES, "10")})
        self.snapshots.write_text(json.dumps({"snapshots": [
            {"feature": feature, "path": "tracts.csv", "column": feature,
             "observed_through": "2022-12-31", "available_on": "2023-02-01",
             "sha256": fingerprint(self.snapshot_csv), "source_url": "https://example.org/historical",
             "historical_reconstruction_verified": True}
            for feature in HISTORICAL_CORE_FEATURES]}))

    def case(self, **changes):
        return {**{"camis": "1", "geoid": "36061000100", "nta_code": "MN01",
                   "borough": "Manhattan", "clean_cohort": "true",
                   "first_cycle_inspection": "2023-06-01", "last_snapshot": "2024-06-02",
                   "next_snapshot": "2025-01-01"}, **changes}

    def write_cases(self, cases):
        with self.lifespans.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.case().keys())
            writer.writeheader()
            writer.writerows(cases)

    def test_reobservation_label_is_archive_only(self):
        self.write_cases([self.case(), self.case(camis="2", last_snapshot="2024-05-30"),
                          self.case(camis="3", first_cycle_inspection="2024-06-02",
                                    last_snapshot="2025-01-01"),
                          self.case(camis="4", clean_cohort="false")])
        rows, matrix, audit = build_proxy_cohort(self.lifespans, self.snapshots, self.data,
                                                 today=date(2025, 1, 2))
        self.assertEqual([row["y"] for row in rows], [1, 0])
        self.assertEqual(len(matrix), 2)
        self.assertEqual(audit["class_counts"], {1: 1, 0: 1})
        self.assertFalse(audit["training_eligible_for_business_survival"])
        self.assertEqual(audit["excluded"]["immature_followup"], 1)

    def test_future_features_cannot_enter_cohort(self):
        manifest = json.loads(self.snapshots.read_text())
        for entry in manifest["snapshots"]:
            entry["available_on"] = "2023-07-01"
        self.snapshots.write_text(json.dumps(manifest))
        self.write_cases([self.case()])
        rows, _, audit = build_proxy_cohort(self.lifespans, self.snapshots, self.data,
                                            today=date(2025, 1, 2))
        self.assertEqual(rows, [])
        self.assertEqual(audit["excluded"]["missing_historical_population_density_per_sq_mile"], 1)

    def test_duplicate_identity_rejected(self):
        self.write_cases([self.case(), self.case()])
        with self.assertRaisesRegex(ValueError, "unique"):
            build_proxy_cohort(self.lifespans, self.snapshots, self.data, today=date(2025, 1, 2))

    def test_strict_disappearance_censors_successors_and_short_gaps(self):
        self.write_cases([self.case(), self.case(camis="2", last_snapshot="2024-05-30"),
                          self.case(camis="3", last_snapshot="2024-05-30"),
                          self.case(camis="4", last_snapshot="2024-05-30"),
                          self.case(camis="5", first_cycle_inspection="2023-12-01",
                                    last_snapshot="2024-09-01")])
        lifespan_manifest = self.data / "lifespans.manifest.json"
        lifespan_manifest.write_text(json.dumps({
            "output_sha256": fingerprint(self.lifespans),
            "snapshot_dates": ["2024-05-30", "2024-06-01", "2024-09-01", "2025-01-01"]}))
        adjudication = self.data / "adjudication.csv"
        fields = ("business_id", "identity_review", "current_active_feed_status",
                  "other_current_camis_same_name_address", "verification_status", "outcome_status",
                  "first_cycle_inspection_lead", "geoid", "borough")
        with adjudication.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for camis in ("1", "2", "3", "4", "5"):
                writer.writerow({"business_id": camis,
                                 "identity_review": "possible_camis_change" if camis == "4" else
                                                    "same_name_and_address" if camis == "1" else
                                                    "no_current_camis_record",
                                 "current_active_feed_status": "absent_not_closure_evidence",
                                 "other_current_camis_same_name_address": "9" if camis == "3" else "",
                                 "verification_status": "independent_verification_required",
                                 "outcome_status": "unresolved",
                                 "first_cycle_inspection_lead": "2023-12-01" if camis == "5" else "2023-06-01",
                                 "geoid": "36061000100", "borough": "Manhattan"})
        rows, matrix, audit = build_proxy_cohort(
            self.lifespans, self.snapshots, self.data, today=date(2025, 1, 2),
            adjudication_path=adjudication, lifespan_manifest_path=lifespan_manifest)
        self.assertEqual([row["id"] for row in rows], ["1", "2"])
        self.assertEqual([row["y"] for row in rows], [1, 0])
        self.assertEqual(matrix[1]["proxy_label_basis"], "two_posthorizon_absences_no_known_successor")
        self.assertEqual(audit["excluded"]["identity_conflict_censored"], 1)
        self.assertEqual(audit["excluded"]["insufficient_disappearance_evidence_censored"], 2)
        self.assertTrue(audit["strict_disappearance_rule"])


if __name__ == "__main__":
    unittest.main()
