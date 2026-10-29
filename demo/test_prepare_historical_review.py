import csv
import json
import tempfile
import unittest
from pathlib import Path

from prepare_historical_review import build_review_queue, inspection_day, match_inventory


class HistoricalReviewTests(unittest.TestCase):
    def test_exported_dot_date_format(self):
        self.assertEqual(inspection_day("12/20/2023 04:06:58 PM").isoformat(), "2023-12-20")

    def test_exact_inventory_match_requires_same_tract(self):
        keys = {("tract-a", "open cafe", "10 main st"): "Open Cafe"}
        basis, name = match_inventory("Open Cafe", "10 Main St", "tract-b", 40.8, -74.0,
                                      keys, {})
        self.assertEqual((basis, name), ("none", ""))

    def test_historical_matches_only_prioritize_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.csv"
            with master.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["geoid", "nta_code", "borough"])
                writer.writeheader()
                writer.writerow({"geoid": "36061000100", "nta_code": "MN01", "borough": "Manhattan"})
            geography = root / "tracts.geojson"
            geography.write_text(json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"geoid": "36061000100"},
                 "geometry": {"type": "Polygon", "coordinates": [[[-74.1, 40.7], [-73.9, 40.7],
                                                              [-73.9, 40.9], [-74.1, 40.9], [-74.1, 40.7]]]}}
            ]}))
            current = root / "current.csv"
            with current.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["dba", "building", "street", "geoid"])
                writer.writeheader()
                writer.writerow({"dba": "Open Cafe", "building": "10", "street": "Main St",
                                 "geoid": "36061000100"})
            source = root / "history.csv"
            with source.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["Borough", "RestaurantName", "BusinessAddress",
                                                            "InspectedOn", "SkippedReason", "Latitude", "Longitude",
                                                            "RestaurantInspectionID"])
                writer.writeheader()
                for index, (name, address, day, skipped) in enumerate([
                    ("Open Cafe", "10 Main St", "2024-02-01", ""),
                    ("Former Cafe", "12 Main St", "2024-03-01", ""),
                    ("Skipped Cafe", "14 Main St", "2024-03-01", "Closed"),
                    ("Early Cafe", "16 Main St", "2023-01-01", ""),
                ]):
                    writer.writerow({"Borough": "Manhattan", "RestaurantName": name,
                                     "BusinessAddress": address, "InspectedOn": day,
                                     "SkippedReason": skipped, "Latitude": 40.8, "Longitude": -74.0,
                                     "RestaurantInspectionID": str(index)})
            queue, audit = build_review_queue(source, master, geography, current)
            self.assertEqual(audit["unique_geocoded_candidates"], 2)
            self.assertEqual(len(queue), 2)
            self.assertEqual({row["current_inventory_match_basis"] for row in queue},
                             {"exact_name_address", "none"})
            self.assertTrue(all(0 < float(row["selection_probability"]) <= 1 for row in queue))
            self.assertTrue(all(row["outcome_status"] == "unresolved" for row in queue))
            self.assertTrue(all(row["baseline_operating"] == "" and row["as_of_date"] == ""
                                for row in queue))
            self.assertEqual(queue, build_review_queue(source, master, geography, current)[0])


if __name__ == "__main__":
    unittest.main()
