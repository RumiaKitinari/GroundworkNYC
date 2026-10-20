import json
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


class Unavailable(Exception):
    pass


class Store:
    def __init__(self, url):
        self.pool = (
            ConnectionPool(
                url,
                min_size=0,
                max_size=8,
                timeout=5,
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": 5,
                    "options": (
                        conninfo_to_dict(url).get("options", "") + " -c statement_timeout=15000"
                    ).strip(),
                },
                open=False,
            )
            if url
            else None
        )

    def open(self):
        if self.pool:
            self.pool.open()

    def close(self):
        if self.pool:
            self.pool.close()

    def connection(self):
        if not self.pool:
            raise Unavailable("Spatial database is not configured.")
        return self.pool.connection()

    def ready(self):
        with self.connection() as conn:
            conn.execute("SELECT 1 FROM gw_snapshots LIMIT 1")
        return True

    def metadata(self, snapshot=None, layer=None):
        with self.connection() as conn:
            if not snapshot:
                row = conn.execute(
                    "SELECT snapshot FROM gw_active WHERE (%s::text IS NULL OR layer=%s) "
                    "ORDER BY activated_at DESC LIMIT 1",
                    (layer, layer),
                ).fetchone()
                if not row:
                    if layer:
                        return None
                    raise Unavailable("No spatial snapshot has been published.")
                snapshot = row["snapshot"]
            row = conn.execute("SELECT id, metadata FROM gw_snapshots WHERE id=%s", (snapshot,)).fetchone()
            if row is None:
                return None
            layers = conn.execute(
                "SELECT layer, resolution, count(*) AS cells FROM gw_hexes "
                "WHERE snapshot=%s GROUP BY layer,resolution ORDER BY layer,resolution",
                (snapshot,),
            ).fetchall()
            return {"snapshot": row["id"], "metadata": row["metadata"], "layers": layers}

    def point(self, snapshot, layer, cell):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT properties FROM gw_hexes WHERE snapshot=%s AND layer=%s AND cell_id=%s",
                (snapshot, layer, cell),
            ).fetchone()
            return row["properties"] if row else None

    def prediction(self, snapshot, layer, cell, version):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM gw_predictions WHERE snapshot=%s AND layer=%s "
                "AND cell_id=%s AND model_version=%s",
                (snapshot, layer, cell, version),
            ).fetchone()
            return row["payload"] if row else None

    def models(self):
        with self.connection() as conn:
            return conn.execute("SELECT version, metadata FROM gw_models ORDER BY version").fetchall()

    def has_layer(self, snapshot, layer, resolution):
        with self.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM gw_hexes WHERE snapshot=%s AND layer=%s AND resolution=%s LIMIT 1",
                    (snapshot, layer, resolution),
                ).fetchone()
                is not None
            )

    def tile(self, snapshot, layer, resolution, z, x, y):
        # Filter in geographic coordinates to use the GiST index, then clip in Web Mercator.
        sql = """
        WITH bounds AS (SELECT ST_TileEnvelope(%s,%s,%s) AS geom),
        features AS (
          SELECT h.cell_id AS id, h.parent_id, h.properties,
                 ST_AsMVTGeom(ST_Transform(h.geom,3857), b.geom,4096,64,true) AS geom
          FROM gw_hexes h CROSS JOIN bounds b
          WHERE snapshot=%s AND layer=%s AND resolution=%s
            AND h.geom && ST_Transform(ST_Expand(b.geom,
                  (ST_XMax(b.geom)-ST_XMin(b.geom))*64.0/4096),4326)
        ) SELECT ST_AsMVT(features,'demand',4096,'geom') AS tile FROM features WHERE geom IS NOT NULL
        """
        with self.connection() as conn:
            row = conn.execute(sql, (z, x, y, snapshot, layer, resolution)).fetchone()
            return bytes(row["tile"] or b"")


def migrate(url):
    script = Path(__file__).resolve().parents[1] / "sql" / "001_initial.sql"
    with psycopg.connect(url) as conn:
        conn.execute(script.read_text())


def publish(url, snapshot, layer, features, metadata):
    # A snapshot is immutable after first publication. All rows and pointer commit together.
    import h3

    with psycopg.connect(url) as conn:
        conn.execute("INSERT INTO gw_snapshots(id,metadata) VALUES (%s,%s)", (snapshot, Jsonb(metadata)))
        with conn.cursor() as cursor:
            for feature in features:
                props = feature["properties"]
                cell = props["id"]
                cursor.execute(
                    "INSERT INTO gw_hexes(snapshot,layer,resolution,cell_id,parent_id,geom,properties) "
                    "VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s)",
                    (
                        snapshot,
                        layer,
                        h3.get_resolution(cell),
                        cell,
                        props.get("parent_id"),
                        json.dumps(feature["geometry"]),
                        Jsonb(props),
                    ),
                )
        conn.execute(
            "INSERT INTO gw_active(layer,snapshot) VALUES (%s,%s) "
            "ON CONFLICT(layer) DO UPDATE SET snapshot=excluded.snapshot,activated_at=now()",
            (layer, snapshot),
        )
