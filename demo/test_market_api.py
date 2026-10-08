import csv
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import app


class MarketApiTests(unittest.TestCase):
    def setUp(self):
        self.package = {
            "tracts": [{"geoid": "36061000100", "tract_label": "1", "nta_code": "MN01", "nta_name": "Test Market"}],
            "restaurants": [
                {"camis": "1", "geoid": "36061000100", "nta": "MN01", "active_establishment": "true", "dba": "Korean Kitchen", "building": "12", "street": "MAIN ST", "cuisine_description": "Korean"},
                {"camis": "2", "geoid": "36061000100", "nta": "MN01", "active_establishment": "true", "dba": "Other Cafe", "cuisine_description": "Coffee/Tea"},
                {"camis": "1", "geoid": "36061000100", "nta": "MN01", "active_establishment": "true", "dba": "Korean Kitchen", "cuisine_description": "Korean"},
                {"camis": "3", "geoid": "36061000200", "nta": "MN01", "active_establishment": "true", "dba": "Nearby Korean", "cuisine_description": "Korean"},
                {"camis": "4", "geoid": "36061000100", "nta": "MN01", "active_establishment": "false", "dba": "Closed", "cuisine_description": "Korean"},
            ],
        }

    def test_competition_uses_active_deduplicated_records(self):
        with patch.object(app, "integrated_package", return_value=self.package), app.app.test_client() as client:
            response = client.get("/api/locations/36061000100/competition?cuisine=korean")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["tract_restaurant_count"], 2)
        self.assertEqual(response.json["tract_same_cuisine_count"], 1)
        self.assertEqual(response.json["neighborhood_same_cuisine_count"], 2)
        self.assertEqual(response.json["restaurants"][0]["name"], "Korean Kitchen")

    def test_invalid_location_and_cuisine_are_rejected(self):
        with patch.object(app, "integrated_package", return_value=self.package), app.app.test_client() as client:
            self.assertEqual(client.get("/api/locations/not-a-geoid/competition").status_code, 400)
            self.assertEqual(client.get("/api/locations/36061000100/competition?cuisine=unknown").status_code, 400)
            self.assertEqual(client.get("/api/locations/36061000999/competition").status_code, 404)

    def test_source_register_uses_catalog_values(self):
        catalog = {"sources": [{"source": "Example Transit", "vintage": "2025", "native_grain": "Station",
                                "purpose": "access", "coverage": "one week", "url": "https://example.com/source"}]}
        with patch.object(app, "integrated_package", return_value=catalog):
            sources = app.data_feeds()
        self.assertEqual(sources[0]["coverage"], "one week")
        self.assertEqual(sources[0]["url"], "https://example.com/source")
        self.assertNotIn("signal", sources[0])

    def test_concept_image_manifest_only_lists_known_images(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as private:
            for name in ("korean.jpg", "unknown.jpg"):
                (Path(folder) / name).touch()
            (Path(private) / "steakhouse.png").write_bytes(b"test")
            with patch.object(app, "CONCEPT_IMAGE_DIR", Path(folder)), patch.object(app, "PRIVATE_CONCEPT_IMAGE_DIR", Path(private)), app.app.test_client() as client:
                response = client.get("/api/concepts/images")
                image = client.get("/api/concepts/image/steakhouse.png")
                rejected = client.get("/api/concepts/image/unknown.jpg")
                image.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["images"], {
            "korean": "/static/images/concepts/korean.jpg",
            "steakhouse": "/api/concepts/image/steakhouse.png",
        })
        self.assertEqual(image.status_code, 200)
        self.assertEqual(rejected.status_code, 404)

    def test_source_limitations_reflect_loaded_listing_fields(self):
        values = app.unsupported_values([{"lead_type": "listing", "transaction": "lease", "asking_rent": 12000, "image": "https://example.com/photo.jpg"}])
        self.assertNotIn("Current Lease Asking Rent", values)
        self.assertNotIn("Listing Photos", values)
        self.assertIn("Current Sale Asking Price", values)

    def test_saved_location_can_be_returned_outside_top_ranking(self):
        all_rows = app.tuned_locations("restaurant", 18000, limit=None)
        saved_id = all_rows[-1]["id"]
        with app.app.test_client() as client:
            response = client.get(f"/api/dashboard?profile=restaurant&rent_cap=18000&saved_id={saved_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json["saved_locations"]], [saved_id])
        self.assertNotIn(saved_id, [row["id"] for row in response.json["locations"]])

    def test_dashboard_keeps_reported_rent_separate_from_listings(self):
        with app.app.test_client() as client:
            response = client.get("/api/dashboard?profile=restaurant&rent_cap=18000")
        self.assertEqual(response.status_code, 200)
        benchmarks = response.json["rent_benchmarks"]
        self.assertEqual(benchmarks["status"], "available")
        self.assertEqual(benchmarks["reporting_year"], 2024)
        self.assertGreater(benchmarks["tracts_with_reported_median"], 1000)
        self.assertTrue(set(benchmarks["by_geoid"]).issubset({row["id"] for row in response.json["locations"]}))
        for row in benchmarks["by_geoid"].values():
            self.assertIn("reported_median_monthly_rent_psf", row)
            self.assertNotIn("asking_rent", row)

    def test_public_opportunity_is_source_linked_but_not_confirmed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = app.PROJECT_ROOT / "data/listings/public_opportunities.csv"
            with source.open(newline="") as stream:
                row = next(csv.DictReader(stream))
            row["checked_at"] = app.date.today().isoformat()
            target = Path(folder) / "public_opportunities.csv"
            with target.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            with patch.object(app, "LISTINGS_PATH", Path(folder) / "verified_properties.csv"), app.app.test_client() as client:
                response = client.get("/api/dashboard?profile=restaurant&rent_cap=18000&deal_type=lease")
        self.assertEqual(response.status_code, 200)
        nycha = next(row for row in response.json["properties"] if row["id"] == "nycha-smith-houses-store-1")
        self.assertEqual(nycha["asking_rent"], 11314.5)
        self.assertEqual(nycha["price_label"], "$11,314.50/Month")
        self.assertEqual(nycha["geoid"], "36061002500")
        self.assertEqual(nycha["source_type"], "official_public_page")
        self.assertIn("Confirm With NYCHA", nycha["availability"])
        self.assertEqual(nycha["image"], "")
        self.assertIn("Confirmed Property Availability", response.json["meta"]["unsupported_values"])

    def test_nycha_public_opportunity_is_not_offered_for_bar_profile(self):
        with app.app.test_client() as client:
            response = client.get("/api/dashboard?profile=bar&rent_cap=18000&deal_type=lease")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("nycha-smith-houses-store-1", {row["id"] for row in response.json["properties"]})


if __name__ == "__main__":
    unittest.main()
