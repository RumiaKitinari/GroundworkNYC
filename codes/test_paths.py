import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load_paths(env):
    spec = importlib.util.spec_from_file_location("model_paths_test", Path(__file__).with_name("paths.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, env, clear=True):
        spec.loader.exec_module(module)
    return module


class PathsTests(unittest.TestCase):
    def test_default_root_and_private_outputs(self):
        paths = load_paths({})
        self.assertEqual(paths.ROOT, Path(__file__).resolve().parents[1])
        self.assertEqual(paths.OUTPUTS, paths.DATA / "output" / "atharv_model")

    def test_existing_flat_layout_keeps_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = load_paths({"CAPSTONE_ROOT": tmp})
            paths.ensure_dirs()
            self.assertEqual(paths.OUTPUTS, Path(tmp) / "outputs")
            target = paths.OUTPUTS / "master_tract_features.csv"
            target.touch()
            self.assertEqual(paths.find(target.name), target)

    def test_integrated_and_archive_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = load_paths({"CAPSTONE_ROOT": tmp})
            targets = {
                "master_tract_features.csv": paths.DATA / "integrated/current/master_tract_features.csv",
                "current_restaurants.csv": paths.DATA / "integrated/current/entities/current_restaurants.csv",
                "synthetic_properties.csv": paths.DATA / "listings/synthetic_properties.csv",
                "restaurants_raw.parquet": paths.DATA / "raw_sources/nyc_cuisine_atlas/pinned/restaurants_raw.parquet",
            }
            for name, target in targets.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
                self.assertEqual(paths.find(name), target)
            self.assertEqual(paths.find(str(target)), target)
            other = paths.DATA / "raw_sources/nyc_cuisine_atlas/another/restaurants_raw.parquet"
            other.parent.mkdir(parents=True)
            other.touch()
            with self.assertRaises(ValueError):
                paths.find("restaurants_raw.parquet")


if __name__ == "__main__":
    unittest.main()
