import csv
import tempfile
import unittest
from pathlib import Path

from app import app
from menu_catalog import FORMAT_TAGS, catalog, review_signals, suggestions
from scoring import CUISINES


class MenuCatalogTests(unittest.TestCase):
    def test_catalog_has_unique_supported_ids(self):
        items = catalog()
        self.assertGreaterEqual(len(items), 175)
        self.assertEqual(len(items), len({item["id"] for item in items}))
        self.assertTrue({item["cuisine"] for item in items} <= set(CUISINES))
        self.assertTrue(all(item["formats"] and set(item["formats"]) <= {"all", "sit_down", "quick", "bar", "premium", "cafe"} for item in items))

    def test_known_cuisine_format_and_plant_based_candidates(self):
        regular = suggestions("mexican", "restaurant")
        vegan = suggestions("mexican", "restaurant", "vegan")
        self.assertEqual(regular["status"], "available")
        self.assertIn("mexican:al-pastor-tacos", {item["id"] for item in regular["items"]})
        self.assertNotIn("mexican:al-pastor-tacos", {item["id"] for item in vegan["items"]})
        self.assertIn("mexican:mushroom-tacos", {item["id"] for item in vegan["items"]})
        coffee = suggestions("any", "coffee")
        self.assertIn("coffee_tea:cold-brew", {item["id"] for item in coffee["items"]})
        self.assertIn("premium", FORMAT_TAGS["fine_dining"])

    def test_exact_spend_changes_menu_order(self):
        budget = suggestions("italian", "restaurant", average_check=25)
        premium = suggestions("italian", "restaurant", average_check=110)
        budget_names = [item["name"] for item in budget["items"]]
        premium_names = [item["name"] for item in premium["items"]]
        self.assertLess(budget_names.index("Margherita Pizza"), budget_names.index("Osso Buco"))
        self.assertLess(premium_names.index("Osso Buco"), premium_names.index("Margherita Pizza"))

    def test_unsupported_cuisine_does_not_claim_a_catalog(self):
        result = suggestions("taiwanese", "restaurant")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["items"], [])

    def test_review_signal_requires_provenance_and_diverse_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review_mentions.csv"
            fields = ("review_id", "restaurant_id", "dish_id", "review_rating", "observed_on", "source_url", "rights_basis")
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for index in range(20):
                    writer.writerow({"review_id": str(index), "restaurant_id": str(index % 5),
                                     "dish_id": "mexican:mushroom-tacos", "review_rating": 5 if index < 15 else 3,
                                     "observed_on": "2026-09-01", "source_url": "https://example.org/review",
                                     "rights_basis": "Owner-contributed research"})
            result = review_signals(path)
            self.assertEqual(result["mexican:mushroom-tacos"]["mention_count"], 20)
            self.assertEqual(result["mexican:mushroom-tacos"]["positive_mention_share"], .75)
            self.assertIn("not the dish", result["mexican:mushroom-tacos"]["basis"])

    def test_api_uses_concept_and_reports_absent_reviews(self):
        with app.test_client() as client:
            response = client.get("/api/menu/suggestions", query_string={"concept_name": "Korean Bistro", "profile": "restaurant", "cuisine": "korean"})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["concept"]["cuisine"], "korean")
            self.assertIn("korean:bulgogi", {item["id"] for item in data["items"]})
            self.assertEqual(data["review_evidence"], "unavailable")
            self.assertEqual(client.get("/api/menu/suggestions", query_string={"q": "x" * 81}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
