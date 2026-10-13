from __future__ import annotations

import importlib.util
import logging
import re
import sys
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

import h3
import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg_pool import PoolTimeout
from redis import Redis, RedisError
from starlette.middleware.wsgi import WSGIMiddleware

from .config import Settings
from .contracts import PointRequest, PredictionRequest
from .store import Store, Unavailable

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)
TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def legacy_module():
    directory = str(ROOT / "demo")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    spec = importlib.util.spec_from_file_location("groundwork_legacy_app", ROOT / "demo" / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def concept_key(arguments):
    import json

    directory = str(ROOT / "demo")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    from scoring import resolve_concept

    resolved = resolve_concept(arguments)
    borough = arguments.get("borough", "")
    if borough not in {"", "Manhattan", "Brooklyn", "Queens", "Bronx"}:
        raise ValueError("Choose a supported borough.")
    canonical = {"concept": resolved["concept"], "profile": resolved["profile"], "borough": borough}
    return sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:20], canonical


def create_app(settings=None, store=None, cache=None, include_legacy=True):
    settings = settings or Settings.from_env()
    store = store or Store(settings.database_url)
    if cache is None and settings.redis_url:
        cache = Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)

    @asynccontextmanager
    async def lifespan(app):
        store.open()
        yield
        store.close()
        if cache:
            cache.close()

    app = FastAPI(title="GroundworkNYC Backend", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "If-None-Match", "X-CSRF-Token"],
        expose_headers=["ETag", "X-Snapshot", "X-Cache"],
    )

    @app.exception_handler(Unavailable)
    async def unavailable(request, error):
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": "service_unavailable", "detail": str(error)}, status_code=503)

    async def database_error(request, error):
        from fastapi.responses import JSONResponse

        log.error("Database request failed: %s", type(error).__name__)
        return JSONResponse(
            {"error": "service_unavailable", "detail": "Spatial database is unavailable."}, status_code=503
        )

    for kind in (psycopg.OperationalError, psycopg.ProgrammingError, PoolTimeout):
        app.add_exception_handler(kind, database_error)

    def metadata(snapshot=None, layer=None):
        if snapshot and not TOKEN.fullmatch(snapshot):
            raise HTTPException(422, "Invalid snapshot identifier.")
        result = store.metadata(snapshot, layer)
        if result is None:
            raise HTTPException(404, "Snapshot not found.")
        return result

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        store.ready()
        current = metadata()
        return {"status": "ok", "snapshot": current["snapshot"], "cache_required": False}

    @app.get("/api/v1/spatial/manifest")
    def manifest():
        return metadata()

    @app.get("/api/v1/spatial/resolve")
    def resolve(request: Request):
        try:
            key, _ = concept_key(dict(request.query_params))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        layer = "screening_" + key
        current = metadata(layer=layer)
        resolutions = {row["resolution"] for row in current["layers"] if row["layer"] == layer}
        if not resolutions:
            raise HTTPException(
                404, "This concept has no precomputed tile layer. Use the screening GeoJSON API."
            )
        base = f"/api/v1/tiles/{current['snapshot']}/{layer}"
        return {
            "snapshot": current["snapshot"],
            "assessment_type": "Uncalibrated Screening Index",
            "source_layer": "demand",
            "tiles": {str(r): f"{base}/{r}/{{z}}/{{x}}/{{y}}.mvt" for r in sorted(resolutions)},
        }

    @app.get("/api/v1/spatial/huff")
    def huff_manifest():
        current = metadata(layer="huff")
        resolutions = {row["resolution"] for row in current["layers"] if row["layer"] == "huff"}
        base = f"/api/v1/tiles/{current['snapshot']}/huff"
        return {
            "snapshot": current["snapshot"],
            "assessment_type": "Huff demand allocation scenario",
            "metadata": current["metadata"],
            "source_layer": "demand",
            "tiles": {str(r): f"{base}/{r}/{{z}}/{{x}}/{{y}}.mvt" for r in sorted(resolutions)},
        }

    @app.post("/api/v1/locations/analyze")
    def analyze(payload: PointRequest):
        current = metadata(payload.snapshot, "huff")
        cell = h3.latlng_to_cell(payload.latitude, payload.longitude, payload.resolution)
        properties = store.point(current["snapshot"], "huff", cell)
        if properties is None:
            raise HTTPException(404, "Location has no published Huff data at this resolution.")
        return {
            "cell_id": cell,
            "snapshot": current["snapshot"],
            "assessment_type": "Huff demand allocation scenario",
            "properties": properties,
        }

    @app.get("/api/v1/models")
    def models():
        return {"models": store.models()}

    @app.post("/api/v1/predictions/survival")
    def survival(payload: PredictionRequest):
        current = metadata(payload.snapshot, "huff")
        cell = h3.latlng_to_cell(payload.latitude, payload.longitude, payload.resolution)
        prediction = store.prediction(current["snapshot"], "huff", cell, payload.model_version)
        if prediction is None:
            raise HTTPException(404, "No precomputed prediction exists for this location and model version.")
        return {"cell_id": cell, "snapshot": current["snapshot"], "prediction": prediction}

    @app.get("/api/v1/tiles/{snapshot}/{layer}/{resolution}/{z}/{x}/{y}.mvt")
    def tile(request: Request, snapshot: str, layer: str, resolution: int, z: int, x: int, y: int):
        if (
            not TOKEN.fullmatch(layer)
            or resolution not in {7, 8, 9}
            or not 0 <= z <= 18
            or not 0 <= x < 2**z
            or not 0 <= y < 2**z
        ):
            raise HTTPException(422, "Invalid tile coordinates or layer.")
        if not TOKEN.fullmatch(snapshot):
            raise HTTPException(422, "Invalid snapshot identifier.")
        key = f"gw:tile:v1:{snapshot}:{layer}:{resolution}:{z}:{x}:{y}"
        data = None
        if cache:
            try:
                data = cache.get(key)
            except RedisError:
                log.warning("Tile cache unavailable; reading PostGIS.")
        hit = data is not None
        if data is None:
            if not store.has_layer(snapshot, layer, resolution):
                raise HTTPException(404, "Snapshot, layer or resolution not found.")
            data = store.tile(snapshot, layer, resolution, z, x, y)
            if cache:
                try:
                    cache.setex(key, settings.tile_ttl, data)
                except RedisError:
                    log.warning("Tile cache write unavailable.")
        etag = '"' + sha256(data).hexdigest() + '"'
        headers = {
            "ETag": etag,
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Snapshot": snapshot,
            "X-Cache": "HIT" if hit else "MISS",
        }
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type="application/vnd.mapbox-vector-tile", headers=headers)

    if include_legacy:
        legacy = legacy_module()

        @legacy.app.context_processor
        def spatial_context():
            import os

            return {
                "spatial_backend_enabled": bool(settings.database_url),
                "real_data_preview": os.getenv("GROUNDWORK_PREVIEW") == "1",
            }

        import os

        if os.getenv("GROUNDWORK_PREVIEW") == "1" and not settings.production:

            @legacy.app.get("/demo")
            def open_preview():
                from flask import redirect, session

                if session.get("access") != "account":
                    session["access"] = "guest"
                return redirect("/?demo=1")

        legacy.app.config["SESSION_COOKIE_SECURE"] = settings.production
        legacy.app.config["MAX_CONTENT_LENGTH"] = 1_000_000

        @legacy.app.errorhandler(FileNotFoundError)
        def missing_data(error):
            from flask import jsonify

            return jsonify({"error": "Required private dataset is unavailable. See backend/README.md."}), 503

        app.mount("/", WSGIMiddleware(legacy.app))
    return app


app = create_app()
