import csv
import unittest

from app import integrated_directory, app, integrated_package, resident_worker_profile, source_number


def indexed_rows(filename):
    with (integrated_directory() / filename).open(newline="", encoding="utf-8-sig") as stream:
        return {row["geoid"]: row for row in csv.DictReader(stream)}


class ResidentWorkerProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tracts = {row["geoid"]: row for row in integrated_package()["tracts"]}
        cls.all_tracts = indexed_rows("master_tract_features.csv")
        cls.residents = indexed_rows("features/tract_demographics_income.csv")
        cls.workers = indexed_rows("features/tract_workers.csv")

    def test_api_matches_source_rows_and_marks_missing_income_and_jobs(self):
        sample = [
            next(geoid for geoid in self.tracts if self.residents[geoid]["median_household_income_2024"] and self.workers[geoid]["total_jobs"]),
            next(geoid for geoid in self.tracts if not self.residents[geoid]["median_household_income_2024"]),
            next(geoid for geoid in self.tracts if not self.workers[geoid]["total_jobs"]),
            next(geoid for geoid in self.tracts if self.workers[geoid]["jobs_agriculture_forestry_fishing_hunting"] and source_number(self.workers[geoid], "jobs_agriculture_forestry_fishing_hunting") == 0),
        ]
        with app.test_client() as client:
            for geoid in sample:
                with self.subTest(geoid=geoid):
                    response = client.get(f"/api/areas/{geoid}/profile")
                    self.assertEqual(response.status_code, 200)
                    profile = response.json["market_profile"]
                    resident = self.residents[geoid]
                    worker = self.workers[geoid]
                    self.assertEqual(profile["population"], source_number(resident, "population_2024"))
                    self.assertEqual(profile["median_household_income"], source_number(resident, "median_household_income_2024"))
                    self.assertEqual(profile["income_margin_of_error"], source_number(resident, "median_household_income_margin_of_error_2024"))
                    self.assertEqual(profile["jobs"], source_number(worker, "total_jobs"))
                    self.assertEqual(profile["job_age"]["jobs_age_29_or_younger"], source_number(worker, "jobs_age_29_or_younger"))
                    self.assertEqual(profile["job_industry"]["jobs_accommodation_food_services"], source_number(worker, "jobs_accommodation_food_services"))

    def test_every_missing_worker_source_stays_unavailable(self):
        missing = [geoid for geoid in self.all_tracts if not self.workers[geoid]["total_jobs"]]
        self.assertEqual(len(missing), 545)
        for geoid in missing:
            profile = resident_worker_profile(self.all_tracts[geoid])["market_profile"]
            self.assertIsNone(profile["jobs"])
            self.assertTrue(all(value is None for group in ("job_age", "job_earnings", "job_industry")
                                for value in profile[group].values()))

    def test_recorded_zero_is_not_missing(self):
        geoid = next(geoid for geoid in self.tracts if self.workers[geoid]["jobs_agriculture_forestry_fishing_hunting"] and source_number(self.workers[geoid], "jobs_agriculture_forestry_fishing_hunting") == 0)
        profile = resident_worker_profile(self.tracts[geoid])["market_profile"]
        self.assertEqual(profile["job_industry"]["jobs_agriculture_forestry_fishing_hunting"], 0)
        self.assertIsNotNone(profile["jobs"])
        self.assertEqual(source_number({"total_jobs": "0.0"}, "total_jobs"), 0)
        self.assertIsNone(source_number({"total_jobs": ""}, "total_jobs"))

    def test_area_selection_and_api_errors(self):
        with app.test_client() as client:
            areas = client.get("/api/areas")
            self.assertEqual(areas.status_code, 200)
            self.assertEqual({row["geoid"] for row in areas.json["areas"]}, set(self.tracts))
            self.assertEqual(client.get("/api/areas/bad/profile").status_code, 400)
            self.assertEqual(client.get("/api/areas/99999999999/profile").status_code, 404)


if __name__ == "__main__":
    unittest.main()
