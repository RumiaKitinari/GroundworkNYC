"""Small synthetic fixtures test reporting semantics, not model accuracy."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from batch_cuisine_scenarios import frequency_features, select_top, taxonomy, write_figure, write_viewer


class BatchScenariosTests(unittest.TestCase):
    def test_taxonomy_has_fifty_explicit_categories(self):
        pairs = taxonomy()
        self.assertEqual(len(pairs), 50)
        self.assertIn(("Haitian", "haitian"), pairs)
        self.assertIn(("Diner", "custom"), pairs)

    def test_ties_are_deterministic_and_missing_is_not_selected(self):
        frame = pd.DataFrame({"property_id": ["b", "missing", "a", "infinite"], "score": [30, np.nan, 30, np.inf]})
        self.assertEqual(select_top(frame, "score", 5).property_id.tolist(), ["a", "b"])
        self.assertEqual(select_top(frame.iloc[::-1], "score", 1).property_id.tolist(), ["a"])

    def test_duplicate_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            select_top(pd.DataFrame({"property_id": ["a", "a"], "score": [1, 2]}), "score", 1)

    def test_empty_scores_remain_empty(self):
        top = select_top(pd.DataFrame({"property_id": ["a"], "score": [np.nan]}), "score", 5)
        self.assertTrue(top.empty)

    def fixture(self):
        return pd.DataFrame({"method": ["huff", "huff", "huff", "screening"], "price_tier": ["$", "$", "$$", "$"],
            "latitude": [40.75] * 4, "longitude": [-73.98] * 4, "property_id": ["a", "b", "a", "a"],
            "scenario_id": ["01_1", "01_1", "01_2", "01_1"], "cuisine": ["American"] * 4})

    def test_frequency_counts_scenarios_not_duplicate_properties(self):
        features = frequency_features(self.fixture(), "huff", "$")
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["properties"]["selection_count"], 2)
        self.assertEqual(features[0]["properties"]["scenario_count"], 1)
        ring = features[0]["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertTrue(frequency_features(self.fixture(), "huff", "$$$") == [])

    def test_viewer_is_self_contained_and_contains_frequency(self):
        with tempfile.TemporaryDirectory() as folder:
            write_viewer(Path(folder), self.fixture(), [])
            text = (Path(folder) / "heatmaps.html").read_text()
            self.assertNotIn("__SCENARIO_DATA__", text)
            payload = json.loads(text.split("const data=", 1)[1].split(";\nconst $", 1)[0])
            self.assertTrue(payload["frequency"])
            self.assertEqual(len(payload["cuisines"]), 50)
            self.assertNotIn('<script src=', text)

    def test_dollar_tiers_render_without_mathtext(self):
        with tempfile.TemporaryDirectory() as folder:
            write_figure(Path(folder), self.fixture(), [])
            self.assertGreater((Path(folder) / "selection_heatmaps.png").stat().st_size, 10000)


if __name__ == "__main__":
    unittest.main()
