"""Tests for conservative matching of original DOHMH capture evidence."""

import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from verify_archived_operating_pairs import build_packet


class ArchivedOperatingPairsTests(unittest.TestCase):
    def test_pair_requires_same_identity_and_eligible_cycle_dates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            queue = root / "queue.csv"
            fields = ("business_id", "candidate_name", "candidate_address", "borough",
                      "first_cycle_inspection_lead", "verification_status", "outcome_status",
                      "identity_review")
            with queue.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for camis in ("1", "2", "3", "4"):
                    writer.writerow({"business_id": camis, "candidate_name": "Cafe A",
                                     "candidate_address": "10 Main Street 10001", "borough": "Manhattan",
                                     "first_cycle_inspection_lead": "2023-09-01",
                                     "verification_status": "independent_verification_required",
                                     "outcome_status": "unresolved",
                                     "identity_review": "possible_camis_change" if camis == "4"
                                     else "same_name_and_address"})
            capture_fields = ("CAMIS", "DBA", "BORO", "BUILDING", "STREET", "ZIPCODE",
                              "INSPECTION DATE", "INSPECTION TYPE", "ACTION", "RECORD DATE")
            for stamp, inspected, rows in (
                ("20231117063638", "09/01/2023", (("1", "Cafe A", ""), ("2", "Cafe A", ""),
                                                      ("3", "Cafe A", ""), ("4", "Cafe A", ""))),
                ("20240928031215", "09/05/2024", (("1", "Cafe A", ""), ("2", "Cafe B", ""),
                                                      ("3", "Cafe A", "Establishment Closed by DOHMH"),
                                                      ("4", "Cafe A", "")))):
                path = root / f"wayback_{stamp}.csv"
                opener = gzip.open if stamp.startswith("2024") else open
                with opener(path, "wt", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=capture_fields)
                    writer.writeheader()
                    for camis, name, action in rows:
                        writer.writerow({"CAMIS": camis, "DBA": name, "BORO": "Manhattan",
                                         "BUILDING": "10", "STREET": "MAIN ST", "ZIPCODE": "10001",
                                         "INSPECTION DATE": inspected,
                                         "INSPECTION TYPE": "Cycle Inspection / Initial Inspection",
                                         "ACTION": action, "RECORD DATE": "11/16/2023" if stamp.startswith("2023")
                                         else "09/27/2024"})
            captures = sorted(root.glob("wayback_*.csv"))
            rows, _, counts, _ = build_packet(queue, captures)
            self.assertEqual(counts["original_capture_operating_pair_review"], 1)
            self.assertEqual(counts["original_capture_operating_pair_identity_conflict"], 1)
            self.assertEqual(rows[0]["followup_inspection_on"], "2024-09-05")
            self.assertEqual(rows[0]["outcome_status"], "unresolved")
            self.assertTrue(all(row["archive_pair_status"] == "original_capture_baseline_only"
                                for row in rows[1:3]))
            self.assertEqual(rows[3]["outcome_status"], "unresolved")


if __name__ == "__main__":
    unittest.main()
