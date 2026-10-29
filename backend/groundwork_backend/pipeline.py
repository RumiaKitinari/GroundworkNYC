from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

import h3
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

from .contracts import SourceRecord
from .huff import DEFAULT_WEIGHTS, compute_huff
from .model import SurvivalModel
from .store import publish


def boundary(cell):
    points = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [points + [points[0]]]}


def ingest(url, path):
    """Atomically ingest normalized source JSONL. Replay is an idempotent upsert."""
    count = 0
    with psycopg.connect(url) as conn, Path(path).open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = SourceRecord.model_validate_json(line)
            required = {
                "acs": ("residents",),
                "lodes": ("workers",),
                "mta": ("transit_inflow",),
                "dohmh": ("capacity", "attractiveness"),
                "walkability": ("walkability",),
            }[row.source]
            for name in required:
                value = row.properties.get(name)
                import math

                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(f"{row.source}: {name} must be a finite nonnegative number.")
            if row.source in {"acs", "lodes"} and row.geometry["type"] not in {"Polygon", "MultiPolygon"}:
                raise ValueError("ACS/LODES counts require their geographic polygon boundaries.")
            if row.source in {"mta", "dohmh"} and row.geometry["type"] != "Point":
                raise ValueError("MTA/DOHMH entities require point geometry.")
            conn.execute(
                "INSERT INTO gw_sources(source,source_id,vintage,observed_at,geom,properties) "
                "VALUES (%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s) "
                "ON CONFLICT(source,source_id,vintage) DO UPDATE SET observed_at=excluded.observed_at, "
                "geom=excluded.geom,properties=excluded.properties",
                (
                    row.source,
                    row.source_id,
                    row.vintage,
                    row.observed_at,
                    json.dumps(row.geometry),
                    Jsonb(row.properties),
                ),
            )
            count += 1
    return count


def build_huff(url, snapshot, boundary_path, vintages, weights=None, radius=3):
    if set(vintages) != {"acs", "lodes", "mta", "dohmh"}:
        raise ValueError("Select exactly one vintage for ACS, LODES, MTA and DOHMH.")
    document = json.loads(Path(boundary_path).read_text())
    geography = (
        unary_union([shape(f["geometry"]) for f in document["features"]])
        if document["type"] == "FeatureCollection"
        else shape(document.get("geometry", document))
    )
    if geography.is_empty or not geography.is_valid:
        raise ValueError("Boundary must be a valid nonempty polygon.")
    west, south, east, north = geography.bounds
    if not (-74.30 <= west < east <= -73.65 and 40.45 <= south < north <= 40.95):
        raise ValueError("Boundary must be inside the NYC service extent.")
    all_features = []
    excluded = {}
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute(
            "CREATE TEMP TABLE chosen_sources AS SELECT * FROM gw_sources WHERE "
            "(source='acs' AND vintage=%s) OR (source='lodes' AND vintage=%s) OR "
            "(source='mta' AND vintage=%s) OR (source='dohmh' AND vintage=%s)",
            tuple(vintages[key] for key in ("acs", "lodes", "mta", "dohmh")),
        )
        present = {r["source"] for r in conn.execute("SELECT DISTINCT source FROM chosen_sources")}
        if present != set(vintages):
            raise ValueError(f"Missing source vintages: {sorted(set(vintages) - present)}")
        conn.execute("CREATE INDEX ON chosen_sources USING gist(geom)")
        for resolution in (7, 8, 9):
            cells = set(h3.geo_to_cells(mapping(box(*geography.bounds)), resolution))
            point = geography.representative_point()
            cells.add(h3.latlng_to_cell(point.y, point.x, resolution))
            cells.update(neighbor for cell in tuple(cells) for neighbor in h3.grid_disk(cell, 1))
            cells = sorted(cell for cell in cells if shape(boundary(cell)).intersects(geography))
            if len(cells) > 50000:
                raise ValueError("Grid exceeds 50,000 cells at one resolution; choose a smaller boundary.")
            conn.execute(
                "CREATE TEMP TABLE work_grid(id text PRIMARY KEY, geom geometry(Geometry,4326)) ON COMMIT DROP"
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO work_grid VALUES (%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))",
                    [
                        (cell, json.dumps(mapping(shape(boundary(cell)).intersection(geography))))
                        for cell in cells
                    ],
                )
            conn.execute("CREATE INDEX ON work_grid USING gist(geom)")
            # Equal-area allocation of polygon totals. Extensive counts are conserved over the covered boundary.
            rows = conn.execute("""
              SELECT g.id,
                sum((s.properties->>'median_income')::double precision * (s.properties->>'residents')::double precision *
                    ST_Area(ST_Transform(ST_Intersection(g.geom,s.geom),2263)) /
                    NULLIF(ST_Area(ST_Transform(s.geom,2263)),0)) FILTER(WHERE s.source='acs' AND s.properties ? 'median_income') /
                NULLIF(sum((s.properties->>'residents')::double precision *
                    ST_Area(ST_Transform(ST_Intersection(g.geom,s.geom),2263)) /
                    NULLIF(ST_Area(ST_Transform(s.geom,2263)),0)) FILTER(WHERE s.source='acs' AND s.properties ? 'median_income'),0)
                    AS median_income_proxy,
                sum((s.properties->>'residents')::double precision *
                    ST_Area(ST_Transform(ST_Intersection(g.geom,s.geom),2263)) /
                    NULLIF(ST_Area(ST_Transform(s.geom,2263)),0)) FILTER(WHERE s.source='acs') AS residents,
                sum((s.properties->>'workers')::double precision *
                    ST_Area(ST_Transform(ST_Intersection(g.geom,s.geom),2263)) /
                    NULLIF(ST_Area(ST_Transform(s.geom,2263)),0)) FILTER(WHERE s.source='lodes') AS workers,
                coalesce(sum((s.properties->>'transit_inflow')::double precision) FILTER(WHERE s.source='mta'),0) AS transit_inflow,
                coalesce(sum((s.properties->>'capacity')::double precision) FILTER(WHERE s.source='dohmh'),0) AS capacity,
                coalesce(sum((s.properties->>'attractiveness')::double precision) FILTER(WHERE s.source='dohmh'),0) AS attractiveness
              FROM work_grid g LEFT JOIN chosen_sources s ON s.geom && g.geom AND
                CASE WHEN s.source IN ('acs','lodes') THEN ST_Intersects(s.geom,g.geom)
                     ELSE ST_Contains(g.geom,s.geom) END
              GROUP BY g.id ORDER BY g.id
            """).fetchall()
            complete = [
                dict(row) for row in rows if row["residents"] is not None and row["workers"] is not None
            ]
            excluded[str(resolution)] = len(rows) - len(complete)
            if not complete:
                raise ValueError(f"No ACS/LODES overlap at H3 resolution {resolution}.")
            for row in compute_huff(complete, weights, radius):
                row["parent_id"] = h3.cell_to_parent(row["id"], resolution - 1)
                all_features.append({"type": "Feature", "geometry": boundary(row["id"]), "properties": row})
            conn.execute("DROP TABLE work_grid")
    metadata = {
        "method": "Huff with an outside option; straight-line distances",
        "vintages": vintages,
        "demand_weights": weights or DEFAULT_WEIGHTS,
        "neighbor_radius": radius,
        "distance_decay": 2.0,
        "outside_attractiveness": 1.0,
        "excluded_cells_missing_acs_or_lodes": excluded,
        "boundary_sha256": sha256(Path(boundary_path).read_bytes()).hexdigest(),
        "limitations": [
            "Scenario weights require calibration",
            "Transit and worker/resident overlap may double-count demand",
            "Capacity must use the same units and period as weighted demand",
            "Polygon counts use uniform areal allocation",
            "median_income_proxy is a population-weighted mean of source medians, not a hex median",
            "Partial source coverage is not a complete census",
            "No closure labels are used",
        ],
    }
    publish(url, snapshot, "huff", all_features, metadata)
    return len(all_features)


