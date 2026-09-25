import unittest

from financials import operating_scenario


class FinancialScenarioTests(unittest.TestCase):
    def test_incomplete_scenario_does_not_invent_sales(self):
        result = operating_scenario({}, 18000, 35, "lease")
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["required_monthly_sales"])
        self.assertIsNone(result["required_covers_per_day"])

    def test_user_assumptions_drive_coverage_target(self):
        values = {"other_fixed_costs": "24000", "variable_cost_pct": "35", "operating_days": "26"}
        result = operating_scenario(values, 18000, 35, "lease")
        self.assertEqual(result["required_monthly_sales"], 64616)
        self.assertEqual(result["required_covers_per_day"], 72)

    def test_invalid_costs_rejected(self):
        with self.assertRaises(ValueError):
            operating_scenario({"other_fixed_costs": "1000", "variable_cost_pct": "95", "operating_days": "26"}, 18000, 35, "lease")


if __name__ == "__main__":
    unittest.main()
