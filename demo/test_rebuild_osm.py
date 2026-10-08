import unittest

from audit_scoring import compare, scenarios, sensitivity_pairs
from rebuild_osm import FoodPOIs, category, inspection_match, per_1000_residents


class RebuildOSMTests(unittest.TestCase):
    def test_category_and_near_duplicate(self):
        self.assertEqual(category({"amenity": "restaurant"}), "restaurant")
        self.assertEqual(category({"shop": "pastry"}), "bakery")
        self.assertEqual(category({"shop": "convenience"}), "")
        geoid = "36061000100"
        handler = FoodPOIs(lambda lon, lat: geoid if lon < -73.9 else "", {geoid: "Manhattan"})
        tags = {"amenity": "restaurant", "name": "Blue Bistro", "cuisine": "italian"}
        handler.accept("node", 1, tags, (40.75, -73.97))
        handler.accept("way", 2, tags, (40.75002, -73.97))
        handler.accept("way", 3, {**tags, "name": "Other Bistro"}, (40.75002, -73.97))
        handler.accept("node", 4, tags, (40.75, -73.8))
        self.assertEqual(len(handler.records), 2)
        self.assertEqual(handler.stats["near_duplicate_removed"], 1)
        self.assertEqual(handler.stats["outside_nyc_tracts"], 1)

    def test_inspection_match_is_quality_audit_only(self):
        poi = {"name": "Blue Bistro", "latitude": 40.75, "longitude": -73.97, "geoid": "36061000100"}
        record = {"dba": "Blue Bistro", "latitude": "40.7501", "longitude": "-73.97",
                  "geoid": "36061000100", "active_establishment": "True"}
        result = inspection_match([poi], [record])
        self.assertEqual(result["named_pois_matched_to_active_inspections"], 1)

    def test_derived_resident_density_uses_refreshed_count(self):
        self.assertEqual(per_1000_residents(12, "3000"), 4)
        self.assertEqual(per_1000_residents(12, ""), "")

    def test_score_audit_covers_independent_concept_dimensions(self):
        names = scenarios()
        dimensions = {item[0] for item in sensitivity_pairs()}
        self.assertEqual(dimensions, {"format", "price", "cuisine", "daypart", "dietary"})
        self.assertIn("price:coffee:$$$$", names)
        result = compare({"a": 50, "b": 60}, {"a": 55, "b": 60})
        self.assertEqual(result["changed_fraction"], .5)
        self.assertEqual(result["median_absolute_change"], 2.5)


if __name__ == "__main__":
    unittest.main()
