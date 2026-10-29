"""Content-addressed provenance for immutable screening tiles."""
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def screening_provenance(root=ROOT):
    files = ["demo/app.py", "demo/scoring.py", "demo/hex_demand.py"]
    return {"screening_code_sha256": sha256(b"".join(
        name.encode() + b"\0" + (root / name).read_bytes() for name in files
    )).hexdigest()}


def screening_is_current(metadata, release, root=ROOT):
    return metadata.get("data_release") == release and all(
        metadata.get(key) == value for key, value in screening_provenance(root).items()
    )
