"""Hierarchical H3 screening surface derived from the integrated tract model."""

import csv
import json
import math
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import h3
from shapely.geometry import shape
from shapely.strtree import STRtree


SECTOR_RESOLUTION = 7
CELL_RESOLUTION = 8
DEMAND_SIGNALS = ("demand", "customer_fit", "access", "market_gap", "competition_balance")


def surface_weights(profile_weights):
    total = sum(profile_weights[key] for key in DEMAND_SIGNALS)
    if total <= 0:
        raise ValueError("Demand signal weights must have a positive total.")
    return {key: profile_weights[key] / total for key in DEMAND_SIGNALS}


def boundary(cell):
    points = [[longitude, latitude] for latitude, longitude in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [points + [points[0]]]}


def miles(lat1, lon1, lat2, lon2):
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    delta_lat, delta_lon = lat2 - lat1, math.radians(lon2 - lon1)
    return 3958.7613 * 2 * math.asin(math.sqrt(math.sin(delta_lat / 2) ** 2 +
                                                math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2))


def subway_access(distance):
    return 100 / (1 + (distance / .35) ** 2)


@lru_cache(maxsize=4)
def grid(directory, cell_resolution=CELL_RESOLUTION, sector_resolution=SECTOR_RESOLUTION):
    if cell_resolution not in {8, 9} or sector_resolution != cell_resolution - 1:
        raise ValueError("Choose a supported parent-and-child H3 resolution pair.")
    directory = Path(directory)
    with (directory / "master_tract_features.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    eligible = {row["geoid"]: row for row in rows if row.get("eligible_for_location_screening", "").lower() in {"true", "1"}
                and row.get("borough") != "Staten Island" and row.get("centroid_latitude") and row.get("centroid_longitude")}
    features = json.loads((directory / "geography" / "nyc_2020_census_tracts.geojson").read_text())["features"]
    polygons, geoids, candidates = [], [], set()
    for feature in features:
        geoid = feature["properties"]["geoid"]
        if geoid not in eligible:
            continue
        polygons.append(shape(feature["geometry"]))
        geoids.append(geoid)
        candidates.update(h3.geo_to_cells(feature["geometry"], cell_resolution))
    # Include edge cells and tiny tracts that contain no H3 center.
    for geoid, row in eligible.items():
        candidates.add(h3.latlng_to_cell(float(row["centroid_latitude"]), float(row["centroid_longitude"]), cell_resolution))
    candidates.update(neighbor for cell in tuple(candidates) for neighbor in h3.grid_disk(cell, 1))
    tree = STRtree(polygons)
    result = []
    for cell in sorted(candidates):
        hexagon = shape(boundary(cell))
        overlaps = [(geoids[index], hexagon.intersection(polygons[index]).area)
                    for index in tree.query(hexagon, predicate="intersects")]
        overlaps = [(geoid, area) for geoid, area in overlaps if area > 0]
        total = sum(area for _, area in overlaps)
        if total < .1 * hexagon.area:
            continue
        shares = tuple(sorted((geoid, area / total) for geoid, area in overlaps))
        result.append((cell, shares, h3.cell_to_parent(cell, sector_resolution), min(1, total / hexagon.area)))
    return tuple(result)


def concept_surface(package, directory, concept, profile, weights, borough="", cell_resolution=CELL_RESOLUTION):
    rows = {row["geoid"]: row for row in package["tracts"] if not borough or row.get("borough") == borough}
    model = package["screening_model"]
    signal_weights = surface_weights(weights)
    tract_scores = {}
    for geoid, row in rows.items():
        components = model.evaluate(row, concept, weights, profile)["components"]
        score = sum(components[key]["score"] * weight for key, weight in signal_weights.items())
        coverage = sum(components[key]["coverage"] * weight for key, weight in signal_weights.items())
        tract_scores[geoid] = (score, coverage)
    stations = [(float(row["latitude"]), float(row["longitude"])) for row in package["subway_stations"]
                if row.get("latitude") and row.get("longitude")]
    cells, parents = [], defaultdict(list)
    for cell, shares, parent, land_fraction in grid(str(directory), cell_resolution, cell_resolution - 1):
        shares = [(geoid, weight) for geoid, weight in shares if geoid in tract_scores]
        total_weight = sum(weight for _, weight in shares)
        if not total_weight:
            continue
        shares = [(geoid, weight / total_weight) for geoid, weight in shares]
        base = sum(tract_scores[geoid][0] * weight for geoid, weight in shares)
        coverage = sum(tract_scores[geoid][1] * weight for geoid, weight in shares)
        latitude, longitude = h3.cell_to_latlng(cell)
        nearest = min((miles(latitude, longitude, lat, lon) for lat, lon in stations), default=None)
        prior_access = sum(subway_access(float(rows[geoid]["nearest_subway_distance_miles"])) * weight
                           for geoid, weight in shares if rows[geoid].get("nearest_subway_distance_miles") not in (None, ""))
        if nearest is not None and prior_access:
            base += signal_weights["access"] * (subway_access(nearest) - prior_access)
        score = round(max(0, min(100, base)))
        properties = {"id": cell, "parent_id": parent, "level": "cell", "score": score,
                      "coverage": round(coverage), "tract_count": len(shares),
                      "land_share": round(land_fraction * 100),
                      "borough": rows[max(shares, key=lambda item: item[1])[0]]["borough"]}
        cells.append({"type": "Feature", "geometry": boundary(cell), "properties": properties})
        parents[parent].append(properties)
    sectors = []
    for parent, children in sorted(parents.items()):
        land_weight = sum(item["land_share"] for item in children)
        sectors.append({"type": "Feature", "geometry": boundary(parent), "properties": {
            "id": parent, "level": "sector",
            "score": round(sum(item["score"] * item["land_share"] for item in children) / land_weight),
            "coverage": round(sum(item["coverage"] * item["land_share"] for item in children) / land_weight),
            "cell_count": len(children), "mean_land_share": round(sum(item["land_share"] for item in children) / len(children))}})
    return {"sector": sectors, "cell": cells}
