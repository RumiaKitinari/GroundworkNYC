import csv
import gzip
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from enrich_location_data import read_csv, rebuild_acs, rebuild_rac, rebuild_subway_patterns, rebuild_historical_events, write_csv


class EnrichmentTests(unittest.TestCase):
    def test_historical_events_are_distinct_past_district_context(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            write_csv(stage / "data_dictionary.csv", [], ("file", "column", "definition", "unit"))
            write_csv(stage / "source_catalog.csv", [], ("source", "vintage", "native_grain", "purpose", "coverage", "url"))
            write_csv(stage / "feature_readiness.csv", [], ("use", "primary_output", "analysis_grain", "status", "limitation"))
            year = datetime.now().year - 1
            rows = [{"event_id": str(i), "start_date_time": f"{year}-{i:02d}-01T10:00:00",
                     "end_date_time": f"{year}-{i:02d}-01T12:00:00", "event_borough": "Manhattan",
                     "community_board": "01", "event_type": "Festival"} for i in range(1, 13)]
            rows.append(rows[0].copy())
            raw = stage / "raw.csv"
            write_csv(raw, rows, rows[0].keys())
            master = [{"geoid": "36061000100", "community_district_code": "101"}]
            result = rebuild_historical_events(stage, raw, master, {"publisher_version": "test", "source_url": "official"}, minimum_rows=1)
            self.assertEqual(master[0]["past_year_permitted_events_district_context"], 12)
            self.assertEqual(master[0]["past_year_permitted_event_hours_district_context"], 24)
            self.assertEqual(result["selected_year"], year)
            aliases = {"event_id": "Event ID", "start_date_time": "Start Date/Time", "end_date_time": "End Date/Time",
                       "event_borough": "Event Borough", "community_board": "Community Board", "event_type": "Event Type"}
            display_rows = [{aliases[k]: datetime.fromisoformat(v).strftime("%m/%d/%Y %I:%M:%S %p") if k.endswith("date_time") else v
                             for k, v in r.items()} for r in rows]
            write_csv(raw, display_rows, display_rows[0].keys())
            rebuild_historical_events(stage, raw, master, {"publisher_version": "test", "source_url": "official"}, minimum_rows=1)
            self.assertEqual(master[0]["past_year_permitted_events_district_context"], 12)
            display_rows.append({**display_rows[0], "Event ID": "bad-duration", "End Date/Time": ""})
            write_csv(raw, display_rows, display_rows[0].keys())
            rebuild_historical_events(stage, raw, master, {"publisher_version": "test", "source_url": "official"}, minimum_rows=1)
            self.assertEqual(master[0]["past_year_permitted_events_district_context"], 13)
            self.assertEqual(master[0]["past_year_permitted_event_hours_district_context"], 24)
            self.assertAlmostEqual(master[0]["past_year_event_duration_valid_share"], 12/13)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.stage = Path(self.folder.name)
        self.master = [{"geoid": "36061000100", "total_jobs": "20", "nearest_subway_station_complex_id": "1"}]
        write_csv(self.stage / "data_dictionary.csv", [], ("file", "column", "definition", "unit"))
        write_csv(self.stage / "feature_readiness.csv", [], ("use", "primary_output", "analysis_grain", "status", "limitation"))
        write_csv(self.stage / "source_catalog.csv", [{"source": "LODES", "vintage": "2023 WAC"}],
                  ("source", "vintage", "native_grain", "purpose", "coverage", "url"))
        self.revision = {"publisher_version": "2023", "source_url": "https://example.org/full-source"}

    def test_acs_uses_correct_universes_and_preserves_suppressed_values(self):
        raw = self.stage / "raw"
        raw.mkdir()
        for table in ("b01001", "b17001", "b19301", "b19001", "b08301", "b15003", "b05002", "b11001", "b25003", "b25064", "b19013"):
            values = {"GEO_ID": "1400000US36061000100"}
            values.update({f"{table.upper()}_E{i:03d}": "10" for i in range(1, 50)})
            values[f"{table.upper()}_E001"] = "100"
            values[f"{table.upper()}_M001"] = "5"
            if table == "b19301":
                values["B19301_E001"] = "-666666666"
            with (raw / f"acsdt5y2024-{table}.dat").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=values.keys(), delimiter="|")
                writer.writeheader()
                writer.writerow(values)
        result = rebuild_acs(self.stage, raw, self.master, {**self.revision, "publisher_version": "2024"}, minimum_tracts=1)
        self.assertEqual(self.master[0]["population_age_20_34_2024"], 100)
        self.assertEqual(self.master[0]["poverty_share_2024"], 0.1)
        self.assertEqual(self.master[0]["bachelors_or_higher_share_2024"], 0.4)
        self.assertEqual(self.master[0]["per_capita_income_2024"], "")
        self.assertEqual(self.master[0]["per_capita_income_moe_2024"], 5)
        self.assertFalse(result["api_key_required"])
        self.assertEqual(len(read_csv(self.stage / "features/acs_context_estimates_and_margins.csv")), 11)

    def test_residence_jobs_are_counted_by_home_and_year_mismatch_stays_blank(self):
        raw = self.stage / "rac.csv.gz"
        with gzip.open(raw, "wt", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("h_geocode", "C000", "CE03", "CNS18"))
            writer.writeheader()
            writer.writerow({"h_geocode": "360610001001001", "C000": 10, "CE03": 3, "CNS18": 2})
        rebuild_rac(self.stage, raw, self.master, self.revision, minimum_blocks=1)
        self.assertEqual(self.master[0]["resident_area_jobs"], 10)
        self.assertEqual(self.master[0]["workplace_to_resident_area_job_ratio"], 2)
        rebuild_rac(self.stage, raw, self.master, {**self.revision, "publisher_version": "2024"}, minimum_blocks=1)
        self.assertEqual(self.master[0]["workplace_to_resident_area_job_ratio"], "")

    def test_subway_periods_use_every_hour_and_full_week_denominator(self):
        raw = self.stage / "station_hours.csv"
        start = datetime(2026, 9, 28)
        write_csv(raw, [{"transit_timestamp": (start + timedelta(hours=i)).isoformat(),
                         "station_complex_id": "1", "ridership": 1} for i in range(168)],
                  ("transit_timestamp", "station_complex_id", "ridership"))
        rebuild_subway_patterns(self.stage, raw, self.master, self.revision, minimum_stations=1)
        self.assertAlmostEqual(self.master[0]["nearest_subway_weekend_ridership_share"], 2/7)
        self.assertAlmostEqual(self.master[0]["nearest_subway_morning_ridership_share"], 4/24)
        self.assertAlmostEqual(self.master[0]["nearest_subway_late_night_ridership_share"], 7/24)


if __name__ == "__main__":
    unittest.main()
