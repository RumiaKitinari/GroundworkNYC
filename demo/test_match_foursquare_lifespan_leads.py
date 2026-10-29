import csv
import tempfile
import unittest
from pathlib import Path

from match_foursquare_lifespan_leads import attach_leads, distance_meters


class FoursquareLifespanLeadTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.places = self.root / "places.csv"
        self.queue = self.root / "queue.csv"
        self.lifespans = self.root / "lifespans.csv"

    def write_csv(self, path, rows):
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def place(self, **changes):
        return {**{"fsq_place_id": "fsq-1", "name": "Cafe Rio", "latitude": "40.70",
                   "longitude": "-73.99", "address": "10 Main St", "postcode": "10001",
                   "date_closed": "2024-02-01"}, **changes}

    def case(self, **changes):
        return {**{"business_id": "123", "candidate_name": "CAFE RIO",
                   "candidate_address": "10 MAIN STREET 10001", "outcome_status": "unresolved"}, **changes}

    def lifespan(self, **changes):
        return {**{"camis": "123", "latitude": "40.70", "longitude": "-73.99",
                   "first_cycle_inspection": "2023-01-01", "last_snapshot": "2023-12-01"}, **changes}

    def test_marked_closed_is_only_review_lead(self):
        self.write_csv(self.places, [self.place()])
        self.write_csv(self.queue, [self.case()])
        self.write_csv(self.lifespans, [self.lifespan()])
        rows, _, audit = attach_leads(self.queue, self.lifespans, self.places)
        self.assertEqual(rows[0]["outcome_status"], "unresolved")
        self.assertEqual(rows[0]["fsq_match_status"], "marked_closed_by_2025_review")
        self.assertEqual(rows[0]["fsq_later_dohmh_snapshot"], "false")
        self.assertEqual(audit["queue_rows"], 1)

    def test_later_active_snapshot_flags_conflict(self):
        self.write_csv(self.places, [self.place()])
        self.write_csv(self.queue, [self.case()])
        self.write_csv(self.lifespans, [self.lifespan(last_snapshot="2024-05-01")])
        rows, _, _ = attach_leads(self.queue, self.lifespans, self.places)
        self.assertEqual(rows[0]["fsq_match_status"], "marked_closed_but_later_dohmh_listing_review")
        self.assertEqual(rows[0]["fsq_later_dohmh_snapshot"], "true")

    def test_prebaseline_and_distant_places_not_failure_labels(self):
        self.write_csv(self.places, [self.place(date_closed="2022-01-01")])
        self.write_csv(self.queue, [self.case()])
        self.write_csv(self.lifespans, [self.lifespan()])
        rows, _, _ = attach_leads(self.queue, self.lifespans, self.places)
        self.assertEqual(rows[0]["fsq_match_status"], "marked_closed_before_cycle_baseline_review")
        self.write_csv(self.places, [self.place(latitude="40.72")])
        rows, _, _ = attach_leads(self.queue, self.lifespans, self.places)
        self.assertEqual(rows[0]["fsq_match_status"], "no_conservative_match")
        self.assertGreater(distance_meters(40.70, -73.99, 40.72, -73.99), 150)

    def test_multiple_exact_places_remain_ambiguous(self):
        self.write_csv(self.places, [self.place(), self.place(fsq_place_id="fsq-2")])
        self.write_csv(self.queue, [self.case()])
        self.write_csv(self.lifespans, [self.lifespan()])
        rows, _, _ = attach_leads(self.queue, self.lifespans, self.places)
        self.assertEqual(rows[0]["fsq_match_status"], "ambiguous_multiple_matches")
        self.assertEqual(rows[0]["fsq_candidate_count"], "2")


if __name__ == "__main__":
    unittest.main()
