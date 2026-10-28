"""Provisional real-data sample recovered from the user's truncated EPA archive."""

import math
from pathlib import Path

import h3
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape

from groundwork_backend.api import create_app
from groundwork_backend.config import Settings
from groundwork_backend.contracts import SourceRecord

SAMPLE = Path(__file__).resolve().parents[2] / "data/samples/walkability-smoke.jsonl"


@pytest.fixture
def records():
    if not SAMPLE.is_file():
        pytest.skip("Optional local walkability reference fixture is not installed.")
    return [SourceRecord.model_validate_json(line) for line in SAMPLE.read_text().splitlines() if line]


def test_real_records_fit_backend_ingestion_contract(records):
    assert len(records) == 20
    assert len({record.source_id for record in records}) == 20
    assert all(record.source == "walkability" for record in records)
    assert all(
        record.properties["recovery_status"] == "provisional_from_truncated_archive" for record in records
    )


def test_recovered_nyc_geometry_and_geographic_identifiers(records):
    for record in records:
        assert len(record.source_id) == 12
        assert record.source_id.startswith(("36005", "36047", "36061", "36081", "36085"))
        polygon = shape(record.geometry)
        assert polygon.is_valid and not polygon.is_empty
        west, south, east, north = polygon.bounds
        assert -74.30 <= west < east <= -73.65
        assert 40.45 <= south < north <= 40.95


def test_walkability_values_remain_on_original_scale(records):
    for record in records:
        value = record.properties["walkability"]
        assert math.isfinite(value) and 1 <= value <= 20
        assert math.isfinite(record.properties["smart_location_score"])
        assert record.properties["source_population"] >= 0
        assert record.properties["source_jobs"] >= 0


def test_recovered_locations_map_to_supported_h3_cells(records):
    for record in records:
        point = shape(record.geometry).representative_point()
        for resolution in (7, 8, 9):
            cell = h3.latlng_to_cell(point.y, point.x, resolution)
            assert h3.is_valid_cell(cell)
            assert h3.get_resolution(cell) == resolution


def test_api_remains_explicit_about_missing_database():
    with TestClient(create_app(Settings(), include_legacy=False)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert (
            client.post(
                "/api/v1/predictions/survival",
                json={"latitude": 40.75, "longitude": -73.97, "model_version": "not_supplied"},
            ).status_code
            == 503
        )