def export_screening(url, snapshot, arguments):
    from .api import concept_key, legacy_module
    from .provenance import screening_provenance

    legacy = legacy_module()
    key, canonical = concept_key(arguments)
    from scoring import Concept

    concept = Concept(**canonical["concept"])
    package = legacy.integrated_package()
    directory = legacy.integrated_directory()
    weights = legacy.PROFILE_WEIGHTS[canonical["profile"]]
    from hex_demand import concept_surface

    standard = concept_surface(
        package, directory, concept, canonical["profile"], weights, canonical["borough"], 8
    )
    fine = concept_surface(
        package, directory, concept, canonical["profile"], weights, canonical["borough"], 9
    )
    features = standard["sector"] + standard["cell"] + fine["cell"]
    if not features:
        raise ValueError("No screening cells are available for this concept.")
    publish(
        url,
        snapshot,
        "screening_" + key,
        features,
        {
            "data_release": package["data_release"],
            "concept": canonical,
            "assessment_type": "Uncalibrated Screening Index",
            "query_key": key,
            **screening_provenance(),
        },
    )
    return len(features)


def precompute(url, snapshot, artifact, manifest, batch_size=256):
    model = SurvivalModel(artifact, manifest)
    version = model.metadata["version"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", snapshot):
        raise ValueError("Invalid snapshot identifier.")
    if not 1 <= batch_size <= 4096:
        raise ValueError("Batch size must be between 1 and 4096.")
    count = 0
    # All predictions commit together. API never sees a half-computed batch.
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("model:" + version,))
        previous = conn.execute("SELECT metadata FROM gw_models WHERE version=%s", (version,)).fetchone()
        if previous and previous["metadata"] != model.metadata:
            raise ValueError("Model version is immutable; use a new version for a different artifact.")
        conn.execute(
            "INSERT INTO gw_models(version,metadata) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (version, Jsonb(model.metadata)),
        )
        with conn.cursor(name="prediction_features") as reader:
            reader.execute(
                "SELECT cell_id,properties FROM gw_hexes WHERE snapshot=%s AND layer='huff' AND resolution=%s ORDER BY cell_id",
                (snapshot, model.metadata["resolution"]),
            )
            while True:
                batch = reader.fetchmany(batch_size)
                if not batch:
                    break
                results = model.predict_batch([row["properties"] for row in batch])
                with conn.cursor() as writer:
                    writer.executemany(
                        "INSERT INTO gw_predictions(snapshot,layer,cell_id,model_version,payload) "
                        "VALUES (%s,'huff',%s,%s,%s) ON CONFLICT DO NOTHING",
                        [
                            (snapshot, row["cell_id"], version, Jsonb(result))
                            for row, result in zip(batch, results)
                        ],
                    )
                count += len(batch)
        if not count:
            raise ValueError("Snapshot has no Huff features.")
    return count
