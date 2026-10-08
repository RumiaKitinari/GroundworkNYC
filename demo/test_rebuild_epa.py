import unittest

from rebuild_epa import aggregate


class EpaCrosswalkTests(unittest.TestCase):
    def test_area_split_then_population_weighted_2020_tract_values(self):
        tracts = [
            {"geoid": "36061000100", "WKT": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"},
            {"geoid": "36061000200", "WKT": "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0))"},
        ]
        groups = [
            {"GEOID10": "old-1", "WKT": "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))",
             "TotPop": "100", "NatWalkInd": "10", "SLC_score": "50"},
            {"GEOID10": "old-2", "WKT": "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0))",
             "TotPop": "100", "NatWalkInd": "20", "SLC_score": "80"},
        ]
        values, summary = aggregate(tracts, groups)
        self.assertEqual(summary["population_bearing_groups_matched"], 2)
        self.assertEqual(values["36061000100"]["walkability_population_weight"], 50)
        self.assertEqual(values["36061000100"]["national_walkability_index"], 10)
        self.assertEqual(values["36061000200"]["walkability_population_weight"], 150)
        self.assertAlmostEqual(values["36061000200"]["national_walkability_index"], 16.666667)

    def test_duplicate_source_group_is_rejected(self):
        tract = [{"geoid": "36061000100", "WKT": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"}]
        group = {"GEOID10": "duplicate", "WKT": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
                 "TotPop": "10", "NatWalkInd": "10", "SLC_score": "60"}
        with self.assertRaisesRegex(ValueError, "duplicated"):
            aggregate(tract, [group, group])


if __name__ == "__main__":
    unittest.main()
