import unittest

from app import market_gap_rows, score_comparison


class DashboardSummaryTests(unittest.TestCase):
    def test_missing_walkability_does_not_break_or_become_zero(self):
        row = {"competition": 40, "activity": 70, "whitespace": 60,
               "customer": 65, "transit": 80, "walkability": None, "cost": 75}
        summary = market_gap_rows([row])
        self.assertEqual(summary[2]["gap_label"], "Walkability Unavailable")
        self.assertIsNone(summary[2]["score"])


if __name__ == "__main__":
    unittest.main()


def test_comparison_uses_full_population_not_displayed_leaders():
    rows = [{"opportunity": score, "assessment_policy": {"recommendation_eligible": True}} for score in range(100)]
    result = score_comparison(rows, "Queens", "opportunity")
    assert result["count"] == 100
    assert result["mean"] == result["median"] == 49.5
    assert result["median"] != score_comparison(rows[-24:], "Queens", "opportunity")["median"]
    assert result["geography"] == "Queens"


def test_comparison_excludes_missing_invalid_and_ineligible_access():
    rows = [{"inverse_walkability": score, "assessment_policy": {"recommendation_eligible": True}}
            for score in [0, 20, 70, None, float("nan"), float("inf"), True]]
    rows.append({"inverse_walkability": 100, "assessment_policy": {"recommendation_eligible": False}})
    result = score_comparison(rows, "", "inverse_walkability")
    assert result["metric"] == "inverse_walkability"
    assert result["count"] == 3
    assert result["median"] == 20
    assert result["mean"] == 30
    assert score_comparison([], "", "opportunity")["median"] is None
