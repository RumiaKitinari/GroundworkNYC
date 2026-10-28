import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from build_restaurant_lifespans import build_candidates
from prepare_lifespan_review import make_review_queue


class LifespanCandidateTests(unittest.TestCase):
    def test_snapshot_exit_stays_unresolved_and_late_prepermit_is_excluded(self):
        restaurants = [
            {"camis": 1, "dba": "One", "boro": "Brooklyn", "building": "10", "street": "Main St",
             "zipcode": "11201", "lat": 40.7, "lon": -73.9,
             "first_snapshot": datetime(2023, 8, 10), "last_snapshot": datetime(2024, 9, 28),
             "first_insp": datetime(2023, 1, 1), "first_prepermit": datetime(2023, 1, 1)},
            {"camis": 2, "dba": "Two", "boro": "Queens", "building": "20", "street": "Broadway",
             "zipcode": "11101", "lat": 40.75, "lon": -73.9,
             "first_snapshot": datetime(2023, 8, 10), "last_snapshot": datetime(2025, 5, 2),
             "first_insp": datetime(2023, 6, 1), "first_prepermit": datetime(2024, 1, 1)},
            {"camis": 3, "dba": "Three", "boro": "Queens", "building": "30", "street": "Broadway",
             "zipcode": "11101", "lat": 40.75, "lon": -73.9,
             "first_snapshot": datetime(2023, 8, 10), "last_snapshot": datetime(2025, 5, 2),
             "first_insp": datetime(2022, 1, 1), "first_prepermit": datetime(2022, 1, 1)},
        ]
        inspections = [(1, datetime(2023, 1, 1), "Pre-permit (Operational) / Initial Inspection"),
                       (1, datetime(2024, 1, 10), "Cycle Inspection / Initial Inspection"),
                       (2, datetime(2024, 1, 1), "Pre-permit (Operational) / Initial Inspection"),
                       (3, datetime(2022, 1, 1), "Pre-permit (Operational) / Initial Inspection")]
        rows, qa, snapshots = build_candidates(restaurants, inspections,
                                               lambda lat, lon: ("36047000100", "BK0101"))
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(qa["clean_temporal_candidates"], 1)
        self.assertEqual(qa["operational_prepermit_after_first_snapshot"], 1)
        self.assertEqual(qa["operational_prepermit_to_first_snapshot_over_365_days"], 1)
        self.assertEqual(rows[0]["clean_cohort"], "true")
        self.assertEqual(rows[0]["followup_inspection_365_455"], "2024-01-10")
        self.assertEqual(rows[0]["first_cycle_inspection"], "2024-01-10")
        self.assertEqual(rows[0]["next_snapshot"], "2025-05-02")
        self.assertEqual(rows[0]["outcome_status"], "unresolved")
        self.assertEqual(rows[1]["clean_cohort"], "false")
        self.assertEqual(rows[2]["clean_cohort"], "false")

    def test_review_queue_never_promotes_interval_to_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lifespans.csv"
            fields = ("camis", "dba", "address", "geoid", "nta_code", "borough", "cuisine", "open_date",
                      "clean_cohort", "survival_lower_years", "survival_upper_years",
                      "first_snapshot", "last_snapshot", "next_snapshot", "first_operational_prepermit",
                      "first_cycle_inspection", "followup_inspection_365_455", "observation_status")
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"camis": "1", "dba": "One", "address": "10 Main St", "geoid": "36047000100",
                                 "nta_code": "BK0101", "borough": "Brooklyn", "open_date": "2023-01-01",
                                 "clean_cohort": "true", "survival_lower_years": "0.5",
                                 "survival_upper_years": "0.9", "first_snapshot": "2023-08-10",
                                 "last_snapshot": "2023-08-10", "next_snapshot": "2023-11-17",
                                 "first_operational_prepermit": "2023-01-01",
                                 "first_cycle_inspection": "2023-09-01", "cuisine": "American",
                                 "followup_inspection_365_455": "", "observation_status": "disappeared_between_snapshots"})
            rows, counts = make_review_queue(path)
            self.assertEqual(counts["snapshot_exit_within_year_review"], 1)
            self.assertEqual(rows[0]["outcome_status"], "unresolved")
            self.assertEqual(rows[0]["verification_status"], "independent_verification_required")
            self.assertEqual(rows[0]["baseline_operating"], "")
            self.assertEqual(rows[0]["as_of_date"], "")
            self.assertEqual(rows[0]["first_cycle_inspection_lead"], "2023-09-01")


if __name__ == "__main__":
    unittest.main()
