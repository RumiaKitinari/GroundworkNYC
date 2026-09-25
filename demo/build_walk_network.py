"""Build the private walking graph once after placing the OSM PBF locally."""

from pathlib import Path
from osm_network import build_network


ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    path = ROOT / "data" / "osm" / "nyc_walk_network.sqlite"
    print(build_network(ROOT / "data" / "osm" / "NewYork.osm.pbf", path))
