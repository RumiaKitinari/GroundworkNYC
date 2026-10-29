import json
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
import pandas as pd

from customer_access import AccessConcept, access_features, load_config, route_matrix, score_cached_run
from engineer_customer_access import build
from model_feature_catalog import current_context_features


def fixtures():
    origins = pd.DataFrame({
        "geoid": ["36061000100", "36061000200", "36061000300"],
        "centroid_latitude": [40.700, 40.701, 40.702],
        "centroid_longitude": [-74.0, -74.0, -74.0],
        "population_2024": [1000., 2000., 500.], "total_jobs": [200., 1000., 5000.],
        "median_household_income_2024": [40000., 80000., 160000.],
        "national_walkability_index": [12., 14., 16.],
    })
    candidates = pd.DataFrame({"property_id": ["synthetic-a", "synthetic-b", "synthetic-c"],
                               "geoid": origins.geoid, "latitude": origins.centroid_latitude,
                               "longitude": origins.centroid_longitude, "inventory_type": "synthetic"})
    distances = np.array([[0., 500., 1500.], [500., 0., 1000.], [1500., 1000., 0.]])
    return origins, candidates, distances


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.origins, self.candidates, self.distances = fixtures()
        self.config = load_config()

    def features(self, **kwargs):
        return access_features(self.origins, self.candidates, self.distances,
                               AccessConcept(**kwargs), self.config)

    def test_positive_finite_scores_and_no_visits(self):
        result = self.features()
        self.assertTrue(result.customer_access_percentile.between(0, 100).all())
        self.assertTrue(result.visit_forecast.isna().all())
        self.assertTrue(result.inventory_type.eq("synthetic").all())

    def test_longer_distance_reduces_raw_access(self):
        before = self.features()
        self.distances += 100
        after = self.features()
        self.assertTrue((after.customer_access_opportunities < before.customer_access_opportunities).all())

    def test_style_audience_daypart_and_price_react(self):
        baseline = self.features()
        longer = self.features(service_style="fine_dining")
        self.assertTrue((longer.customer_access_opportunities >= baseline.customer_access_opportunities).all())
        expensive = self.features(average_check=110)
        self.assertTrue((expensive.price_adjusted_access_opportunities <= baseline.price_adjusted_access_opportunities).all())
        workers = self.features(audience="workers")
        self.assertFalse(np.allclose(workers.customer_access_opportunities, baseline.customer_access_opportunities))
        lunch = self.features(daypart="lunch")
        self.assertFalse(np.allclose(lunch.customer_access_opportunities, baseline.customer_access_opportunities))

    def test_missing_network_never_becomes_zero(self):
        self.distances[0] = np.nan
        result = self.features()
        self.assertEqual(result.status.iloc[0], "network_unavailable")
        self.assertTrue(pd.isna(result.customer_access_opportunities.iloc[0]))
        self.assertTrue(pd.isna(result.inverse_walkability_percentile.iloc[0]))

    def test_disconnected_routes_are_recorded_zero(self):
        self.distances[0] = np.inf
        result = self.features()
        self.assertEqual(result.customer_access_opportunities.iloc[0], 0)
        self.assertEqual(result.reachable_origin_tracts.iloc[0], 0)

    def test_missing_income_not_free_price_fit(self):
        self.origins["median_household_income_2024"] = np.nan
        result = self.features()
        self.assertTrue(result.price_adjusted_access_opportunities.isna().all())
        self.assertTrue(result.customer_access_opportunities.notna().all())

    def test_missing_population_not_favorable_zero(self):
        self.origins["population_2024"] = np.nan
        result = self.features()
        self.assertTrue(result.status.eq("limited_coverage").all())
        self.assertTrue(result.customer_access_percentile.isna().all())

    def test_source_frames_not_mutated(self):
        original = self.origins.copy(deep=True)
        self.features()
        pd.testing.assert_frame_equal(self.origins, original)

    def test_reordering_preserves_identified_values(self):
        original = self.features().set_index("property_id").customer_access_opportunities
        order = [2, 0, 1]
        other = access_features(self.origins.iloc[order], self.candidates,
                                self.distances[:, order], AccessConcept(), self.config)
        pd.testing.assert_series_equal(original, other.set_index("property_id").customer_access_opportunities)

    def test_invalid_parameters_rejected(self):
        for concept in (AccessConcept(average_check=float("nan")), AccessConcept(average_check=-1),
                        AccessConcept(service_style="unknown")):
            with self.assertRaises(ValueError):
                access_features(self.origins, self.candidates, self.distances, concept, self.config)
        with self.assertRaises(ValueError):
            access_features(self.origins, self.candidates, -self.distances, AccessConcept(), self.config)

    def test_context_units_and_missing_are_explicit(self):
        self.origins["pct_residents_under_18"] = [25, 0, 101]
        self.origins["rideshare_dropoffs_per_sq_mile"] = [100, 0, np.nan]
        result, dictionary = current_context_features(self.origins)
        self.assertEqual(result.resident_under18_share.iloc[0], .25)
        self.assertEqual(result.resident_under18_share.iloc[1], 0)
        self.assertTrue(pd.isna(result.resident_under18_share.iloc[2]))
        self.assertEqual(result.rideshare_allocated_density.iloc[0], np.log1p(100))
        self.assertEqual(result.rideshare_allocated_density.iloc[1], 0)
        self.assertTrue(pd.isna(result.rideshare_allocated_density.iloc[2]))
        self.assertTrue(result.registered_properties_with_vacancy_share.isna().all())
        self.assertTrue(dictionary.role.str.contains("prospective_context_only").all())


