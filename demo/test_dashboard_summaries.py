import unittest

from app import market_gap_rows


class DashboardSummaryTests(unittest.TestCase):
    def test_missing_walkability_does_not_break_or_become_zero(self):
        row = {"competition": 40, "activity": 70, "whitespace": 60,
               "customer": 65, "transit": 80, "walkability": None, "cost": 75}
        summary = market_gap_rows([row])
        self.assertEqual(summary[2]["gap_label"], "Walkability Unavailable")
        self.assertIsNone(summary[2]["score"])


if __name__ == "__main__":
    unittest.main()
