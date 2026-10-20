"""Run only against a disposable TEST_DATABASE_URL; never use a live database."""

import json
import os
from uuid import uuid4

import h3
import mapbox_vector_tile
import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from shapely.geometry import box, mapping

from groundwork_backend.pipeline import boundary, build_huff, ingest, precompute
from groundwork_backend.store import Store, migrate, publish

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostGIS integration tests.")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    from psycopg.conninfo import make_conninfo

    isolated = make_conninfo(url, options=f"-c search_path={schema},public")
    try:
        migrate(isolated)
        yield isolated
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_schema_publication_mvt_and_immutable_snapshots(database):
    cell = h3.latlng_to_cell(40.75, -73.97, 8)
    feature = {"type": "Feature", "geometry": boundary(cell), "properties": {"id": cell, "score": 75}}
    publish(database, "first", "huff", [feature], {"test": True})
    store = Store(database)
    store.open()
    try:
        assert store.metadata(layer="huff")["snapshot"] == "first"
        assert store.metadata(layer="screening_unpublished") is None
        tile = store.tile("first", "huff", 8, 12, 1206, 1539)
        decoded = mapbox_vector_tile.decode(tile)
        assert decoded["demand"]["features"][0]["properties"]["score"] == 75
        with pytest.raises(psycopg.errors.UniqueViolation):
            publish(database, "first", "huff", [feature], {})
        assert store.metadata(layer="huff")["snapshot"] == "first"
        assert store.has_layer("first", "huff", 8)
        publish(database, "screening", "screening_test", [feature], {})
        assert store.metadata(layer="huff")["snapshot"] == "first"
        assert store.metadata(layer="screening_test")["snapshot"] == "screening"
    finally:
        store.close()


def test_source_replay_and_areal_huff_pipeline(database, tmp_path, artifact):
    geography = mapping(box(-73.985, 40.745, -73.955, 40.775))
    sources = [
        {
            "source": "acs",
            "source_id": "tract",
            "properties": {"residents": 1000, "median_income": 80000},
            "geometry": geography,
        },
        {"source": "lodes", "source_id": "block", "properties": {"workers": 500}, "geometry": geography},
        {
            "source": "mta",
            "source_id": "station",
            "properties": {"transit_inflow": 100},
            "geometry": {"type": "Point", "coordinates": [-73.97, 40.75]},
        },
        {
            "source": "dohmh",
            "source_id": "restaurant",
            "properties": {"capacity": 50, "attractiveness": 1},
            "geometry": {"type": "Point", "coordinates": [-73.97, 40.75]},
        },
    ]
    path = tmp_path / "source.jsonl"
    path.write_text(
        "\n".join(json.dumps({**r, "vintage": "test", "observed_at": "2026-10-08"}) for r in sources)
    )
    assert ingest(database, path) == 4
    assert ingest(database, path) == 4
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM gw_sources").fetchone()[0] == 4
    boundary_path = tmp_path / "boundary.json"
    boundary_path.write_text(json.dumps(geography))
    assert (
        build_huff(
            database,
            "huff_test",
            boundary_path,
            {source: "test" for source in ("acs", "lodes", "mta", "dohmh")},
        )
        > 0
    )
    with psycopg.connect(database, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT properties FROM gw_hexes WHERE snapshot='huff_test' AND resolution=8"
        ).fetchall()
        assert sum(row["properties"]["residents"] for row in rows) == pytest.approx(1000)
        assert sum(row["properties"]["workers"] for row in rows) == pytest.approx(500)
        assert sum(row["properties"]["capacity"] for row in rows) == pytest.approx(50)
        assert all(row["properties"]["median_income_proxy"] == pytest.approx(80000) for row in rows)

    assert precompute(database, "huff_test", artifact[0], artifact[1]) == len(rows)
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM gw_predictions").fetchone()[0] == len(rows)
