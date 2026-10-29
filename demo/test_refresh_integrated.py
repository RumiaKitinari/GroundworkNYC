import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app
import refresh_integrated as refresh


class RefreshIntegratedTests(unittest.TestCase):
    def test_release_validation_checks_all_tract_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            (stage / "geography").mkdir()
            geoid = "36061000100"
            refresh.write_csv(stage / "master_tract_features.csv", [{"geoid": geoid, "jobs": 1}],
                              ("geoid", "jobs"))
            refresh.write_csv(stage / "data_dictionary.csv", [
                {"file": "master_tract_features.csv", "column": "geoid"},
                {"file": "master_tract_features.csv", "column": "jobs"},
            ], ("file", "column"))
            (stage / "geography" / "nyc_2020_census_tracts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [{"properties": {"geoid": geoid}}]}))
            feature = stage / "features" / "tract_jobs.csv"
            refresh.write_csv(feature, [{"geoid": geoid, "jobs": 1}], ("geoid", "jobs"))
            self.assertEqual(refresh.validate_release(stage, 1, [])["feature_tables_checked"], 1)
            refresh.write_csv(feature, [{"geoid": "36061000200", "jobs": 1}], ("geoid", "jobs"))
            with self.assertRaisesRegex(ValueError, "Invalid or duplicate 2020 tract GEOIDs"):
                refresh.validate_release(stage, 1, [])

    def test_weather_refresh_keeps_citywide_daily_grain_and_units(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            refresh.write_csv(stage / "features" / "daily_weather_central_park.csv", [],
                              ("station", "date", "precipitation_mm", "snowfall_mm", "snow_depth_mm",
                               "max_temperature_c", "min_temperature_c", "avg_temperature_c", "rain"))
            raw = stage / "weather.csv"
            refresh.write_csv(raw, [
                {"STATION": "USW00094728", "DATE": "2026-09-29", "PRCP": "114", "SNOW": "5",
                 "SNWD": "0", "TMAX": "211", "TMIN": "150", "WT16": "1"},
                {"STATION": "USW00094728", "DATE": "2026-10-07", "PRCP": "0"},
            ], ("STATION", "DATE", "PRCP", "SNOW", "SNWD", "TMAX", "TMIN", "WT16"))
            result = refresh.rebuild_weather(stage, raw, date(2026, 10, 6), minimum=1)
            self.assertEqual(result["days"], 1)
            row = refresh.read_csv(stage / "features" / "daily_weather_central_park.csv")[0]
            self.assertEqual(row["precipitation_mm"], "11.4")
            self.assertEqual(row["snowfall_mm"], "5.0")
            self.assertEqual(row["avg_temperature_c"], "18.05")
            self.assertEqual(row["rain"], "1")

    def test_rent_stats_only_join_published_tract_medians(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            raw = stage / "rent.csv"
            refresh.write_csv(raw, [
                {"reporting_year": "2024", "aggregate_level_citywide": "Census Tract",
                 "aggregate_level_id": "1000201", "median_monthly_rent_per_square": "8.00",
                 "median_square_feet": "1200", "total_storefronts": "50",
                 "storefront_leased_to_tenants": "42"},
                {"reporting_year": "2024", "aggregate_level_citywide": "Census Tract",
                 "aggregate_level_id": "1000300", "median_monthly_rent_per_square": "*"},
            ], ("reporting_year", "aggregate_level_citywide", "aggregate_level_id",
                "median_monthly_rent_per_square", "median_square_feet", "total_storefronts",
                "storefront_leased_to_tenants"))
            master = [{"geoid": "36061000201"}, {"geoid": "36061000300"}]
            result = refresh.rebuild_rent_stats(stage, raw, master, minimum=1)
            self.assertEqual(result["tracts_with_medians"], 1)
            self.assertEqual(master[0]["reported_median_monthly_rent_psf"], 8.0)
            self.assertEqual(master[0]["rent_reporting_year"], 2024)
            self.assertEqual(master[1]["reported_median_monthly_rent_psf"], "")

    def test_storefront_refresh_uses_latest_filing_and_tract_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            (stage / "entities").mkdir()
            (stage / "geography").mkdir()
            refresh.write_csv(stage / "entities" / "current_storefronts.csv",
                              [{"borough_block_lot": "1", "geoid": "36061000100"}],
                              ("borough_block_lot", "geoid"))
            (stage / "geography" / "nyc_2020_census_tracts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [{"type": "Feature",
                "properties": {"geoid": "36061000100"}, "geometry": {"type": "Polygon",
                "coordinates": [[[-74.02, 40.7], [-74.0, 40.7], [-74.0, 40.72],
                                 [-74.02, 40.72], [-74.02, 40.7]]]}}]}))
            raw = stage / "storefronts.csv"
            refresh.write_csv(raw, [
                {"borough_block_lot": "1", "reporting_year": "2025", "filing_due_date": "2025-08-15",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_6_30_or_date_sold": "yes"},
                {"borough_block_lot": "1", "reporting_year": "2025", "filing_due_date": "2026-02-15",
                 "latitude": "40.71", "longitude": "-74.01", "vacant_on_12_31": "yes"},
            ], ("borough_block_lot", "reporting_year", "filing_due_date", "latitude", "longitude",
                "vacant_on_12_31", "vacant_6_30_or_date_sold"))
            master = [{"geoid": "36061000100"}, {"geoid": "36061000200"}]
            result = refresh.rebuild_storefronts(stage, raw, master, minimum=1)
            self.assertEqual(result["properties"], 1)
            self.assertEqual(master[0]["reported_vacant_storefront_count"], 1)
            self.assertEqual(master[1]["reported_storefront_property_count"], 0)
            rows = refresh.read_csv(stage / "entities" / "current_storefronts.csv")
            self.assertEqual(rows[0]["filing_due_date"], "2026-02-15")

    def test_citibike_refresh_tracks_month_without_overwriting_august(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            (stage / "entities").mkdir()
            (stage / "geography").mkdir()
            refresh.write_csv(stage / "entities" / "citibike_stations_august_2026.csv",
                              [{"station_id": "A", "geoid": "36061000100", "latitude": "40.71",
                                "longitude": "-74.01"}],
                              ("station_id", "geoid", "latitude", "longitude"))
            (stage / "geography" / "nyc_2020_census_tracts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [{"type": "Feature",
                "properties": {"geoid": "36061000100"}, "geometry": {"type": "Polygon",
                "coordinates": [[[-74.02, 40.7], [-74.0, 40.7], [-74.0, 40.72],
                                 [-74.02, 40.72], [-74.02, 40.7]]]}}]}))
            raw = stage / "trips.zip"
            with zipfile.ZipFile(raw, "w") as archive:
                archive.writestr("trips.csv", "started_at,start_station_id,start_station_name,start_lat,start_lng,end_station_id,end_station_name,end_lat,end_lng\n"
                                 "2026-09-05 18:00:00,A,Test,40.71,-74.01,A,Test,40.71,-74.01\n"
                                 "2026-09-08 12:00:00,A,Test,40.71,-74.01,A,Test,40.71,-74.01\n")
            master = [{"geoid": "36061000100", "centroid_latitude": "40.71", "centroid_longitude": "-74.01",
                       "citibike_departures_august_2026": "5"}]
            result = refresh.rebuild_citibike(stage, raw, master, "2026-09", minimum=0)
            self.assertEqual(result["trips"], 2)
            self.assertEqual(master[0]["citibike_departures_latest_month"], 2)
            self.assertEqual(master[0]["citibike_evening_departures_latest_month"], 1)
            self.assertEqual(master[0]["citibike_weekend_departures_latest_month"], 1)
            self.assertEqual(master[0]["citibike_activity_month"], "2026-09")
            self.assertEqual(master[0]["citibike_departures_august_2026"], "5")

    def test_pluto_uses_vacant_land_not_parking_and_updates_master(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            raw = stage / "pluto.csv"
            refresh.write_csv(raw, [
                {"bbl": "1", "bct2020": "1000100", "landuse": "04", "lotarea": "100",
                 "comarea": "20", "retailarea": "10", "officearea": "5", "version": "26v2"},
                {"bbl": "2", "bct2020": "1000100", "landuse": "05", "lotarea": "200",
                 "comarea": "40", "retailarea": "20", "officearea": "10", "version": "26v2"},
                {"bbl": "3", "bct2020": "1000100", "landuse": "10", "lotarea": "300", "version": "26v2"},
                {"bbl": "4", "bct2020": "1000100", "landuse": "11", "lotarea": "400", "version": "26v2"},
                {"bbl": "5", "bct2020": "1999999", "landuse": "11", "version": "26v2"},
            ], ("bbl", "bct2020", "landuse", "lotarea", "comarea", "retailarea", "officearea", "version"))
            master = [{"geoid": "36061000100"}, {"geoid": "36061000200"}]
            result = refresh.rebuild_pluto(stage, raw, master, minimum=0)
            self.assertEqual(result["relevant_parcels"], 3)
            self.assertEqual(result["unassigned_parcels"], 1)
            self.assertEqual(result["vacant_land_parcels"], 1)
            self.assertEqual(master[0]["relevant_parcel_count"], 3)
            self.assertEqual(master[0]["vacant_land_parcel_count"], 1)
            self.assertEqual(master[0]["relevant_lot_area_sqft"], 700.0)
            self.assertEqual(master[0]["vacant_land_parcel_share"], round(1 / 3, 6))
            self.assertEqual(master[1]["relevant_parcel_count"], "")
            rows = refresh.read_csv(stage / "features" / "tract_land_use.csv")
            self.assertEqual(rows[0]["vacant_land_parcel_count"], "1")

    def test_polygon_assignment_respects_holes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tracts.geojson"
            path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
                "type": "Feature", "properties": {"geoid": "36061000100"},
                "geometry": {"type": "Polygon", "coordinates": [
                    [[-74.02, 40.7], [-74.0, 40.7], [-74.0, 40.72], [-74.02, 40.72], [-74.02, 40.7]],
                    [[-74.015, 40.705], [-74.01, 40.705], [-74.01, 40.71], [-74.015, 40.71], [-74.015, 40.705]],
                ]}}]}))
            index = refresh.polygon_index(path)
            self.assertEqual(refresh.containing_tract(-74.019, 40.701, index), "36061000100")
            self.assertEqual(refresh.containing_tract(-74.012, 40.707, index), "")

    def test_restaurants_keep_unlocated_establishments(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "entities").mkdir()
            (stage / "features").mkdir()
            (stage / "geography").mkdir()
            fields = ("camis", "dba", "geoid", "latitude", "longitude", "latest_score", "latest_grade",
                      "latest_violation_count", "latest_critical_violation_count", "active_establishment")
            refresh.write_csv(stage / "entities" / "current_restaurants.csv",
                              [{"camis": "1", "geoid": "36061000100"}], fields)
            (stage / "geography" / "nyc_2020_census_tracts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"geoid": "36061000100"},
                "geometry": {"type": "Polygon", "coordinates": [[[-74.02, 40.7], [-74.0, 40.7],
                [-74.0, 40.72], [-74.02, 40.72], [-74.02, 40.7]]]}}]}))
            raw = stage / "raw.csv"
            refresh.write_csv(raw, [
                {"camis": "1", "dba": "A", "boro": "Manhattan", "census_tract": "999999",
                 "latitude": "40.71", "longitude": "-74.01", "inspection_date": "2026-09-30T00:00:00.000",
                 "score": "8", "grade": "A", "violation_code": "06A", "critical_flag": "Critical"},
                {"camis": "2", "dba": "B", "boro": "Manhattan", "census_tract": "", "latitude": "0",
                 "longitude": "0", "inspection_date": "2026-09-30T00:00:00.000"},
            ], ("camis", "dba", "boro", "census_tract", "latitude", "longitude", "inspection_date",
                "score", "grade", "violation_code", "critical_flag"))
            master = [{"geoid": "36061000100"}]
            result = refresh.rebuild_restaurants(stage, raw, master, minimum=0)
            self.assertEqual(result["establishments"], 2)
            self.assertEqual(result["unlocated"], 1)
            rows = refresh.read_csv(stage / "entities" / "current_restaurants.csv")
            self.assertEqual(rows[0]["geoid"], "36061000100")
            self.assertEqual(rows[1]["geoid"], "")
            self.assertEqual(master[0]["active_restaurant_count"], 1)

    def test_event_window_and_board(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            raw = stage / "events.csv"
            refresh.write_csv(raw, [
                {"event_id": "one", "event_borough": "Manhattan", "community_board": "01,",
                 "start_date_time": "2026-10-02T10:00:00", "end_date_time": "2026-10-02T12:00:00",
                 "event_type": "Fair"},
                {"event_id": "old", "event_borough": "Manhattan", "community_board": "01,",
                 "start_date_time": "2026-09-01T10:00:00", "end_date_time": "2026-09-01T12:00:00",
                 "event_type": "Fair"},
            ], ("event_id", "event_borough", "community_board", "start_date_time", "end_date_time", "event_type"))
            master = [{"geoid": "36061000100", "community_district_code": "101"}]
            result = refresh.rebuild_events(stage, raw, master, date(2026, 10, 1))
            self.assertEqual(result["events"], 1)
            self.assertEqual(master[0]["permitted_event_count_2026"], 1)

    def test_event_window_crosses_year_without_mislabeling_2026(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            raw = stage / "raw.csv"
            refresh.write_csv(raw, [
                {"event_id": "dec", "event_borough": "Manhattan", "community_board": "01,",
                 "start_date_time": "2026-12-02T10:00:00", "end_date_time": "2026-12-02T11:00:00"},
                {"event_id": "jan", "event_borough": "Manhattan", "community_board": "01,",
                 "start_date_time": "2027-01-02T10:00:00", "end_date_time": "2027-01-02T11:00:00"},
            ], ("event_id", "event_borough", "community_board", "start_date_time", "end_date_time"))
            master = [{"geoid": "36061000100", "community_district_code": "101"}]
            result = refresh.rebuild_events(stage, raw, master, date(2026, 12, 1))
            self.assertEqual(result["events"], 2)
            self.assertEqual(master[0]["permitted_event_count_next_90_days"], 2)
            self.assertEqual(master[0]["permitted_event_count_2026"], 1)

    def test_tlc_refresh_uses_pickup_month_and_zone(self):
        import duckdb

        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            (stage / "features").mkdir()
            raw = stage / "rides.parquet"
            connection = duckdb.connect()
            connection.execute("""
                COPY (SELECT * FROM (VALUES
                    (TIMESTAMP '2026-08-01 12:00:00', 1, 2, 2.50),
                    (TIMESTAMP '2026-08-02 12:00:00', 1, 2, 1.00),
                    (TIMESTAMP '2026-09-01 12:00:00', 1, 2, 9.00)
                ) AS t(pickup_datetime, PULocationID, DOLocationID, cbd_congestion_fee))
                TO ? (FORMAT PARQUET)
            """, [str(raw)])
            connection.close()
            refresh.write_csv(stage / "features" / "tract_taxi_activity.csv",
                              [{"geoid": "36061000100", "location_id": "1"},
                               {"geoid": "36061000200", "location_id": "2"}], ("geoid", "location_id"))
            master = [{"geoid": "36061000100"}, {"geoid": "36061000200"}]
            result = refresh.rebuild_tlc(stage, raw, master, "2026-08", minimum_trips=0, minimum_zones=0)
            self.assertEqual(result["trips_with_pickup_zone"], 2)
            self.assertEqual(master[0]["pickups_latest_month"], 2)
            self.assertEqual(master[0]["cbd_congestion_fee_total_latest_month"], 3.5)
            self.assertEqual(master[1]["dropoffs_latest_month"], 2)
            self.assertEqual(master[0]["taxi_activity_month"], "2026-08")

    def test_app_follows_atomic_release_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline, release, pointer = root / "baseline", root / "release", root / "current"
            baseline.mkdir()
            release.mkdir()
            with patch.object(app, "BASELINE_DATA_DIR", baseline), patch.object(app, "CURRENT_DATA_LINK", pointer), \
                    patch.object(app, "_load_integrated_package", side_effect=lambda path: path.name):
                self.assertEqual(app.integrated_package(), "baseline")
                pointer.symlink_to(release, target_is_directory=True)
                self.assertEqual(app.integrated_package(), "release")


if __name__ == "__main__":
    unittest.main()
