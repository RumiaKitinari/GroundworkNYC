import csv
import tempfile
import unittest
from pathlib import Path

from prepare_survival_review import build_review_queue


class SurvivalReviewTests(unittest.TestCase):
    def test_queue_is_balanced_by_borough_but_has_no_outcome_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.csv"
            with master.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["geoid", "nta_code", "borough"])
                writer.writeheader()
                writer.writerows([{"geoid": "1", "nta_code": "MN01", "borough": "Manhattan"},
                                  {"geoid": "2", "nta_code": "BK01", "borough": "Brooklyn"}])
            candidates = root / "candidates.csv"
            with candidates.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["business_id", "geoid", "name", "address",
                                                            "source_url", "last_inspection_on", "closure_order_seen"])
                writer.writeheader()
                for i in range(6):
                    writer.writerow({"business_id": str(i), "geoid": "1" if i < 3 else "2",
                                     "name": f"Restaurant {i}", "address": f"{i} Main St",
                                     "source_url": "https://example.org", "last_inspection_on": "2025-01-01",
                                     "closure_order_seen": "True"})
            queue, counts = build_review_queue(candidates, master, per_borough=2)
            self.assertEqual(len(queue), 4)
            self.assertEqual(counts["source_rows"], 6)
            self.assertTrue(all(row["outcome_status"] == "unresolved" for row in queue))
            self.assertTrue(all(not row["as_of_date"] and not row["baseline_operating"] for row in queue))
            self.assertEqual(queue, build_review_queue(candidates, master, per_borough=2)[0])


if __name__ == "__main__":
    unittest.main()
