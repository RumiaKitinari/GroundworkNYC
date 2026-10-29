import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import app


class PropertyDataTests(unittest.TestCase):
    def setUp(self):
        self.location = {"id": "tract-1", "geoid": "tract-1", "name": "Test Tract", "borough": "Queens", "opportunity": 78, "confidence_score": 70, "latitude": 40.7, "longitude": -73.9}

    def test_transaction_filters_and_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verified_properties.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["listing_id", "geoid", "transaction", "address", "asking_rent_monthly", "asking_price", "broker_name", "source_url", "checked_at"])
                writer.writeheader()
                writer.writerow({"listing_id": "lease-1", "geoid": "tract-1", "transaction": "lease", "address": "1 Test Street", "asking_rent_monthly": "12000", "broker_name": "Example Broker", "source_url": "https://example.com/lease", "checked_at": date.today().isoformat()})
                writer.writerow({"listing_id": "sale-1", "geoid": "tract-1", "transaction": "purchase", "address": "2 Test Street", "asking_price": "2100000", "source_url": "https://example.com/sale", "checked_at": date.today().isoformat()})
            with patch.object(app, "LISTINGS_PATH", path), patch.object(app, "integrated_package", return_value={"storefronts": []}):
                lease = app.matching_properties([self.location], "lease", 18000, 3000000)
                purchase = app.matching_properties([self.location], "purchase", 18000, 3000000)
                both = app.matching_properties([self.location], "either", 18000, 3000000)
        self.assertEqual([row["transaction"] for row in lease], ["lease"])
        self.assertEqual([row["transaction"] for row in purchase], ["purchase"])
        self.assertEqual(len(both), 2)
        self.assertEqual(lease[0]["asking_rent"], 12000)
        self.assertEqual(purchase[0]["asking_price"], 2100000)
        self.assertIsNone(lease[0]["latitude"])
        self.assertIsNone(lease[0]["longitude"])

    def test_registry_record_is_not_advertised_for_sale(self):
        storefront = {"geoid": "tract-1", "borough_block_lot": "123", "property_street_address_or": "3 Test Street", "vacant_current": "True"}
        with patch.object(app, "LISTINGS_PATH", Path("/nonexistent/verified_properties.csv")), patch.object(app, "integrated_package", return_value={"storefronts": [storefront]}):
            purchase = app.matching_properties([self.location], "purchase", 18000, 3000000)
            lead = app.matching_properties([self.location], "lease", 18000, 3000000)[0]
        self.assertEqual(purchase, [])
        self.assertEqual(lead["transaction"], "unknown")
        self.assertIsNone(lead["asking_price"])
        self.assertEqual(lead["transaction_label"], "Storefront Research")

    def test_listing_budget_filters_before_ranking(self):
        outside_top = dict(self.location, id="tract-2", geoid="tract-2", name="Other Tract", opportunity=62)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verified_properties.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["listing_id", "geoid", "transaction", "address", "asking_rent_monthly", "source_url", "checked_at"])
                writer.writeheader()
                writer.writerow({"listing_id": "affordable", "geoid": "tract-2", "transaction": "lease", "address": "2 Test Street", "asking_rent_monthly": "12000", "source_url": "https://example.com/a", "checked_at": date.today().isoformat()})
                writer.writerow({"listing_id": "over-budget", "geoid": "tract-1", "transaction": "lease", "address": "1 Test Street", "asking_rent_monthly": "30000", "source_url": "https://example.com/b", "checked_at": date.today().isoformat()})
            with patch.object(app, "LISTINGS_PATH", path), patch.object(app, "integrated_package", return_value={"storefronts": []}):
                results = app.matching_properties([self.location, outside_top], "lease", 18000, 3000000)
        self.assertEqual([row["id"] for row in results], ["affordable"])
        self.assertEqual(results[0]["location_name"], "Other Tract")

    def test_stale_listing_is_not_presented_as_current(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verified_properties.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["listing_id", "geoid", "transaction", "address", "asking_rent_monthly", "source_url", "checked_at"])
                writer.writeheader()
                writer.writerow({"listing_id": "stale", "geoid": "tract-1", "transaction": "lease", "address": "1 Test Street", "asking_rent_monthly": "12000", "source_url": "https://example.com/a", "checked_at": (date.today() - timedelta(days=91)).isoformat()})
            with patch.object(app, "LISTINGS_PATH", path), patch.object(app, "integrated_package", return_value={"storefronts": []}):
                results = app.matching_properties([self.location], "lease", 18000, 3000000)
        self.assertEqual(results, [])

    def test_listing_photo_requires_explicit_display_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verified_properties.csv"
            fields = ["listing_id", "geoid", "transaction", "address", "asking_rent_monthly", "source_url", "checked_at", "image_url", "photo_display_permission"]
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"listing_id": "photo", "geoid": "tract-1", "transaction": "lease", "address": "1 Test Street",
                                 "asking_rent_monthly": "12000", "source_url": "https://example.com/a",
                                 "checked_at": date.today().isoformat(), "image_url": "https://example.com/photo.jpg"})
            with patch.object(app, "LISTINGS_PATH", path), patch.object(app, "integrated_package", return_value={"storefronts": []}):
                without_rights = app.matching_properties([self.location], "lease", 18000, 3000000)
            with path.open("a", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writerow({"listing_id": "photo-rights", "geoid": "tract-1", "transaction": "lease", "address": "2 Test Street",
                                 "asking_rent_monthly": "12000", "source_url": "https://example.com/b",
                                 "checked_at": date.today().isoformat(), "image_url": "https://example.com/photo.jpg",
                                 "photo_display_permission": "yes"})
            with patch.object(app, "LISTINGS_PATH", path), patch.object(app, "integrated_package", return_value={"storefronts": []}):
                with_rights = app.matching_properties([self.location], "lease", 18000, 3000000)
        self.assertEqual(without_rights[0]["image"], "")
        self.assertEqual([row["image"] for row in with_rights], ["", "https://example.com/photo.jpg"])


if __name__ == "__main__":
    unittest.main()
