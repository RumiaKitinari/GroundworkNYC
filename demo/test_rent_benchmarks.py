import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rent_benchmarks import load_rent_benchmarks


class RentBenchmarkTests(unittest.TestCase):
    def test_missing_source_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_rent_benchmarks(folder)["status"], "unavailable")

    def test_latest_tract_rows_and_suppressed_values(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "raw_sources/storefront_rent_stats"
            revision = home / "version-one"
            revision.mkdir(parents=True)
            path = revision / "rows.csv"
            fields = ["reporting_year", "aggregate_level_citywide", "aggregate_level_id",
                      "median_monthly_rent_per_square", "median_square_feet", "total_storefronts",
                      "storefront_leased_to_tenants"]
            rows = [
                ["2023", "Census Tract", "1000201", "2.00", "900", "30", "20"],
                ["2024", "Census Tract", "1000201", "8.00", "1,200", "50", "42"],
                ["2024", "Census Tract", "2008900", "*", "850", "25", "17"],
                ["2024", "Borough", "Manhattan", "9.00", "1,300", "400", "200"],
            ]
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                writer.writerows(rows)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            (home / "manifest.json").write_text(json.dumps({"revisions": [{"directory": "version-one",
                                                                "files": [{"file": "rows.csv", "sha256": digest}]}]}))
            result = load_rent_benchmarks(folder)
            self.assertEqual(result["reporting_year"], 2024)
            self.assertEqual(result["tracts_with_reported_median"], 1)
            self.assertEqual(result["by_geoid"]["36061000201"]["reported_median_monthly_rent_psf"], 8)
            self.assertEqual(result["by_geoid"]["36061000201"]["reported_median_storefront_sqft"], 1200)

    def test_modified_snapshot_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "raw_sources/storefront_rent_stats"
            revision = home / "version-two"
            revision.mkdir(parents=True)
            (revision / "rows.csv").write_text("reporting_year\n2024\n")
            (home / "manifest.json").write_text(json.dumps({"revisions": [{"directory": "version-two",
                                                                "files": [{"file": "rows.csv", "sha256": "wrong"}]}]}))
            self.assertEqual(load_rent_benchmarks(folder)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
