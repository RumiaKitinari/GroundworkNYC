import json
import tempfile
import unittest
from pathlib import Path

import master_tract_spec
import refresh_integrated as refresh


def polygon(geoid, left, bottom, right, top):
    return {"type": "Feature", "properties": {"geoid": geoid},
            "geometry": {"type": "Polygon", "coordinates": [[
                [left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]
            ]]}}


class MasterTractSpecTests(unittest.TestCase):
    def test_pluto_shares_use_all_lots_and_floor_average_excludes_vacant_land(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            raw = stage / "pluto.csv"
            refresh.write_csv(raw, [
                {"bbl": "1", "bct2020": "1000100", "landuse": "04", "numfloors": "4", "version": "26v2"},
                {"bbl": "2", "bct2020": "1000100", "landuse": "05", "numfloors": "2", "version": "26v2"},
                {"bbl": "3", "bct2020": "1000100", "landuse": "11", "version": "26v2"},
                {"bbl": "4", "bct2020": "1000100", "landuse": "01", "version": "26v2"},
            ], ("bbl", "bct2020", "landuse", "numfloors", "version"))
            master = [{"geoid": "36061000100"}]
            result = refresh.rebuild_pluto(stage, raw, master, minimum=1)
            self.assertEqual(result["relevant_parcels"], 3)
            self.assertEqual(master[0]["total_lot_count"], 4)
            self.assertEqual(master[0]["commercial_mixed_lot_share_all"], 0.5)
            self.assertEqual(master[0]["vacant_land_share_all_lots"], 0.25)
            self.assertEqual(master[0]["mean_commercial_mixed_num_floors"], 3)

    def test_normalized_fields_and_boundary_neighbors(self):
        with tempfile.TemporaryDirectory() as folder:
            geography = Path(folder) / "tracts.geojson"
            geography.write_text(json.dumps({"type": "FeatureCollection", "features": [
                polygon("36061000100", 0, 0, 1, 1),
                polygon("36061000200", 1, 0, 2, 1),
                polygon("36061000300", 2, 1, 3, 2),
            ]}))
            master = [
                {"geoid": "36061000100", "population_2024": "100", "population_under_18_2024": "20",
                 "population_65_plus_2024": "10", "total_jobs": "200", "jobs_retail_trade": "30",
                 "jobs_accommodation_food_services": "40", "jobs_earn_more_than_3333_monthly": "50",
                 "land_area_sq_miles": "0.5", "citibike_departures_latest_month": "60",
                 "citibike_weekend_departures_latest_month": "20", "citibike_evening_departures_latest_month": "30",
                 "retail_area_sqft": "1000", "office_area_sqft": "500", "restaurant_competitor_count": "2",
                 "bar_nightlife_competitor_count": "", "median_household_income_2024": "",
                 "reported_median_monthly_rent_psf": "8", "registered_storefronts": "10"},
                {"geoid": "36061000200", "population_2024": "200", "total_jobs": "50",
                 "land_area_sq_miles": "1", "median_household_income_2024": "80000"},
                {"geoid": "36061000300", "population_2024": "0", "total_jobs": "0",
                 "land_area_sq_miles": "1", "median_household_income_2024": ""},
            ]
            result = master_tract_spec.enrich(master, geography)
            self.assertEqual(result["missing_income"], 2)
            self.assertEqual(master[0]["pct_residents_under_18"], 20)
            self.assertEqual(master[0]["jobs_per_resident"], 2)
            self.assertEqual(master[0]["citibike_weekend_departure_share_latest_month"], 0.333333)
            self.assertEqual(master[0]["reported_median_annual_rent_psf"], 96)
            self.assertEqual(master[0]["neighbor_geoids"], "36061000200")
            self.assertEqual(master[0]["neighbor_income_2024_estimate"], 80000)
            self.assertEqual(master[0]["median_household_income_2024"], "")
            self.assertEqual(master[2]["jobs_per_resident"], "")
            self.assertEqual(master[2]["neighbor_geoids"], "")

    def test_incomplete_latest_storefront_year_is_not_treated_as_full_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            for directory in ("entities", "features", "geography"):
                (stage / directory).mkdir()
            refresh.write_csv(stage / "entities" / "current_storefronts.csv",
                              [{"borough_block_lot": "1", "geoid": "36061000100"}],
                              ("borough_block_lot", "geoid"))
            (stage / "geography" / "nyc_2020_census_tracts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [polygon("36061000100", -74.02, 40.7, -74.0, 40.72)]
            }))
            raw = stage / "raw.csv"
            refresh.write_csv(raw, [
                {"borough_block_lot": "1", "reporting_year": "2024", "filing_due_date": "2025-01-01",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_on_12_31": "NO"},
                {"borough_block_lot": "2", "reporting_year": "2024", "filing_due_date": "2025-01-01",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_on_12_31": "YES"},
                {"borough_block_lot": "2", "reporting_year": "2024", "filing_due_date": "2025-01-01",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_on_12_31": "NO"},
                {"borough_block_lot": "3", "reporting_year": "2025", "filing_due_date": "2026-01-01",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_on_12_31": "YES"},
                {"borough_block_lot": "4", "reporting_year": "2025", "filing_due_date": "2026-01-01",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_on_12_31": "NO"},
            ], ("borough_block_lot", "reporting_year", "filing_due_date", "latitude", "longitude", "vacant_on_12_31"))
            master = [{"geoid": "36061000100"}]
            result = refresh.rebuild_storefronts(stage, raw, master, minimum=1)
            self.assertEqual(result["reporting_year"], "2024")
            self.assertEqual(result["properties"], 2)
            self.assertEqual(master[0]["reported_vacant_storefront_count"], 1)
            self.assertEqual(master[0]["reported_storefront_vacancy_share"], "")


if __name__ == "__main__":
    unittest.main()
