"""Cartographic NYC extent from the complete integrated tract geography."""
import json
from functools import lru_cache
from pathlib import Path

from shapely import make_valid
from shapely.geometry import MultiLineString, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union


@lru_cache(maxsize=4)
def city_partition(path, signature=None):
    source = json.loads(Path(path).read_text())
    polygons = []
    for feature in source["features"]:
        geometry = shape(feature["geometry"])
        if not geometry.is_valid:
            geometry = make_valid(geometry)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty:
            raise ValueError("NYC geography contains a non-polygon feature.")
        polygons.append(geometry)
    if not polygons:
        raise ValueError("NYC geography is empty.")
    # Cartographic simplification only; analytical tract geometry remains untouched.
    city = unary_union(polygons).simplify(.00008, preserve_topology=True)
    parts = list(city.geoms) if city.geom_type == "MultiPolygon" else [city]
    # Sub-hectare internal slivers are tract stitching artifacts, not useful city-mask detail.
    # Retain all detached islands and larger holes; never alter analytical source geometry.
    removed = sum(Polygon(ring).area < .000001 for part in parts for ring in part.interiors)
    parts = [Polygon(part.exterior, [ring for ring in part.interiors if Polygon(ring).area >= .000001]) for part in parts]
    city = MultiPolygon(parts) if len(parts) > 1 else parts[0]
    # Internal tract seams are not city limits; retain only exterior outline rings.
    outline = MultiLineString([part.exterior.coords for part in parts])
    context = box(-75.5, 39.8, -72.5, 41.6)
    if not context.covers(city):
        raise ValueError("NYC geography extends beyond the supported map context.")
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"kind": "city"}, "geometry": mapping(city)},
        {"type": "Feature", "properties": {"kind": "outside"}, "geometry": mapping(context.difference(city))},
        {"type": "Feature", "properties": {"kind": "outline"}, "geometry": mapping(outline)},
    ], "meta": {"basis": "Union of integrated 2020 NYC census tract boundaries",
                 "tract_count": len(polygons), "geography_vintage": "2020",
                 "display_seams_removed": removed,
                 "cartographic_only": True}}
