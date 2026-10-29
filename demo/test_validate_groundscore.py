import unittest
import tempfile
from pathlib import Path

from validate_groundscore import hex_assessment, verify_hex_inputs
from audit_scoring import sha256


class GroundscoreAuditTests(unittest.TestCase):
    def report(self, missing=None):
        rows = []
        for borough in ("Bronx", "Brooklyn", "Manhattan", "Queens"):
            for resolution in (8, 9):
                if (borough, resolution) == missing:
                    continue
                rows.append({"borough": borough, "resolution": resolution,
                             "material_blocks_per_cell_p10_p50_p90": [1, 10, 20],
                             "distinct_tracts_per_cell_p50_p90": [2, 4],
                             "block_land_coverage_pct": 100})
        return {"results": rows, "live_grid_coverage": {"results": [
            {"resolution": 8, "eligible_tract_polygon_coverage_pct": 99.7},
            {"resolution": 9, "eligible_tract_polygon_coverage_pct": 99.8}]}}

    def test_hex_assessment_keeps_fine_cells_exploratory(self):
        result = hex_assessment(self.report())
        self.assertEqual(result["default_single_hex_resolution"], 8)
        self.assertEqual(result["exploratory_fine_resolution"], 9)

    def test_hex_assessment_rejects_incomplete_coverage(self):
        with self.assertRaisesRegex(ValueError, "missing resolution"):
            hex_assessment(self.report(("Queens", 9)))

    def test_hex_report_must_match_current_release(self):
        with tempfile.TemporaryDirectory() as folder:
            release = Path(folder)
            (release / "geography").mkdir()
            (release / "master_tract_features.csv").write_text("first")
            (release / "geography/nyc_2020_census_tracts.geojson").write_text("geometry")
            report = {"integrated_inputs_sha256": {
                "master": sha256(release / "master_tract_features.csv"),
                "geography": sha256(release / "geography/nyc_2020_census_tracts.geojson")}}
            verify_hex_inputs(report, release)
            (release / "master_tract_features.csv").write_text("refreshed")
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_hex_inputs(report, release)


if __name__ == "__main__":
    unittest.main()
