import unittest
import numpy as np
import pandas as pd
from scipy.stats import norm

from customer_access import AccessConcept, load_config
from test_customer_access import fixtures
from network_huff import competitor_stock, network_scenarios, scenario_shares
from survival_metrics import (interval_nll, fit_constant_aft, evaluate_predictions,
                              comparable_concordance, paired_concordance_delta)
from evaluate_model_features import gap_inventory, rank_comparison


class HuffEvaluationTests(unittest.TestCase):
    def test_choice_mass_and_independent_entrant_scenarios(self):
        candidate = np.array([[1, 2], [2, 1.]])
        entrant, competitors, outside = scenario_shares(candidate, [2, 3])
        np.testing.assert_allclose(entrant + competitors + outside, 1)
        alone = scenario_shares(candidate[:1], [2, 3])[0]
        np.testing.assert_allclose(entrant[:1], alone)
        more_competition = scenario_shares(candidate, [4, 6])[0]
        self.assertTrue((more_competition < entrant).all())
        self.assertTrue((scenario_shares(candidate, [2, 3], outside=2)[0] < entrant).all())

    def test_invalid_utilities_rejected(self):
        for candidate, stock, outside in [([[np.nan]], [1], 1), ([[-1]], [1], 1), ([[1]], [1], 0), ([[1]], [-1], 1)]:
            with self.assertRaises(ValueError):
                scenario_shares(candidate, stock, outside)

    def test_ambiguous_cuisines_not_asserted_to_be_known(self):
        restaurants = pd.DataFrame({"camis": ["1", "2", "3"], "geoid": ["36061000100"] * 3,
            "active_establishment": [True] * 3, "cuisine_description": ["Italian", "Latin American", "Other"],
            "dba": ["Restaurant", "Restaurant", "Restaurant"]})
        stock, audit, labels = competitor_stock(restaurants, pd.Series(["36061000100"]), "Italian")
        self.assertEqual(stock[0], 1)
        self.assertEqual(audit["excluded_rows"], 2)
        self.assertEqual(len(labels), 3)
        with self.assertRaises(ValueError):
            competitor_stock(pd.concat([restaurants, restaurants]), pd.Series(["36061000100"]), "Italian")

    def test_network_coverage_and_no_fabricated_visits(self):
        origins, candidates, routes = fixtures()
        tracts = candidates.copy()
        tracts["property_id"] = origins.geoid
        result, audit = network_scenarios(origins, candidates, routes, tracts, routes,
            np.array([1., 2., 1.]), AccessConcept(), load_config())
        self.assertTrue(result.huff_percentile.between(0, 100).all())
        self.assertTrue(result.forecast_visits.isna().all())
        self.assertLess(audit["maximum_choice_mass_error"], 1e-12)
        incomplete = routes.copy()
        incomplete[1, 0] = np.nan
        missing, _ = network_scenarios(origins, candidates, routes, tracts, incomplete,
            np.array([1., 2., 1.]), AccessConcept(), load_config())
        self.assertTrue(missing.huff_percentile.isna().all())
        self.assertTrue(missing.status.eq("competitor_routing_incomplete").all())

    def test_more_competition_reduces_captured_opportunities(self):
        origins, candidates, routes = fixtures()
        tracts = candidates.copy()
        tracts["property_id"] = origins.geoid
        args = (origins, candidates, routes, tracts, routes)
        before, _ = network_scenarios(*args, np.ones(3), AccessConcept(), load_config())
        after, _ = network_scenarios(*args, np.ones(3) * 3, AccessConcept(), load_config())
        self.assertTrue((after.huff_opportunities < before.huff_opportunities).all())

    def test_rank_comparison_reports_common_coverage(self):
        result = rank_comparison(pd.Series([1, 2, np.nan]), pd.Series([1, 2, 3]))
        self.assertEqual(result["paired_rows"], 2)
        self.assertEqual(result["top_k_retention"], 1)

    def test_zero_coordinates_never_enter_legacy_gap(self):
        rows = pd.DataFrame({"cuisine_50": ["Italian"] * 3,
                             "latitude": [40.7, 0, np.nan], "longitude": [-74, 0, -74]})
        self.assertEqual(gap_inventory(rows).index.tolist(), [0])


class SurvivalMetricsTests(unittest.TestCase):
    def test_paired_delta_uses_matched_outcomes_and_resamples(self):
        result = paired_concordance_delta([3, 2, 1], [1, 2, 3], [1, 2, 3], [1, 2, 3], ["A", "B", "C"])
        self.assertEqual(result["candidate_minus_reference"], 1)
        self.assertEqual(result["paired_nta_bootstrap_95_ci"], [1, 1])
        with self.assertRaises(ValueError):
            paired_concordance_delta([1], [1, 2], [1], [2], ["A"])
    def test_exact_interval_and_censored_likelihoods(self):
        got = interval_nll([2, 2, 2], [1, 1, 1], [1, 3, np.inf])
        self.assertAlmostEqual(got[0], -norm.logpdf(np.log(.5)))
        self.assertAlmostEqual(got[1], -np.log(norm.cdf(np.log(1.5)) - norm.cdf(np.log(.5))))
        self.assertAlmostEqual(got[2], -norm.logsf(np.log(.5)))
        self.assertTrue(np.isfinite(interval_nll([1], [100], [101])).all())

    def test_baseline_fit_and_no_all_censored_fit(self):
        median = fit_constant_aft([1, 2, 4], [1, 2, 4])
        self.assertAlmostEqual(median, 2, places=5)
        with self.assertRaises(ValueError):
            fit_constant_aft([1, 2], [np.inf, np.inf])

    def test_concordance_direction_ties_and_cluster_uncertainty(self):
        a = comparable_concordance([1, 2, 3], [1, 2, 3], [1, 2, 3], ["A", "B", "C"])
        self.assertEqual(a["estimate"], 1)
        self.assertEqual(a["nta_cluster_bootstrap_95_ci"], [1, 1])
        b = comparable_concordance([1, 1, 1], [1, 2, 3], [1, 2, 3])
        self.assertEqual(b["estimate"], .5)
        c = comparable_concordance([3, 2, 1], [1, 2, 3], [1, 2, 3])
        self.assertEqual(c["estimate"], 0)

    def test_early_censoring_and_straddling_not_survivors(self):
        result = evaluate_predictions([2, 2, 2, 2], [1, 2, 1, 4], [np.inf, 4, 2, np.inf])
        self.assertEqual(result["resolved_3yr_rows"], 2)
        self.assertEqual(result["unresolved_3yr_rows"], 2)
        self.assertIn("not IPCW", result["calibration_scope"])
        unresolved = evaluate_predictions([2], [1], [np.inf])
        self.assertIsNone(unresolved["resolved_subset_brier_3yr"])

    def test_invalid_interval_bounds_rejected(self):
        for lower, upper in [([0], [1]), ([2], [1]), ([1], [np.nan])]:
            with self.assertRaises(ValueError):
                interval_nll([1], lower, upper)


if __name__ == "__main__":
    unittest.main()
