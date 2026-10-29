import csv
import unittest
from collections import Counter

from app import (
    app,
    current_restaurant_records,
    integrated_directory,
    integrated_package,
)


class CompetitionExplorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tracts = {row["geoid"] for row in integrated_package()["tracts"]}
        with (integrated_directory() / "entities" / "current_restaurants.csv").open(newline="", encoding="utf-8-sig") as stream:
            cls.rows = list(csv.DictReader(stream))

    def test_recorded_counts_match_csv_for_several_tracts(self):
        active = current_restaurant_records(self.rows)
        counts = Counter(row["geoid"] for row in active if row["geoid"] in self.tracts)
        samples = [max(counts, key=counts.get), next(geoid for geoid in self.tracts if counts[geoid] == 0),
                   next(geoid for geoid in self.tracts if 1 <= counts[geoid] <= 5)]
        with app.test_client() as client:
            for geoid in samples:
                with self.subTest(geoid=geoid):
                    result = client.get(f"/api/locations/{geoid}/competition?cuisine=italian")
                    self.assertEqual(result.status_code, 200)
                    data = result.json
                    source = [row for row in active if row["geoid"] == geoid]
                    self.assertEqual(data["tract_restaurant_count"], len(source))
                    self.assertTrue(data["borough"])
                    self.assertEqual(len(data["restaurants"]), len(source))
                    self.assertEqual(sum(item["count"] for item in data["cuisine_counts"]), len(source))
                    self.assertEqual(data["same_cuisine_count"], sum(row["cuisine_description"] == "Italian" for row in source))
                    self.assertEqual(data["cuisine_counts"], [
                        {"cuisine": label, "count": count} for label, count in sorted(
                            Counter((row["cuisine_description"] or "").strip() or "Unclassified" for row in source).items(),
                            key=lambda item: (-item[1], item[0].casefold()))])

    def test_animo_address_has_two_distinct_active_ids(self):
        rows = [row for row in self.rows if row["building"] == "1004" and row["street"] == "2 AVENUE"
                and row["dba"].rstrip("!") == "ANIMO"]
        self.assertEqual({row["camis"] for row in rows}, {"50147420", "50179526"})
        self.assertEqual({row["active_establishment"] for row in rows}, {"True"})
        self.assertEqual({row["geoid"] for row in rows}, {"36061009800"})

    def test_latest_duplicate_status_wins_and_unknown_cuisine_remains_visible(self):
        row = {"camis": "123", "geoid": "36061000100", "inspection_date": "2026-01-01",
               "active_establishment": "True", "cuisine_description": "", "dba": "Sample"}
        duplicate = dict(row, inspection_date="2026-02-01", active_establishment="False")
        other = dict(row, camis="456")
        self.assertEqual(current_restaurant_records([row, duplicate, other]), [other])
        self.assertEqual(current_restaurant_records([duplicate, row, other]), [other])

    def test_unsupported_cuisine_and_api_errors(self):
        geoid = next(iter(self.tracts))
        with app.test_client() as client:
            data = client.get(f"/api/locations/{geoid}/competition?cuisine=custom").json
            self.assertFalse(data["cuisine_supported"])
            self.assertIsNone(data["same_cuisine_count"])
            self.assertEqual(client.get("/api/locations/bad/competition").status_code, 400)
            self.assertEqual(client.get("/api/locations/99999999999/competition").status_code, 404)
            self.assertEqual(client.get(f"/api/locations/{geoid}/competition?cuisine=not_real").status_code, 400)


if __name__ == "__main__":
    unittest.main()
