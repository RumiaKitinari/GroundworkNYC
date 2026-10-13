import h3
import pytest
from fastapi.testclient import TestClient
from redis import RedisError

from groundwork_backend.api import concept_key, create_app
from groundwork_backend.config import Settings
from groundwork_backend.store import Unavailable


class FakeStore:
    def __init__(self):
        self.tile_calls = 0
        self.cell = h3.latlng_to_cell(40.75, -73.97, 8)

    def open(self):
        pass

    def close(self):
        pass

    def ready(self):
        return True

    def metadata(self, snapshot=None, layer=None):
        if snapshot == "missing":
            return None
        return {
            "snapshot": snapshot or "release_1",
            "metadata": {},
            "layers": [{"layer": "huff", "resolution": 8, "cells": 1}],
        }

    def has_layer(self, snapshot, layer, resolution):
        return snapshot != "missing" and layer == "huff" and resolution == 8

    def tile(self, *args):
        self.tile_calls += 1
        return b""

    def point(self, snapshot, layer, cell):
        return {"demand": 100, "outside_share": 0.3} if cell == self.cell else None

    def prediction(self, snapshot, layer, cell, version):
        return (
            {"survival_probability": 0.7, "horizon_months": 24}
            if version == "v1" and cell == self.cell
            else None
        )

    def models(self):
        return []


class FakeCache:
    def __init__(self, broken=False):
        self.data = {}
        self.broken = broken

    def get(self, key):
        if self.broken:
            raise RedisError("offline")
        return self.data.get(key)

    def setex(self, key, ttl, data):
        self.data[key] = data

    def close(self):
        pass


@pytest.fixture
def client():
    store, cache = FakeStore(), FakeCache()
    with TestClient(create_app(Settings(), store, cache, include_legacy=False)) as client:
        yield client, store, cache


def test_tiles_cache_empty_tiles_and_conditional_get(client):
    client, store, cache = client
    url = "/api/v1/tiles/release_1/huff/8/12/1206/1539.mvt"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    assert response.headers["x-cache"] == "MISS"
    second = client.get(url)
    assert second.headers["x-cache"] == "HIT"
    assert store.tile_calls == 1
    assert client.get(url, headers={"If-None-Match": response.headers["etag"]}).status_code == 304
    assert client.get(url.replace("release_1", "release_2")).headers["x-cache"] == "MISS"


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/tiles/r/huff/8/19/0/0.mvt",
        "/api/v1/tiles/r/huff/8/2/4/0.mvt",
        "/api/v1/tiles/r/huff/6/2/0/0.mvt",
        "/api/v1/tiles/r/huff/8/2/-1/0.mvt",
    ],
)
def test_invalid_tile_coordinates(client, url):
    assert client[0].get(url).status_code == 422


def test_unknown_snapshot_or_layer(client):
    assert client[0].get("/api/v1/tiles/missing/huff/8/2/0/0.mvt").status_code == 404
    assert client[0].get("/api/v1/tiles/r/unknown/8/2/0/0.mvt").status_code == 404


def test_cache_outage_does_not_break_tiles():
    with TestClient(create_app(Settings(), FakeStore(), FakeCache(True), include_legacy=False)) as client:
        assert client.get("/api/v1/tiles/r/huff/8/2/0/0.mvt").status_code == 200


def test_point_prediction_and_coverage_errors(client):
    client = client[0]
    point = {"latitude": 40.75, "longitude": -73.97}
    assert client.post("/api/v1/locations/analyze", json=point).json()["properties"]["demand"] == 100
    predicted = client.post("/api/v1/predictions/survival", json={**point, "model_version": "v1"})
    assert predicted.status_code == 200
    assert predicted.json()["prediction"]["survival_probability"] == 0.7
    assert (
        client.post("/api/v1/predictions/survival", json={**point, "model_version": "missing"}).status_code
        == 404
    )
    assert (
        client.post("/api/v1/locations/analyze", json={"latitude": 40.5, "longitude": -74.2}).status_code
        == 404
    )
    assert client.post("/api/v1/locations/analyze", json={**point, "extra": 1}).status_code == 422
    assert client.post("/api/v1/locations/analyze", json={**point, "latitude": 51}).status_code == 422


def test_missing_database_is_explicit():
    with TestClient(create_app(Settings(), include_legacy=False)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.get("/api/v1/spatial/manifest").status_code == 503


def test_no_precomputed_concept_does_not_fabricate_layer(client):
    assert client[0].get("/api/v1/spatial/resolve?cuisine=korean").status_code == 404


def test_concept_keys_ignore_presentation_and_budget():
    a, _ = concept_key({"cuisine": "korean", "rent_cap": "18000", "level": "sector"})
    b, _ = concept_key({"cuisine": "korean", "rent_cap": "22000", "level": "fine"})
    assert a == b
    assert a != concept_key({"cuisine": "italian"})[0]


def test_explicit_cors_allowlist():
    app = create_app(Settings(cors_origins=("https://example.com",)), FakeStore(), include_legacy=False)
    with TestClient(app) as client:
        assert (
            client.get("/health/live", headers={"Origin": "https://example.com"}).headers[
                "access-control-allow-origin"
            ]
            == "https://example.com"
        )
        assert (
            "access-control-allow-origin"
            not in client.get("/health/live", headers={"Origin": "https://untrusted.com"}).headers
        )


def test_legacy_dashboard_auth_and_missing_private_data():
    with TestClient(create_app(Settings(), FakeStore(), include_legacy=True)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/menu/suggestions?cuisine=korean").status_code == 200
        assert client.post("/auth/login", data={"email": "a@example.com", "password": "x"}).status_code == 400
        assert client.get("/api/dashboard").status_code == 503
        assert client.get("/health/live").status_code == 200


def test_layer_specific_active_snapshot_lookup():
    class LayerStore(FakeStore):
        def metadata(self, snapshot=None, layer=None):
            if layer and layer.startswith("screening_"):
                return {
                    "snapshot": "screening_2",
                    "metadata": {},
                    "layers": [{"layer": layer, "resolution": 8}],
                }
            return super().metadata(snapshot, layer)

    with TestClient(create_app(Settings(), LayerStore(), include_legacy=False)) as client:
        assert client.get("/api/v1/spatial/resolve?cuisine=korean").json()["snapshot"] == "screening_2"
        assert (
            client.post("/api/v1/locations/analyze", json={"latitude": 40.75, "longitude": -73.97}).json()[
                "snapshot"
            ]
            == "release_1"
        )


def test_unavailable_store_returns_503():
    class Offline(FakeStore):
        def metadata(self, snapshot=None, layer=None):
            raise Unavailable("Not published")

    with TestClient(create_app(Settings(), Offline(), include_legacy=False)) as client:
        assert client.get("/api/v1/spatial/manifest").status_code == 503


def test_workspace_cors_preflight_preserves_put_and_csrf_header():
    with TestClient(
        create_app(Settings(cors_origins=("https://example.com",)), FakeStore(), include_legacy=False)
    ) as client:
        response = client.options(
            "/api/workspace",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type,x-csrf-token",
            },
        )
        assert response.status_code == 200
        assert "PUT" in response.headers["access-control-allow-methods"]


def test_huff_manifest_returns_pinned_vector_urls(client):
    data = client[0].get("/api/v1/spatial/huff").json()
    assert data["snapshot"] == "release_1"
    assert data["source_layer"] == "demand"
    assert data["tiles"]["8"] == "/api/v1/tiles/release_1/huff/8/{z}/{x}/{y}.mvt"
