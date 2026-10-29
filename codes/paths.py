r"""
Project folders. Every script imports these, so paths live in one place.

    E:\440 CAPSTONE\codes     all .py files (this one included)
    E:\440 CAPSTONE\data      raw inputs you downloaded
    E:\440 CAPSTONE\outputs   everything the scripts write

To use a different drive or folder, set the CAPSTONE_ROOT environment
variable instead of editing this file.
"""
import os
from pathlib import Path

ROOT = Path(os.environ.get("CAPSTONE_ROOT", r"E:\440 CAPSTONE"))
DATA = ROOT / "data"
OUTPUTS = ROOT / "outputs"
MODEL = OUTPUTS / "model"
RECOMMENDATIONS = OUTPUTS / "recommendations"


def find(name):
    """Look for a file in outputs first (things the scripts made), then data."""
    for folder in (OUTPUTS, DATA):
        if (folder / name).exists():
            return folder / name
    return DATA / name


def ensure_dirs():
    for d in (OUTPUTS, MODEL, RECOMMENDATIONS):
        d.mkdir(parents=True, exist_ok=True)
