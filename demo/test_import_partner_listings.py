import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from import_partner_listings import prepare_rows, publish


class PartnerListingImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        self.geography = self.home / "tracts.geojson"
        self.geography.write_text(json.dumps({"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"geoid": "36061000100"},
            "geometry": {"type": "Polygon", "coordinates": [[[-74.01, 40.70], [-73.99, 40.70],
                                                            [-73.99, 40.72], [-74.01, 40.72], [-74.01, 40.70]]]},
        }]}))
        self.master = self.home / "master.csv"
        self.master.write_text("geoid\n36061000100\n")
        self.source = self.home / "partner.csv"
        self.base = {"listing_id": "one", "transaction": "lease", "address": "1 Test Street",
                     "asking_rent_monthly": "12000", "source_url": "https://broker.example/one",
                     "checked_at": date.today().isoformat(), "latitude": "40.71", "longitude": "-74.0"}

    def write_rows(self, rows):
        fields = sorted(set().union(*(row.keys() for row in rows)))
        with self.source.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def parse(self):
        return prepare_rows(self.source, self.geography, self.master)

    def test_coordinates_assign_tract_and_publish_atomically(self):
        self.write_rows([self.base])
        rows = self.parse()
        self.assertEqual(rows[0]["geoid"], "36061000100")
        self.assertEqual(rows[0]["source_type"], "authorized_partner")
        rights = self.home / "permission.txt"
        rights.write_text("Provider grants display rights for this test.")
        output = publish(rows, self.source, "test-broker", rights, self.home / "authorized")
        with output.open() as stream:
            self.assertEqual(next(csv.DictReader(stream))["listing_id"], "one")
        self.assertEqual(json.loads(output.with_suffix(".json").read_text())["listing_count"], 1)

    def test_rejects_mismatched_tract_without_replacing_prior_snapshot(self):
        self.write_rows([self.base])
        rights = self.home / "permission.txt"
        rights.write_text("Display permission")
        output = publish(self.parse(), self.source, "test-broker", rights, self.home / "authorized")
        original = output.read_bytes()
        self.write_rows([{**self.base, "geoid": "36061000999"}])
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.parse()
        self.assertEqual(output.read_bytes(), original)

    def test_photo_requires_explicit_display_permission(self):
        self.write_rows([{**self.base, "image_url": "https://broker.example/photo.jpg"}])
        with self.assertRaisesRegex(ValueError, "photo_display_permission"):
            self.parse()
        self.write_rows([{**self.base, "image_url": "https://broker.example/photo.jpg",
                          "photo_display_permission": "yes"}])
        with self.assertRaisesRegex(ValueError, "image_rights_reference"):
            self.parse()
        self.write_rows([{**self.base, "image_url": "https://broker.example/photo.jpg",
                          "photo_display_permission": "yes", "image_rights_reference": "provider-photo-grant"}])
        self.assertEqual(self.parse()[0]["image_url"], "https://broker.example/photo.jpg")
        self.assertEqual(self.parse()[0]["photo_display_permission"], "yes")

    def test_missing_rights_file_blocks_publish(self):
        self.write_rows([self.base])
        with self.assertRaisesRegex(ValueError, "permission reference"):
            publish(self.parse(), self.source, "test-broker", self.home / "missing.txt", self.home / "authorized")

    def test_stale_and_zero_rent_are_rejected(self):
        self.write_rows([{**self.base, "asking_rent_monthly": "0"}])
        with self.assertRaisesRegex(ValueError, "positive asking_rent_monthly"):
            self.parse()
        self.write_rows([{**self.base, "checked_at": "2020-01-01"}])
        with self.assertRaisesRegex(ValueError, "90-day"):
            self.parse()

    def test_lease_cannot_carry_a_sale_price(self):
        self.write_rows([{**self.base, "asking_price": "2000000"}])
        with self.assertRaisesRegex(ValueError, "asking_price must be blank"):
            self.parse()


if __name__ == "__main__":
    unittest.main()
