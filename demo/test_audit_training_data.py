import unittest
from datetime import date

from audit_training_data import prepare_candidates, quality_audit, rent_audit
from evaluation import HISTORICAL_CORE_FEATURES


class CleaningAuditTests(unittest.TestCase):
    def test_rent_missing_is_not_zero_and_annual_units_are_checked(self):
        master = [{"geoid": "36061000201", "reported_median_monthly_rent_psf": "8",
                   "reported_median_annual_rent_psf": "96"},
                  {"geoid": "36061000600", "reported_median_monthly_rent_psf": "",
                   "reported_median_annual_rent_psf": ""},
                  {"geoid": "36061000700", "reported_median_monthly_rent_psf": "0",
                   "reported_median_annual_rent_psf": "0"}]
        raw = [{"reporting_year": "2024", "aggregate_level_citywide": "Census Tract",
                "aggregate_level_id": "1000201", "median_monthly_rent_per_square": "8"},
               {"reporting_year": "2024", "aggregate_level_citywide": "Census Tract",
                "aggregate_level_id": "1000600", "median_monthly_rent_per_square": "*"}]
        rows, summary = rent_audit(master, raw)
        self.assertEqual(rows[1]["missingness_reason"], "publisher_star_marker")
        self.assertEqual(rows[2]["missingness_reason"], "no_latest_year_source_tract")
        self.assertEqual(summary["source_or_unit_mismatches"], 1)
        self.assertEqual(master[1]["reported_median_monthly_rent_psf"], "")

    def test_quality_checks_preserve_legitimate_zeros_and_review_outliers(self):
        rows = [{"geoid": "36061000201", "test_share": "1.2", "count": "0"},
                {"geoid": "36061000201", "test_share": "nan", "count": "-1"}]
        fields = list(rows[0])
        profiles, issues = quality_audit(rows, fields, {f: {"definition": f} for f in fields})
        rules = {r["rule"] for r in issues}
        self.assertTrue({"invalid_or_duplicate_geoid", "share_outside_zero_one", "nonfinite", "negative_measure"} <= rules)
        self.assertEqual(next(p for p in profiles if p["column"] == "count")["zero_count"], 1)

    def test_candidates_never_take_future_features_or_create_labels(self):
        case = {"business_id": "1", "geoid": "36061000201", "nta_code": "N1", "borough": "Manhattan",
                "candidate_name": "Test Cafe", "candidate_address": "1 MAIN ST 10001",
                "identity_review": "possible_camis_change", "outcome_status": "unresolved",
                "first_cycle_inspection_lead": "2023-06-01"}
        snapshots = {f: [{"available": date(2024, 1, 1), "path": "future.csv", "values": {case["geoid"]: "999"}},
                         {"available": date(2023, 1, 1), "path": "past.csv", "values": {case["geoid"]: "10"}}]
                     for f in HISTORICAL_CORE_FEATURES}
        rows, review = prepare_candidates([case], snapshots)
        self.assertTrue(rows[0]["complete_historical_core"])
        self.assertFalse(rows[0]["training_eligible"])
        self.assertNotIn("y", rows[0])
        self.assertEqual(rows[0][HISTORICAL_CORE_FEATURES[0]], "10")
        self.assertEqual(len(review), 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            prepare_candidates([case, case], snapshots)

    def test_dictionary_units_distinguish_percentage_from_fraction(self):
        rows = [{"geoid": "36061000201", "pct_old": "65", "pct_new": "0.65"}]
        dictionary = {"geoid": {"definition": "ID"}, "pct_old": {"definition": "Percent", "unit": "percent"},
                      "pct_new": {"definition": "Fraction", "unit": "share"}}
        _, issues = quality_audit(rows, list(rows[0]), dictionary)
        self.assertEqual(issues, [])
        rows[0]["pct_new"] = "65"
        _, issues = quality_audit(rows, list(rows[0]), dictionary)
        self.assertEqual(issues[0]["rule"], "share_outside_zero_one")


if __name__ == "__main__":
    unittest.main()
