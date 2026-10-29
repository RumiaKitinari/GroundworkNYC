import unittest

import h3
from shapely.geometry import box, mapping, shape

from audit_hex_resolution import percentile, summarize_blocks
from hex_demand import boundary


class HexResolutionAuditTests(unittest.TestCase):
    def test_percentile_and_empty_input(self):
        self.assertIsNone(percentile([], .5))
        self.assertEqual(percentile([1, 3, 5], .5), 3)
        self.assertEqual(percentile([1, 3, 5], .25), 2)
        with self.assertRaises(ValueError):
            summarize_blocks([], (11,))

    def test_split_blocks_cover_full_cell_without_double_counting(self):
        cell = h3.latlng_to_cell(40.75, -73.97, 8)
        polygon = shape(boundary(cell))
        split = polygon.centroid.x
        parts = [polygon.intersection(box(-74, 40, split, 41)),
                 polygon.intersection(box(split, 40, -73, 41))]
        features = [{"type": "Feature", "properties": {"GEOID20": geoid,
                                                   "ALAND20": round(h3.cell_area(cell, unit="m^2") / 2)},
                     "geometry": mapping(part)}
                    for geoid, part in zip(("360610001001001", "360610002001001"), parts)]
        report = summarize_blocks(features, (8,))
        row = report["results"][0]
        self.assertEqual(row["borough"], "Manhattan")
        self.assertEqual(row["census_blocks_with_land"], 2)
        self.assertEqual(row["blocks_with_incomplete_hex_coverage"], 0)
        self.assertAlmostEqual(row["block_land_coverage_pct"], 100)
        self.assertGreaterEqual(row["material_blocks_per_cell_p10_p50_p90"][1], 2)
        self.assertGreaterEqual(row["distinct_tracts_per_cell_p50_p90"][0], 2)


if __name__ == "__main__":
    unittest.main()
