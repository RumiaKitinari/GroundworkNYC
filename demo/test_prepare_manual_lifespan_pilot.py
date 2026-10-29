import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from prepare_manual_lifespan_pilot import select_pilot


class ManualLifespanPilotTests(unittest.TestCase):
    def test_pilot_is_unlabeled_and_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "queue.csv"
            fields = ("business_id", "candidate_name", "candidate_address", "candidate_cuisine",
                      "borough", "geoid", "nta_code", "first_operational_prepermit",
                      "first_cycle_inspection_lead", "first_snapshot", "last_snapshot",
                      "next_snapshot", "followup_inspection_365_455", "observation_status",
                      "review_priority", "verification_status", "outcome_status")
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for business_id, priority in (("1", "snapshot_exit_within_year_review"),
                                              ("2", "operational_inspection_followup_review")):
                    writer.writerow({"business_id": business_id, "candidate_name": "Example",
                                     "candidate_address": "10 Main St", "candidate_cuisine": "American",
                                     "borough": "Brooklyn", "geoid": "36047000100", "nta_code": "BK0101",
                                     "first_operational_prepermit": "2024-01-01",
                                     "first_cycle_inspection_lead": "2024-06-01",
                                     "first_snapshot": "2024-09-28", "last_snapshot": "2025-05-02",
                                     "next_snapshot": "2025-09-13",
                                     "followup_inspection_365_455": "2025-03-01",
                                     "observation_status": "disappeared_between_snapshots",
                                     "review_priority": priority,
                                     "verification_status": "independent_verification_required",
                                     "outcome_status": "unresolved"})
            rows, summary = select_pilot(path, date(2026, 10, 20), 1, 1)
            again, _ = select_pilot(path, date(2026, 10, 20), 1, 1)
            self.assertEqual(rows, again)
            self.assertEqual(summary["selected_by_stratum"],
                             {"snapshot_exit_review": 1, "inspection_followup_review": 1})
            self.assertEqual({row["outcome_status"] for row in rows}, {"unresolved"})
            self.assertEqual({row["as_of_date"] for row in rows}, {""})
            self.assertTrue(all("camis=" in row["dohmh_current_record_url"] for row in rows))


if __name__ == "__main__":
    unittest.main()
