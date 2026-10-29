import csv
import tempfile
import unittest
from pathlib import Path

from build_historical_snapshots import build_snapshots, load_epa_snapshot, read_acs_table, write_immutable_csv


class HistoricalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)

    def test_acs_filters_nyc_tracts_and_suppressed_values(self):
        source = self.path / "table.dat"
        with source.open("w", newline="") as stream:
            writer = csv.writer(stream, delimiter="|")
            writer.writerow(["GEO_ID", "B19013_E001"])
            writer.writerow(["1400000US36061000100", "95000"])
            writer.writerow(["1400000US36061000200", "-666666666"])
            writer.writerow(["1400000US36119000100", "100000"])
            writer.writerow(["0500000US36061", "50000"])
        values = read_acs_table(source, "B19013_E001", minimum_tracts=2)
        self.assertEqual(values, {"36061000100": 95000, "36061000200": None})
        with self.assertRaisesRegex(ValueError, "Incomplete NYC ACS"):
            read_acs_table(source, "B19013_E001")

    def test_snapshot_density_and_immutable_output(self):
        acs, workers = build_snapshots({"36061000100": 0.5, "36061000200": 0},
                                       {"36061000100": 1000, "36061000200": 500},
                                       {"36061000100": 95000}, {"36061000100": 200})
        self.assertEqual(acs[0]["population_density_per_sq_mile"], 2000)
        self.assertEqual(workers[0]["job_density_per_sq_mile"], 400)
        self.assertEqual(acs[1]["population_density_per_sq_mile"], "")
        target = self.path / "snapshot.csv"
        first = write_immutable_csv(target, acs, ["geoid", "population_density_per_sq_mile", "median_household_income"])
        self.assertEqual(first, write_immutable_csv(target, acs, ["geoid", "population_density_per_sq_mile", "median_household_income"]))
        with self.assertRaisesRegex(ValueError, "differs"):
            write_immutable_csv(target, acs[:1], ["geoid", "population_density_per_sq_mile", "median_household_income"])

    def test_epa_values_are_bounded_and_complete(self):
        source = self.path / "epa.csv"
        with source.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["geoid", "national_walkability_index"])
            writer.writeheader()
            writer.writerow({"geoid": "36061000100", "national_walkability_index": "15.5"})
        self.assertEqual(load_epa_snapshot(source, {"36061000100"})[0]["national_walkability_index"], "15.5")
        with self.assertRaisesRegex(ValueError, "coverage"):
            load_epa_snapshot(source, {"36061000100", "36061000200"})


if __name__ == "__main__":
    unittest.main()
