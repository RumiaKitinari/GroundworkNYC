import csv
import tempfile
import unittest
from pathlib import Path

from build_historical_transit_candidate import aggregate_stations, nearest_features


class HistoricalTransitCandidateTests(unittest.TestCase):
    def make_source(self, path, conflicting=False):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("station_complex_id", "latitude", "longitude", "ridership"))
            writer.writeheader()
            for station_id in range(400):
                writer.writerow({"station_complex_id": station_id, "latitude": 40.7,
                                 "longitude": -73.9, "ridership": 1})
            writer.writerow({"station_complex_id": 1, "latitude": 40.7 if not conflicting else 40.8,
                             "longitude": -73.9, "ridership": 2})

    def test_aggregates_complete_station_set(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "week.csv"
            self.make_source(path)
            stations = aggregate_stations(path)
            self.assertEqual(len(stations), 400)
            self.assertEqual(stations["1"]["ridership"], 3)

    def test_rejects_material_coordinate_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "week.csv"
            self.make_source(path, conflicting=True)
            with self.assertRaisesRegex(ValueError, "Conflicting station coordinates"):
                aggregate_stations(path)

    def test_rejects_incomplete_master_geography(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "master.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("geoid", "centroid_latitude", "centroid_longitude"))
                writer.writeheader()
                writer.writerow({"geoid": "36061000100", "centroid_latitude": 40.7,
                                 "centroid_longitude": -73.9})
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                nearest_features(path, {"1": {"latitude": 40.7, "longitude": -73.9, "ridership": 10}})


if __name__ == "__main__":
    unittest.main()
