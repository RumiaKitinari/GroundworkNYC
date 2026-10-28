import json

from map_geography import city_partition
from shapely.geometry import box, mapping, shape


def test_partition_preserves_city_islands_and_excludes_city_from_mask(tmp_path):
    first = box(-74.02, 40.70, -74.00, 40.75)
    first = first.difference(box(-74.015, 40.72, -74.01, 40.73))
    second = box(-74.15, 40.55, -74.10, 40.60)
    path = tmp_path / "tracts.geojson"
    path.write_text(json.dumps({"type":"FeatureCollection", "features":[
        {"type":"Feature", "geometry":mapping(geometry)} for geometry in (first, second)]}))
    result = city_partition(str(path))
    city, outside = [shape(feature["geometry"]) for feature in result["features"][:2]]
    assert city.covers(first.representative_point())
    assert city.covers(second.representative_point())
    assert city.intersection(outside).area == 0
    assert result["meta"]["tract_count"] == 2
    assert city.is_valid and outside.is_valid
    assert len(shape(result["features"][2]["geometry"]).geoms) == 2


def test_live_boundary_uses_complete_integrated_geography():
    from app import app
    response = app.test_client().get("/api/geography/nyc-boundary")
    assert response.status_code == 200
    result = response.json
    assert result["meta"]["tract_count"] == 2327
    assert result["meta"]["cartographic_only"]
    assert {row["properties"]["kind"] for row in result["features"]} == {"city", "outside", "outline"}


def test_tiny_display_seams_removed_without_erasing_islands_or_large_holes(tmp_path):
    outer = box(-74.02, 40.70, -74.00, 40.75)
    tiny = box(-74.019, 40.701, -74.0189, 40.7011)
    large = box(-74.015, 40.72, -74.01, 40.73)
    island = box(-74.05, 40.69, -74.0499, 40.6901)
    path = tmp_path / "seams.geojson"
    path.write_text(json.dumps({"features": [{"geometry": mapping(outer.difference(tiny).difference(large))}, {"geometry": mapping(island)}]}))
    result = city_partition(str(path))
    city = shape(result["features"][0]["geometry"])
    assert city.covers(tiny.representative_point())
    assert not city.covers(large.representative_point())
    assert city.covers(island.representative_point())
    assert result["meta"]["display_seams_removed"] == 1
