import csv
import unittest
from collections import Counter

from app import INTEGRATED_DATA_DIR, app, integrated_package, source_number


def indexed(filename):
    with (INTEGRATED_DATA_DIR / filename).open(newline="", encoding="utf-8-sig") as stream:
        return {row["geoid"]: row for row in csv.DictReader(stream)}


class TransitStorefrontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ids = {row["geoid"] for row in integrated_package()["tracts"]}
        cls.subway = indexed("features/tract_subway_access.csv")
        cls.bike = indexed("features/tract_citibike_activity.csv")
        cls.pedestrian = indexed("features/tract_pedestrian_access.csv")
        cls.taxi = indexed("features/tract_taxi_activity.csv")

    def test_transit_values_match_source_and_missing_is_not_zero(self):
        samples = [next(id for id in self.ids if self.bike[id]["citibike_departures_august_2026"] and self.taxi[id]["pickups_may_2026"]),
                   next(id for id in self.ids if not self.bike[id]["citibike_departures_august_2026"]),
                   next(id for id in self.ids if not self.taxi[id]["pickups_may_2026"]),
                   next(id for id in self.ids if self.bike[id]["nearest_citibike_departures_august_2026"] == "0")]
        with app.test_client() as client:
            for geoid in samples:
                with self.subTest(geoid=geoid):
                    result = client.get(f"/api/areas/{geoid}/transit-activity")
                    self.assertEqual(result.status_code, 200)
                    data = result.json
                    self.assertEqual(data["subway"]["nearest_distance_miles"], source_number(self.subway[geoid], "nearest_subway_distance_miles"))
                    self.assertEqual(data["bike"]["departures"], source_number(self.bike[geoid], "citibike_departures_august_2026"))
                    self.assertEqual(data["bike"]["nearest_departures"], source_number(self.bike[geoid], "nearest_citibike_departures_august_2026"))
                    self.assertEqual(data["pedestrian"]["observed_total"], source_number(self.pedestrian[geoid], "nearest_pedestrian_count_site_latest_pedestrian_count_total"))
                    self.assertEqual(data["taxi"]["pickups"], source_number(self.taxi[geoid], "pickups_may_2026"))
                    self.assertEqual(data["taxi"]["zone"], self.taxi[geoid]["taxi_zone"] or None)
                    self.assertEqual(data["subway"]["period"], "2025-03-03 through 2025-03-09")
                    self.assertEqual(data["bike"]["period"], "August 2026")
                    self.assertEqual(data["taxi"]["period"], "May 2026")

    def test_storefront_api_keeps_source_records_and_geography(self):
        with (INTEGRATED_DATA_DIR / "entities/current_storefronts.csv").open(newline="", encoding="utf-8-sig") as stream:
            source = list(csv.DictReader(stream))
        with app.test_client() as client:
            result = client.get("/api/storefronts")
        self.assertEqual(result.status_code, 200)
        data = result.json
        self.assertEqual(data["total"], len(source))
        self.assertEqual(len(data["records"]), len(source))
        self.assertEqual(Counter(row["borough"] for row in data["records"]), Counter(row["borough"] for row in source))
        self.assertEqual(Counter(row["geoid"] for row in data["records"]), Counter(row["geoid"] or None for row in source))
        self.assertEqual(Counter(row["address"] for row in data["records"]), Counter(row["property_street_address_or"] for row in source))
        self.assertEqual(sum(row["vacancy_status"] == "reported_vacant" for row in data["records"]), len(source))
        self.assertEqual(sum(row["vacancy_status"] == "unknown" for row in data["records"]), 0)
        self.assertEqual(data["reporting_years"], ["2025"])
        self.assertEqual(data["filing_due_dates"], ["2025-08-15", "2026-02-15"])

    def test_api_errors(self):
        with app.test_client() as client:
            self.assertEqual(client.get("/api/areas/bad/transit-activity").status_code, 400)
            self.assertEqual(client.get("/api/areas/99999999999/transit-activity").status_code, 404)


if __name__ == "__main__":
    unittest.main()
