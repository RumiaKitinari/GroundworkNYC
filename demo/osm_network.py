"""Offline pedestrian-network extraction and bounded address catchments."""

from collections import Counter, defaultdict
from contextlib import closing
from functools import lru_cache
from math import cos, radians, sqrt
from pathlib import Path
import sqlite3


WALKABLE = {
    "residential", "living_street", "pedestrian", "footway", "path", "steps",
    "service", "tertiary", "secondary", "primary", "unclassified", "track",
    "road", "cycleway",
}
METERS_PER_DEGREE_LAT = 111_195


def distance_meters(lat_a, lon_a, lat_b, lon_b):
    lat_scale = METERS_PER_DEGREE_LAT
    lon_scale = lat_scale * cos(radians((lat_a + lat_b) / 2))
    return sqrt(((lat_a - lat_b) * lat_scale) ** 2 + ((lon_a - lon_b) * lon_scale) ** 2)


def build_network(pbf_path, output_path):
    """Create a private SQLite walk graph from the local New York PBF."""
    import osmium

    pbf_path, output_path = Path(pbf_path), Path(output_path)
    if not pbf_path.is_file():
        raise FileNotFoundError(pbf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".building.sqlite")
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    connection.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE nodes (id INTEGER PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL);
        CREATE VIRTUAL TABLE node_index USING rtree(id, min_lon, max_lon, min_lat, max_lat);
        CREATE TABLE edges (source INTEGER NOT NULL, target INTEGER NOT NULL, meters REAL NOT NULL,
                            PRIMARY KEY(source, target)) WITHOUT ROWID;
    """)

    class Walkways(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.nodes = {}
            self.edges = []
            self.count = 0

        def flush(self):
            if not self.edges:
                return
            connection.executemany("INSERT OR IGNORE INTO nodes VALUES (?, ?, ?)",
                                   ((node_id, lat, lon) for node_id, (lat, lon) in self.nodes.items()))
            connection.executemany("INSERT OR IGNORE INTO node_index VALUES (?, ?, ?, ?, ?)",
                                   ((node_id, lon, lon, lat, lat) for node_id, (lat, lon) in self.nodes.items()))
            connection.executemany("INSERT OR IGNORE INTO edges VALUES (?, ?, ?)", self.edges)
            self.count += len(self.edges)
            self.nodes.clear()
            self.edges.clear()

        def way(self, way):
            highway = way.tags.get("highway")
            if highway not in WALKABLE or way.tags.get("foot") == "no" or way.tags.get("access") in {"private", "no"}:
                return
            if highway == "cycleway" and way.tags.get("foot") not in {"yes", "designated"}:
                return
            nodes = [node for node in way.nodes if node.location.valid()]
            for first, second in zip(nodes, nodes[1:]):
                a = (first.location.lat, first.location.lon)
                b = (second.location.lat, second.location.lon)
                if not all(40.47 <= lat <= 40.95 and -74.28 <= lon <= -73.65 for lat, lon in (a, b)):
                    continue
                meters = distance_meters(*a, *b)
                if meters <= 0 or meters > 1000:
                    continue
                self.nodes[first.ref] = a
                self.nodes[second.ref] = b
                self.edges.append((first.ref, second.ref, meters))
                self.edges.append((second.ref, first.ref, meters))
            if len(self.edges) >= 20_000:
                self.flush()

    try:
        handler = Walkways()
        handler.apply_file(str(pbf_path), locations=True)
        handler.flush()
        connection.executescript("CREATE INDEX edges_source ON edges(source); ANALYZE;")
        counts = (connection.execute("SELECT count(*) FROM nodes").fetchone()[0],
                  connection.execute("SELECT count(*) FROM edges").fetchone()[0])
        connection.commit()
        connection.close()
        temporary.replace(output_path)
        return {"nodes": counts[0], "directed_edges": counts[1], "source": str(pbf_path)}
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise


class WalkingNetwork:
    def __init__(self, path):
        self.path = Path(path)

    @lru_cache(maxsize=64)
    def catchment(self, latitude, longitude, minutes=10):
        import networkx as nx

        if not self.path.is_file():
            return None
        latitude, longitude = float(latitude), float(longitude)
        radius = minutes * 80
        lat_range = (radius + 350) / METERS_PER_DEGREE_LAT
        lon_range = lat_range / cos(radians(latitude))
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)) as connection:
            rows = connection.execute("""
                SELECT n.id, n.latitude, n.longitude FROM nodes n JOIN node_index r ON n.id=r.id
                WHERE r.min_lon BETWEEN ? AND ? AND r.min_lat BETWEEN ? AND ?
            """, (longitude - lon_range, longitude + lon_range,
                  latitude - lat_range, latitude + lat_range)).fetchall()
            if not rows:
                return None
            coordinates = {node_id: (lat, lon) for node_id, lat, lon in rows}
            origin = min(coordinates, key=lambda node: distance_meters(latitude, longitude, *coordinates[node]))
            snap = distance_meters(latitude, longitude, *coordinates[origin])
            if snap > 200:
                return None
            edges = connection.execute("""
                SELECT e.source, e.target, e.meters FROM edges e
                WHERE e.source IN (
                    SELECT id FROM node_index WHERE min_lon BETWEEN ? AND ? AND min_lat BETWEEN ? AND ?
                )
            """, (longitude - lon_range, longitude + lon_range,
                  latitude - lat_range, latitude + lat_range)).fetchall()
        graph = nx.Graph()
        graph.add_weighted_edges_from((source, target, meters) for source, target, meters in edges
                                      if source in coordinates and target in coordinates)
        if origin not in graph:
            return None
        distances = nx.single_source_dijkstra_path_length(graph, origin, cutoff=radius, weight="weight")
        return {"minutes": minutes, "radius_meters": radius, "origin_snap_meters": round(snap),
                "reachable_nodes": len(distances), "distances": distances,
                "coordinates": coordinates}

    def site_evidence(self, latitude, longitude, restaurants, stations, minutes=10):
        catchment = self.catchment(round(float(latitude), 6), round(float(longitude), 6), minutes)
        if catchment is None:
            return {"status": "unavailable", "reason": "No local walking-network match within 200 meters."}
        coordinates = catchment["coordinates"]
        distances = catchment["distances"]
        lat, lon = float(latitude), float(longitude)
        nearby_nodes = {node: point for node, point in coordinates.items() if node in distances}
        grid = defaultdict(list)
        for node, (node_lat, node_lon) in nearby_nodes.items():
            grid[(int(node_lat * 1000), int(node_lon * 1000))].append(node)

        def reachable(row):
            try:
                point = float(row["latitude"]), float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                return False
            if distance_meters(lat, lon, *point) > catchment["radius_meters"] + 100:
                return False
            cell_lat, cell_lon = int(point[0] * 1000), int(point[1] * 1000)
            candidates = [node for dy in range(-2, 3) for dx in range(-2, 3)
                          for node in grid.get((cell_lat + dy, cell_lon + dx), ())]
            if not candidates:
                return False
            node = min(candidates, key=lambda key: distance_meters(*point, *nearby_nodes[key]))
            return distance_meters(*point, *nearby_nodes[node]) <= 120 and distances[node] <= catchment["radius_meters"]

        local_restaurants = [row for row in restaurants
                             if str(row.get("active_establishment", "")).lower() == "true" and reachable(row)]
        return {
            "status": "available", "source": "Local OpenStreetMap pedestrian network",
            "minutes": minutes, "origin_snap_meters": catchment["origin_snap_meters"],
            "reachable_street_nodes": catchment["reachable_nodes"],
            "recorded_restaurants": len(local_restaurants),
            "nearby_subway_stations": sum(reachable(row) for row in stations),
            "restaurant_cuisine_counts": dict(Counter(
                row.get("cuisine_description", "Unclassified") for row in local_restaurants)),
        }
