import random
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import Polygon

import app
from generate_synthetic_properties import PRIME_ANCHORS, context_and_rate, make_property, money, weighted_median


class SyntheticPropertyTests(unittest.TestCase):
    def setUp(self):
        self.geometry = Polygon([(-74.1, 40.7), (-73.9, 40.7), (-73.9, 40.9), (-74.1, 40.9)])
        self.tract = {"geoid": "tract-1", "borough": "Queens", "nta_code": "QN01",
                      "nta_name": "Astoria", "reported_median_monthly_rent_psf": "4",
                      "rent_reporting_year": "2024"}

    def test_generation_is_deterministic_and_financially_consistent(self):
        rents = {("Queens", "QN01"): [(48, 10, "2024"), (54, 30, "2024"), (60, 10, "2024")]}
        lease = make_property(self.tract, self.geometry, rents, "lease", 1, random.Random(440), "release-1", 440)
        repeat = make_property(self.tract, self.geometry, rents, "lease", 1, random.Random(440), "release-1", 440)
        sale = make_property(self.tract, self.geometry, rents, "purchase", 2, random.Random(440), "release-1", 440)
        self.assertEqual(lease, repeat)
        self.assertEqual(lease["monthly_rent"], money(lease["annual_rent_psf"] * lease["available_sqft"] / 12))
        self.assertEqual(sale["asking_price"], sale["asking_price_psf"] * sale["available_sqft"])
        self.assertEqual(sale["monthly_rent"], "")
        self.assertEqual(lease["asking_price"], "")
        self.assertEqual(lease["location_precision"], "tract_approximate")
        self.assertEqual(lease["rent_context_year"], "2024")
        self.assertIn(sale["building_type"], {"Retail Condominium", "Stand-Alone Retail"})
        self.assertEqual(sale["floor"], "Ground")

    def test_weighted_neighborhood_rent_and_space_dimensions(self):
        self.assertEqual(weighted_median([(40, 1), (80, 9), (160, 1)]), 80)
        rents = {("Queens", "QN01"): [(48, 10, "2024"), (54, 30, "2024")]}
        for seed in range(100):
            scenario = make_property(self.tract, self.geometry, rents, "lease", seed + 1,
                                     random.Random(seed), "release-1", seed)
            self.assertLessEqual(scenario["available_sqft"] / scenario["frontage_ft"], 110)
            self.assertLessEqual(scenario["frontage_ft"], 80)

    def test_published_corridor_anchors_are_not_assigned_to_other_neighborhoods(self):
        self.assertNotIn("Midtown-Times Square", PRIME_ANCHORS)
        self.assertNotIn("Chelsea-Hudson Yards", PRIME_ANCHORS)

    def test_neighborhood_context_uses_latest_available_reporting_year(self):
        tract = dict(self.tract, reported_median_monthly_rent_psf="")
        rents = {("Queens", "QN01"): [(42, 20, "2024"), (60, 10, "2025"), (72, 30, "2025")]}
        result = context_and_rate(tract, rents, random.Random(23), 1800, "Ground", False, "Buildout-Ready")
        self.assertEqual(result[3], "neighborhood")
        self.assertEqual(result[6], "2025")
        fallback = make_property(tract, self.geometry, {}, "lease", 1, random.Random(23), "release-1", 23)
        self.assertEqual(fallback["rent_context_year"], "")
        self.assertTrue(fallback["pricing_basis"].startswith("Modeled borough rent baseline"))

    def test_neighborhood_context_not_borough_average(self):
        soho = dict(self.tract, borough="Manhattan", nta_code="MN24", nta_name="SoHo-Little Italy-Hudson Square",
                    reported_median_monthly_rent_psf="13")
        rents = {("Manhattan", "MN24"): [(150, 10, "2024"), (156, 10, "2024"), (180, 10, "2024")],
                 ("Queens", "QN01"): [(42, 10, "2024"), (48, 10, "2024"), (54, 10, "2024")]}
        soho_rate = context_and_rate(soho, rents, random.Random(23), 2000, "Ground", False, "Buildout-Ready")[0]
        queens_rate = context_and_rate(self.tract, rents, random.Random(23), 2000, "Ground", False, "Buildout-Ready")[0]
        self.assertGreater(soho_rate, queens_rate * 2)

    def test_api_keeps_scenarios_separate_from_listings(self):
        scenario = make_property(self.tract, self.geometry, {("Queens", "QN01"): [(48, 10, "2024"), (54, 10, "2024")]},
                                 "lease", 1, random.Random(440), "release-1", 440)
        scenario["monthly_rent"] = Decimal("12000.00")
        location = {"id": "tract-1", "geoid": "tract-1", "name": "Astoria Tract",
                    "borough": "Queens", "opportunity": 78, "confidence_score": 70}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(app, "LISTINGS_PATH", Path(folder) / "verified_properties.csv"), \
                patch.object(app, "load_published_inventory", return_value=(scenario,)), \
                patch.object(app, "integrated_package", return_value={"storefronts": []}):
            results = app.matching_properties([location], "lease", 18000, 3000000)
            over_budget = app.matching_properties([location], "lease", 10000, 3000000)
        self.assertEqual(len(results), 1)
        self.assertEqual(over_budget, [])
        self.assertEqual(results[0]["lead_type"], "synthetic")
        self.assertEqual(results[0]["source_type"], "synthetic_demonstration")
        self.assertIsNone(results[0]["source_url"])
        self.assertIsNone(results[0]["broker_contact"])
        self.assertIsNone(results[0]["checked_at"])
        self.assertEqual(results[0]["site_evidence"]["status"], "unavailable")

    def test_dashboard_accepts_premium_corridor_budget(self):
        with app.app.test_client() as client:
            accepted = client.get("/api/dashboard?rent_cap=100000&borough=Manhattan")
            rejected = client.get("/api/dashboard?rent_cap=100001")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 400)
        self.assertTrue(any(row["lead_type"] == "synthetic" for row in accepted.json["properties"]))
        locations = {row["id"]: row for row in accepted.json["property_locations"]}
        self.assertTrue(all(row["location_id"] in locations for row in accepted.json["properties"]))
        self.assertTrue(all(row["location_score"] == locations[row["location_id"]]["opportunity"] for row in accepted.json["properties"]))
        self.assertFalse(accepted.json["property_search"]["synthetic_results_truncated"])

    def test_valid_scenarios_are_not_removed_by_shortlist_or_neighborhood_caps(self):
        rows = [{"id": str(index), "borough": "Queens", "neighborhood": "Astoria",
                 "lead_type": "synthetic", "fit_score": 70, "property_match_score": index}
                for index in range(80)]
        selected = app.select_property_candidates(rows)
        self.assertEqual(len(selected), 80)
        self.assertEqual(selected[0]["id"], "79")

    def test_access_sort_uses_property_access_not_tract_access(self):
        with app.app.test_client() as client:
            response = client.get("/api/dashboard?sort_by=inverse_walkability")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["property_search"]["sort_basis"], "property_customer_access")
        values = [row["customer_access"]["index"] for row in response.json["properties"]
                  if row["customer_access"].get("index") is not None]
        self.assertEqual(values, sorted(values, reverse=True))


if __name__ == "__main__":
    unittest.main()
