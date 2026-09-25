import unittest

from scoring import Concept, ScreeningModel, resolve_concept


WEIGHTS = {"demand": .24, "customer_fit": .18, "access": .16, "market_gap": .16, "competition_balance": .12, "economics": .14}


def tract(geoid="a", **changes):
    row = dict(geoid=geoid, nta_code="n1", nta_name="Example", population_2024=4000,
               population_density_per_sq_mile=40000, job_density_per_sq_mile=30000,
               national_walkability_index=18, nearest_subway_distance_miles=.1,
               nearest_subway_weekly_ridership=100000, nearest_pedestrian_count_site_distance_miles=.1,
               nearest_pedestrian_count_site_latest_pedestrian_count_total=800,
               citibike_evening_departures_august_2026=1000, median_household_income_2024=150000,
               median_household_income_margin_of_error_2024=10000, restaurant_competitor_count=20,
               retail_area_sqft=100000, mixed_use_parcel_count=50, reported_storefront_property_count=30)
    return dict(row, **changes)


def restaurants(geoid, label, n):
    return [dict(camis=f"{geoid}-{label}-{i}", geoid=geoid, cuisine_description=label, active_establishment="True") for i in range(n)]


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.row = tract()
        self.other = tract("b", population_density_per_sq_mile=1000, job_density_per_sq_mile=1000,
                           median_household_income_2024=35000, nearest_subway_weekly_ridership=1000)
        records = restaurants("a", "Italian", 20) + restaurants("b", "Korean", 20)
        self.model = ScreeningModel([self.row, self.other], records)

    def evaluate(self, row=None, **concept):
        return self.model.evaluate(row or self.row, Concept(**concept), WEIGHTS, "restaurant")

    def test_walkability_does_not_change_with_concept(self):
        first = self.evaluate(cuisine="korean", average_check=15)
        second = self.evaluate(cuisine="italian", average_check=150, service_style="fine_dining")
        self.assertEqual(first["walkability"], second["walkability"])
        self.assertNotEqual(first["business_draw"], second["business_draw"])

    def test_price_and_cuisine_affect_relevant_factors(self):
        affordable = self.evaluate(cuisine="korean", average_check=15)
        expensive = self.evaluate(cuisine="korean", average_check=150)
        saturated = self.evaluate(cuisine="italian", average_check=15)
        self.assertGreater(affordable["components"]["customer_fit"]["score"], expensive["components"]["customer_fit"]["score"])
        self.assertGreater(affordable["components"]["market_gap"]["score"], saturated["components"]["market_gap"]["score"])

    def test_absence_of_cuisine_needs_demand(self):
        high = self.evaluate(cuisine="korean", average_check=35)
        weak = dict(self.row, population_density_per_sq_mile=0, job_density_per_sq_mile=0,
                    median_household_income_2024=10000, nearest_subway_weekly_ridership=0,
                    nearest_pedestrian_count_site_latest_pedestrian_count_total=0,
                    citibike_evening_departures_august_2026=0)
        low = self.evaluate(weak, cuisine="korean", average_check=35)
        self.assertGreater(high["components"]["market_gap"]["score"], low["components"]["market_gap"]["score"])
        self.assertNotEqual(low["concept_evidence"]["positioning"], "Potential Cuisine Gap")

    def test_missing_walkability_is_not_zero_or_good_access(self):
        missing = dict(self.row, national_walkability_index="", nearest_subway_distance_miles="")
        score = self.evaluate(missing)
        self.assertIsNone(score["walkability"])
        self.assertEqual(score["components"]["access"], {"score": 50, "coverage": 0})

    def test_distant_pedestrian_counts_reduce_evidence(self):
        near = self.evaluate()
        far = self.evaluate(dict(self.row, nearest_pedestrian_count_site_distance_miles=5))
        self.assertGreater(near["components"]["demand"]["coverage"], far["components"]["demand"]["coverage"])

    def test_unknown_cuisine_and_duplicates_do_not_create_false_gap(self):
        records = restaurants("a", "", 20)
        model = ScreeningModel([self.row], records + records)
        result = model.evaluate(self.row, Concept(cuisine="korean"), WEIGHTS, "restaurant")
        self.assertEqual(result["concept_evidence"]["cuisine_inventory_count"], 20)
        self.assertEqual(result["concept_evidence"]["cuisine_evidence_coverage"], 0)
        self.assertEqual(result["concept_evidence"]["positioning"], "Limited Cuisine Evidence")
        self.assertIsNone(result["concept_evidence"]["visit_forecast"])

    def test_bad_inputs_rejected(self):
        for args in ({"average_check": "NaN"}, {"average_check": "-5"}, {"cuisine": "made_up"}, {"average_check": "inf"}, {"price_tier": "$$$$$"}):
            with self.assertRaises(ValueError):
                Concept.from_args(args)

    def test_description_identifies_supported_combination(self):
        concept = Concept.from_args({"concept_name": "Vegan Mexican Kitchen", "description": "fast casual with pickup", "profile": "fast_casual", "price_tier": "$$$", "price_mode": "tier", "average_check": "42"})
        self.assertEqual((concept.cuisine, concept.dietary, concept.service_style, concept.average_check), ("mexican", "vegan", "quick_service", 65))

    def test_exact_guest_spend_overrides_price_category(self):
        concept = Concept.from_args({"price_mode": "exact", "price_tier": "$$$", "average_check": "42"})
        self.assertEqual(concept.average_check, 42)

    def test_concept_resolution_keeps_dietary_and_cuisine_distinct(self):
        resolved = resolve_concept({"concept_name": "Vegan Mexican Bistro", "price_mode": "tier"})
        self.assertEqual(resolved["concept"]["cuisine"], "mexican")
        self.assertEqual(resolved["concept"]["dietary"], "vegan")
        self.assertEqual(resolved["profile"], "restaurant")
        self.assertEqual(resolved["field_sources"]["cuisine"], "inferred")

    def test_dietary_only_idea_has_no_made_up_cuisine_demand(self):
        resolved = resolve_concept({"concept_name": "Vegan Restaurant"})
        self.assertEqual(resolved["concept"]["cuisine"], "vegetarian_vegan")
        self.assertEqual(resolved["concept"]["dietary"], "vegan")

    def test_dietary_identity_changes_opportunity_without_changing_walkability(self):
        standard = self.evaluate(cuisine="korean")
        vegan = self.evaluate(cuisine="korean", dietary="vegan")
        self.assertEqual(standard["walkability"], vegan["walkability"])
        self.assertNotEqual(standard["components"]["market_gap"]["score"], vegan["components"]["market_gap"]["score"])
        self.assertIn("Dietary Customer Demand Is Not Measured", vegan["risk_flags"])


if __name__ == "__main__":
    unittest.main()
