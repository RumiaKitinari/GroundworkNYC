import json
import unittest

from research_overture_closures import match_cases


class OvertureEvidenceTests(unittest.TestCase):
    def case(self, **updates):
        return {"business_id": "1", "candidate_name": "Test Cafe", "candidate_address": "123-125 MAIN STREET 10001",
                "borough": "Manhattan", **updates}

    def place(self, **updates):
        return {"overture_id": "gers-1", "name": "Test Cafe", "operating_status": "permanently_closed",
                "confidence": "0", "addresses_json": json.dumps([{"freeform": "123-125 Main St", "postcode": "10001"}]),
                "sources_json": json.dumps([{"dataset": "Foursquare", "update_time": "2026-09-01"}]), **updates}

    def test_closed_zero_confidence_preserved_but_never_verified(self):
        row = match_cases([self.case()], [self.place()], "2026-09-23.1")[0]
        self.assertEqual(row["overture_match_status"], "matched_permanently_closed")
        self.assertTrue(row["foursquare_lineage_present"])
        self.assertFalse(row["independent_confirmation"])
        self.assertFalse(row["training_eligible"])
        self.assertEqual(row["actual_closure_date"], "")

    def test_non_queens_building_ranges_not_collapsed(self):
        place = self.place(addresses_json=json.dumps([{"freeform": "123125 Main St", "postcode": "10001"}]))
        self.assertEqual(match_cases([self.case()], [place], "release")[0]["overture_match_status"], "no_conservative_match")

    def test_queens_hyphenated_addresses_match_and_duplicates_remain_ambiguous(self):
        case = self.case(candidate_address="3812 MAIN ST 11354", borough="Queens")
        place = self.place(addresses_json=json.dumps([{"freeform": "38-12 Main Street", "postcode": "11354"}]))
        self.assertEqual(match_cases([case], [place], "release")[0]["overture_match_status"], "matched_permanently_closed")
        second = dict(place, overture_id="gers-2", operating_status="open")
        self.assertEqual(match_cases([case], [place, second], "release")[0]["overture_match_status"], "ambiguous_multiple_places")


if __name__ == "__main__":
    unittest.main()