class RoutingTests(unittest.TestCase):
    def network(self, directory):
        path = Path(directory) / "network.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE nodes(id INTEGER PRIMARY KEY, latitude REAL, longitude REAL)")
            db.execute("CREATE TABLE edges(source INTEGER, target INTEGER, meters REAL)")
            db.executemany("INSERT INTO nodes VALUES(?,?,?)", [(1,40.7,-74.), (2,40.701,-74.), (3,40.702,-74.)])
            # Deliberately one way; origin->destination, not destination->origin.
            db.execute("INSERT INTO edges VALUES(1,2,112)")
            db.commit()
        return path

    def test_directed_routes_and_disconnection(self):
        origins, candidates, _ = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            matrix, audit = route_matrix(origins, candidates, self.network(tmp), load_config())
        self.assertAlmostEqual(matrix[1,0], 112)
        self.assertTrue(np.isinf(matrix[0,1]))
        self.assertTrue(np.isinf(matrix[1,2]))
        self.assertEqual(audit["nodes"], 3)

    def test_no_silent_euclidean_fallback(self):
        origins, candidates, _ = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                route_matrix(origins, candidates, Path(tmp)/"absent.sqlite", load_config())

    def test_duplicate_and_invalid_points_rejected(self):
        origins, candidates, _ = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            network = self.network(tmp)
            origins.loc[1,"geoid"] = origins.loc[0,"geoid"]
            with self.assertRaises(ValueError):
                route_matrix(origins, candidates, network, load_config())

    def test_reproducible_export_and_cache_integrity(self):
        origins, candidates, _ = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            network = self.network(tmp)
            master, listings = root/"master.csv", root/"listings.csv"
            origins.to_csv(master,index=False)
            candidates.to_csv(listings,index=False)
            first, second = root/"run1", root/"run2"
            result = build(master,listings,network,first)
            self.assertTrue(result["checks_passed"])
            build(master,listings,network,second,reuse=first)
            self.assertEqual((first/"office_lunch.csv").read_bytes(),(second/"office_lunch.csv").read_bytes())
            full = score_cached_run(first,AccessConcept(),candidates,date.today().isoformat())
            subset = score_cached_run(first,AccessConcept(),candidates.iloc[[1]],date.today().isoformat())
            self.assertEqual(full.loc[1,"customer_access_percentile"],subset.loc[1,"customer_access_percentile"])
            with self.assertRaises(ValueError):
                score_cached_run(first,AccessConcept(),candidates,"2020-01-01")
            moved = candidates.copy()
            moved.loc[0,"latitude"] += .0001
            with self.assertRaises(ValueError):
                score_cached_run(first,AccessConcept(),moved,date.today().isoformat())
            with self.assertRaises(FileExistsError):
                build(master,listings,network,first)
            with (first/"routes.npz").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaises(ValueError):
                build(master,listings,network,root/"bad",reuse=first)


if __name__ == "__main__":
    unittest.main()
