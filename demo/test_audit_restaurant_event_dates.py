import copy
import unittest

from audit_restaurant_event_dates import audit_cases


class EventDateAuditTests(unittest.TestCase):
    def setUp(self):
        self.cases = [{"business_id": "1", "candidate_name": "Test Cafe", "candidate_address": "10 MAIN ST 10001",
                       "borough": "Manhattan", "first_operational_prepermit": "2023-08-09",
                       "first_cycle_inspection_lead": "", "fsq_marked_closed_dates": "2024-10-08"}]
        self.registry = {"sources": {"opening": {"url": "https://example.org/opening"},
                                     "closure": {"url": "https://example.org/closure"}}, "cases": [{
            "business_id": "1", "candidate_name": "Test Cafe", "candidate_address": "10 Main Street 10001",
            "event_unit": "restaurant_concept_at_address", "source_ids": ["opening", "closure"],
            "opening_bounds": {"lower": "2023-06-01", "upper": "2023-06-30", "source_ids": ["opening"]},
            "reported_closed_by": "2024-04-29", "closure_source_ids": ["closure"], "review_notes": "Identity pending"}]}

    def test_bounds_remain_conditional_without_imputing_exact_dates(self):
        row = audit_cases(self.registry, self.cases)[0]
        self.assertEqual(row["maximum_opening_to_closed_by_days"], 333)
        self.assertTrue(row["prepermit_after_reported_opening_window"])
        self.assertEqual(row["minimum_prepermit_delay_days"], 40)
        self.assertIn("if_identity_and_event_are_accepted", row["conditional_horizon_result"])
        self.assertFalse(row["training_eligible"])
        self.assertFalse(row["operator_identity_verified"])

    def test_closure_by_after_horizon_does_not_prove_survival(self):
        self.registry["cases"][0]["reported_closed_by"] = "2025-01-01"
        self.assertEqual(audit_cases(self.registry, self.cases)[0]["conditional_horizon_result"],
                         "bounds_alone_do_not_determine_first_exit_by_horizon")

    def test_no_opening_bounds_stays_unresolved(self):
        self.registry["cases"][0]["opening_bounds"] = {}
        self.assertEqual(audit_cases(self.registry, self.cases)[0]["conditional_horizon_result"], "unresolved")

    def test_rejects_bad_dates_identity_and_source_attribution(self):
        original = copy.deepcopy(self.registry)
        for key, value in (("candidate_address", "11 Main St 10001"), ("candidate_name", "Different Cafe"),
                           ("reported_closed_by", "2022-01-01"), ("closure_source_ids", []),
                           ("source_ids", ["missing"])):
            with self.subTest(key=key):
                registry = copy.deepcopy(original)
                registry["cases"][0][key] = value
                with self.assertRaises(ValueError):
                    audit_cases(registry, self.cases)

    def test_rejects_duplicate_candidate_or_event_ids(self):
        with self.assertRaises(ValueError):
            audit_cases(self.registry, self.cases * 2)
        self.registry["cases"] *= 2
        with self.assertRaises(ValueError):
            audit_cases(self.registry, self.cases)

    def test_does_not_mutate_inputs(self):
        original = copy.deepcopy((self.registry, self.cases))
        audit_cases(self.registry, self.cases)
        self.assertEqual((self.registry, self.cases), original)


if __name__ == "__main__":
    unittest.main()
