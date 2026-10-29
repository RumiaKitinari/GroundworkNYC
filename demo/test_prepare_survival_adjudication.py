"""Safety checks for the unverified survival-adjudication packet."""

import csv
import tempfile
import unittest
from pathlib import Path

from prepare_survival_adjudication import build_packet
from match_sla_lifespan_leads import candidate_address, normalized_address


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


class AdjudicationTests(unittest.TestCase):
    def test_queens_building_hyphen_normalization_is_borough_specific(self):
        self.assertEqual(candidate_address("13515 37TH AVE 11354", "Queens"),
                         normalized_address("135-15 37 AVENUE", "11354", "Queens"))
        self.assertNotEqual(normalized_address("12-14 MAIN STREET", "10001", "Manhattan"),
                            normalized_address("1214 MAIN STREET", "10001", "Manhattan"))

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.queue, self.sla, self.fsq, self.current = (
            root / name for name in ("queue.csv", "sla.csv", "fsq.csv", "current.csv"))
        base = {"business_id": "1", "geoid": "36061000100", "nta_code": "MN01",
                "borough": "Manhattan", "as_of_date": "", "baseline_operating": "",
                "baseline_source_reference": "", "verification_status": "independent_verification_required",
                "outcome_status": "unresolved", "outcome_observed_on": "",
                "outcome_recorded_on": "", "outcome_source_reference": "",
                "candidate_name": "CAFE ONE", "candidate_address": "10 MAIN ST 10001",
                "first_snapshot": "2023-08-01",
                "observation_status": "disappeared_between_snapshots",
                "first_operational_prepermit": "2023-06-01", "followup_inspection_365_455": ""}
        write_csv(self.queue, [base])
        write_csv(self.sla, [{**base, "sla_match_status": "inactive_license_lead",
                              "sla_active_ids": "", "sla_inactive_ids": "44",
                              "sla_active_source_url": "", "sla_inactive_source_url": "source"}])
        write_csv(self.fsq, [{**base, "fsq_match_status": "marked_closed_by_2025_review",
                              "fsq_place_ids": "p1", "fsq_marked_closed_dates": "2025-01-01",
                              "fsq_place_urls": "source"}])
        write_csv(self.current, [{"camis": "1", "dba": "CAFE TWO", "boro": "Manhattan",
                                  "building": "10", "street": "MAIN STREET", "zipcode": "10001",
                                  "inspection_date": "2026-01-01T00:00:00", "record_date": "2026-10-20T00:00:00"}])

    def test_identity_conflict_does_not_become_outcome(self):
        rows, sample, fields, summary = build_packet(self.queue, self.sla, self.fsq,
                                                      self.current, sample_size=1)
        self.assertEqual(rows, sample)
        self.assertEqual(rows[0]["identity_review"], "name_or_address_changed")
        self.assertEqual(rows[0]["review_tier"], "identity_or_date_conflict")
        self.assertEqual(rows[0]["outcome_status"], "unresolved")
        self.assertEqual(rows[0]["verification_status"], "independent_verification_required")
        self.assertEqual(rows[0]["baseline_operating"], "")
        self.assertEqual(summary["sample_inclusion_probability"], 1)
        self.assertIn("outcome_source_reference", fields)

    def test_absence_is_not_closure(self):
        write_csv(self.current, [{"camis": "other", "dba": "CAFE TWO", "boro": "Manhattan",
                                  "building": "10", "street": "MAIN STREET", "zipcode": "10001",
                                  "inspection_date": "2026-01-01", "record_date": "2026-10-20"}])
        rows, _, _, _ = build_packet(self.queue, self.sla, self.fsq, self.current)
        self.assertEqual(rows[0]["current_active_feed_status"], "absent_not_closure_evidence")
        self.assertEqual(rows[0]["outcome_status"], "unresolved")

    def test_same_name_address_under_new_camis_is_review_only(self):
        write_csv(self.current, [{"camis": "2", "dba": "CAFE ONE", "boro": "Manhattan",
                                  "building": "10", "street": "MAIN STREET", "zipcode": "10001",
                                  "inspection_date": "2026-01-01", "record_date": "2026-10-20"}])
        rows, _, _, _ = build_packet(self.queue, self.sla, self.fsq, self.current)
        self.assertEqual(rows[0]["identity_review"], "possible_camis_change")
        self.assertEqual(rows[0]["other_current_camis_same_name_address"], "2")
        self.assertEqual(rows[0]["outcome_status"], "unresolved")

    def test_rejects_misaligned_or_labeled_leads(self):
        with self.sla.open("r", newline="", encoding="utf-8") as stream:
            row = next(csv.DictReader(stream))
        write_csv(self.sla, [{**row, "business_id": "2"}])
        with self.assertRaisesRegex(ValueError, "same business IDs"):
            build_packet(self.queue, self.sla, self.fsq, self.current)
        write_csv(self.sla, [{**row, "verification_status": "independently_verified"}])
        with self.assertRaisesRegex(ValueError, "unverified leads"):
            build_packet(self.queue, self.sla, self.fsq, self.current)
        write_csv(self.sla, [{**row, "candidate_name": "DIFFERENT CAFE"}])
        with self.assertRaisesRegex(ValueError, "Lead identity differs"):
            build_packet(self.queue, self.sla, self.fsq, self.current)


if __name__ == "__main__":
    unittest.main()
