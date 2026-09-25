import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from osm_network import WalkingNetwork


class WalkingNetworkTests(unittest.TestCase):
    def test_missing_graph_reports_unavailable(self):
        result = WalkingNetwork("/nonexistent/groundwork-walk.sqlite").site_evidence(40.7, -73.9, [], [])
        self.assertEqual(result["status"], "unavailable")

    def test_local_walk_catchment_uses_network_links(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "walk.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("""
                    CREATE TABLE nodes (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL);
                    CREATE VIRTUAL TABLE node_index USING rtree(id, min_lon, max_lon, min_lat, max_lat);
                    CREATE TABLE edges (source INTEGER, target INTEGER, meters REAL);
                    INSERT INTO nodes VALUES (1, 40.7, -73.9), (2, 40.7005, -73.9), (3, 40.701, -73.9);
                    INSERT INTO node_index VALUES (1, -73.9, -73.9, 40.7, 40.7),
                                                  (2, -73.9, -73.9, 40.7005, 40.7005),
                                                  (3, -73.9, -73.9, 40.701, 40.701);
                    INSERT INTO edges VALUES (1, 2, 56), (2, 3, 56);
                """)
                connection.commit()
            restaurants = [{"latitude": "40.7005", "longitude": "-73.9", "active_establishment": "True", "cuisine_description": "Mexican"},
                           {"latitude": "40.7005", "longitude": "-73.9", "active_establishment": "False", "cuisine_description": "Italian"}]
            stations = [{"latitude": "40.701", "longitude": "-73.9"}]
            result = WalkingNetwork(path).site_evidence(40.7, -73.9, restaurants, stations)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["recorded_restaurants"], 1)
        self.assertEqual(result["nearby_subway_stations"], 1)
        self.assertEqual(result["restaurant_cuisine_counts"], {"Mexican": 1})


if __name__ == "__main__":
    unittest.main()
