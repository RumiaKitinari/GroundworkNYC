r"""
Project folders. Every script imports these, so paths live in one place.

By default, use this repository's data folder and keep generated research
outputs in data/output/atharv_model (excluded from Git). The integrated
release remains read-only. CAPSTONE_ROOT preserves the original flat
data/outputs layout; CAPSTONE_OUTPUTS overrides the output directory.
"""
import os
from pathlib import Path

ROOT = Path(os.environ.get("CAPSTONE_ROOT", Path(__file__).resolve().parents[1])).expanduser()
DATA = ROOT / "data"
OUTPUTS = Path(os.environ.get(
    "CAPSTONE_OUTPUTS", ROOT / "outputs" if "CAPSTONE_ROOT" in os.environ
    else DATA / "output" / "atharv_model"
)).expanduser()
MODEL = OUTPUTS / "model"
RECOMMENDATIONS = OUTPUTS / "recommendations"


def find(name):
    """Keep flat-layout inputs compatible, then use the local integrated package."""
    path = Path(name).expanduser()
    if path.is_absolute() or path.exists():
        return path
    for folder in (OUTPUTS, DATA):
        if (folder / name).exists():
            return folder / name
    integrated = DATA / "integrated" / "current"
    inputs = {
        "master_tract_features.csv": integrated / "master_tract_features.csv",
        "current_restaurants.csv": integrated / "entities" / "current_restaurants.csv",
        "synthetic_properties.csv": DATA / "listings" / "synthetic_properties.csv",
    }
    if name in inputs and inputs[name].exists():
        return inputs[name]
    if name == "restaurants_raw.parquet":
        archives = sorted((DATA / "raw_sources" / "nyc_cuisine_atlas").glob("*/restaurants_raw.parquet"))
        if len(archives) > 1:
            raise ValueError("Multiple cuisine-atlas snapshots exist; pass an explicit input path.")
        if archives:
            return archives[0]
    return DATA / name


def ensure_dirs():
    for d in (OUTPUTS, MODEL, RECOMMENDATIONS):
        d.mkdir(parents=True, exist_ok=True)
