import csv
import unittest
from collections import Counter

from app import app, integrated_directory, integrated_package, source_number


def indexed(filename):
    with (integrated_directory() / filename).open(newline="", encoding="utf-8-sig") as stream:
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
        bike_suffix = "latest_month" if "citibike_departures_latest_month" in next(iter(self.bike.values())) else "august_2026"
        taxi_suffix = "latest_month" if "pickups_latest_month" in next(iter(self.taxi.values())) else "may_2026"
        samples = sorted(self.ids)[:6]
        with app.test_client() as client:
            for geoid in samples:
                with self.subTest(geoid=geoid):
                    result = client.get(f"/api/areas/{geoid}/transit-activity")
                    self.assertEqual(result.status_code, 200)
                    data = result.json
                    self.assertEqual(data["subway"]["nearest_distance_miles"], source_number(self.subway[geoid], "nearest_subway_distance_miles"))
                    self.assertEqual(data["bike"]["departures"], source_number(self.bike[geoid], f"citibike_departures_{bike_suffix}"))
                    self.assertEqual(data["bike"]["nearest_departures"], source_number(self.bike[geoid], f"nearest_citibike_departures_{bike_suffix}"))
                    self.assertEqual(data["pedestrian"]["observed_total"], source_number(self.pedestrian[geoid], "nearest_pedestrian_count_site_latest_pedestrian_count_total"))
                    self.assertEqual(data["taxi"]["pickups"], source_number(self.taxi[geoid], f"pickups_{taxi_suffix}"))
                    self.assertEqual(data["taxi"]["zone"], self.taxi[geoid]["taxi_zone"] or None)
                    self.assertEqual(data["subway"]["period"], integrated_package()["subway_vintage"])
                    self.assertTrue(data["bike"]["period"])
                    self.assertTrue(data["taxi"]["period"])
        self.assertIsNone(source_number({"x": ""}, "x"))
        self.assertEqual(source_number({"x": "0"}, "x"), 0)

    def test_storefront_api_keeps_source_records_and_geography(self):
        with (integrated_directory() / "entities/current_storefronts.csv").open(newline="", encoding="utf-8-sig") as stream:
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
        self.assertEqual(sum(row["vacancy_status"] == "reported_vacant" for row in data["records"]), sum(row["vacant_current"].lower() == "true" for row in source))
        self.assertEqual(sum(row["vacancy_status"] == "reported_not_vacant" for row in data["records"]), sum(row["vacant_current"].lower() == "false" for row in source))
        self.assertEqual(data["reporting_years"], sorted({row["reporting_year"] for row in source if row["reporting_year"]}))
        self.assertEqual(data["filing_due_dates"], sorted({row["filing_due_date"] for row in source if row["filing_due_date"]}))

    def test_api_errors(self):
        with app.test_client() as client:
            self.assertEqual(client.get("/api/areas/bad/transit-activity").status_code, 400)
            self.assertEqual(client.get("/api/areas/99999999999/transit-activity").status_code, 404)


if __name__ == "__main__":
    unittest.main()
