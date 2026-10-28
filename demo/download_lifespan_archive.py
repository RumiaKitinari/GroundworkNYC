"""Download the pinned, privately stored NYC cuisine atlas Parquet inputs."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from build_restaurant_lifespans import SOURCE_COMMIT
from evaluation import fingerprint
from refresh_integrated import ROOT


FILES = {
    "restaurants_raw.parquet": "296143a070f5dffce509d8219031c3b55b9dc0ea66c96a9d7b5a502268c4c14a",
    "inspections.parquet": "93b1af948571bbc5304c8004c306d5dbad39b5adf33cdd34feb8132fb5f44a46",
}
BASE_URL = f"https://raw.githubusercontent.com/CharlesFainLehman/nyc-cuisine-atlas/{SOURCE_COMMIT}/data"


def download(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, expected in FILES.items():
        destination = directory / name
        if destination.exists():
            if fingerprint(destination) != expected:
                raise ValueError(f"Existing file differs from pinned source: {destination}")
            results[name] = "already_verified"
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{name}.", delete=False) as stream:
                temporary = Path(stream.name)
                digest = hashlib.sha256()
                with urlopen(f"{BASE_URL}/{name}", timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"Downloaded file hash differs from pinned source: {name}")
            os.replace(temporary, destination)
            results[name] = "downloaded_and_verified"
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"source_commit": SOURCE_COMMIT, "directory": str(directory), "files": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data/raw_sources/nyc_cuisine_atlas" / SOURCE_COMMIT)
    args = parser.parse_args()
    try:
        print(json.dumps(download(args.directory), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Archive download failed: {error}\n")


if __name__ == "__main__":
    main()
