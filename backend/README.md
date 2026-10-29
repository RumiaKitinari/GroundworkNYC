# GroundworkNYC backend

This implementation adds a FastAPI service, PostGIS storage, Redis tile caching, offline Huff demand allocation, and XGBoost model serving to the supplied frontend. The existing Flask dashboard remains mounted at `/`, so login, guest access, saved workspaces, briefs, menus, rankings, and existing API paths keep their contracts. OpenAPI documentation for the new endpoints is at `/docs`.

**Integration status:** the Flask dashboard and a concept-screening vector layer were tested through this service with the local integrated release. PostGIS serves the tiles and Redis caches repeat tile requests. Huff demand allocation and survival-model predictions remain unpublished. The integrated datasets stay local, and no trained survival model is supplied. This is a local screening demo, not a calibrated forecasting service.

## Start with Docker

### Current Combined Local Runtime

The preferred local entry point is `.venv/bin/python run_local.py` from the
repository root, with the existing Compose database/Redis services running.
Install `backend/requirements-dashboard.txt` into the current project environment.
This adds the service dependencies without downgrading the feature pipeline's
NumPy/pandas environment to the standalone backend's Python 3.12 pins.

The launcher reads the private `.env` without printing credentials. Explicit
`DATABASE_URL`/`REDIS_URL` settings take precedence; otherwise it uses the existing
Compose loopback ports, 15432 and 16379, with `POSTGRES_PASSWORD`. It checks the
database before starting, reports Redis availability, and serves the combined
app at `http://127.0.0.1:5001` by default. `--check` checks services without
starting a listener. `--port 8000` selects an alternative port.

Storage responsibilities remain explicit: PostGIS stores immutable published
spatial layers and model batches; Redis is an expendable tile cache; original
and integrated source artifacts remain local files; accounts and saved
workspaces/menus remain in `instance/accounts.sqlite3`. No SQLite-to-Postgres
account migration is implied or performed. This is still a local prototype,
not a complete production authentication/deployment setup.

### Standalone Container Setup

From the repository root:

```bash
cp .env.example .env
# Replace both secret placeholders with separate random URL-safe values.
# For example: python -c 'import secrets; print(secrets.token_urlsafe(48))'
docker compose up --build
```

Open `http://localhost:8000` for the existing UI and `http://localhost:8000/docs` for the new API. The migration service initializes PostGIS before the API starts. Database, Redis and API ports bind to loopback only (15432, 16379 and 8000 respectively). The PostgreSQL image targets Linux containers; Apple Silicon Docker installations may need x86 emulation for this PostGIS image.

If Docker Desktop rejects the `./data` bind mount because the project directory is not shared with Docker, leave the API on the host and run only the infrastructure in Compose. From the repository root, with the separate `backend/.venv` installed:

```bash
docker compose up -d db redis migrate
set -a; source .env; set +a
export DATABASE_URL="postgresql://groundwork:${POSTGRES_PASSWORD}@127.0.0.1:15432/groundwork"
export REDIS_URL="redis://127.0.0.1:16379/0"
backend/.venv/bin/uvicorn groundwork_backend.api:app --app-dir backend --host 127.0.0.1 --port 8000
```

The host API reads the same local `data/integrated/current/` release. Use `http://127.0.0.1:8000/`, not the standalone Flask port, to test spatial tiles. Keep the generated `.env` private.

The UI entry screen can load without private data. The dashboard returns a clear 503 until the required dataset is supplied. `/health/live` checks that the service runs; `/health/ready` also requires the database schema and at least one published spatial snapshot. Redis is an optional acceleration layer, so its failure does not prevent PostGIS from serving tiles.

For deployment behind HTTPS, set `APP_ENV=production`, a stable `GROUNDWORK_SECRET_KEY` of at least 32 characters, and the relevant frontend origins in `CORS_ORIGINS`. Production enables secure session cookies. The Compose configuration is for local development; choose managed database backups, HTTPS termination and operational monitoring before deployment.

## Run locally without Docker

Use Python 3.12 in a separate backend environment:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
cd backend
.venv/bin/uvicorn groundwork_backend.api:app --host 127.0.0.1 --port 8000
```

Configure `DATABASE_URL` and optionally `REDIS_URL` in the process environment. On macOS, XGBoost also needs an OpenMP runtime (`brew install libomp`). The API itself does not import XGBoost at request time; only offline prediction batches require it. Standalone `python demo/app.py` continues to work as before.

## Restore the existing dashboard data

The local Flask demo reads `data/integrated/current/`, a symlink to the active validated release. Keep the private package there with at least:

```text
data/integrated/current/
  master_tract_features.csv
  source_catalog.csv
  feature_readiness.csv
  entities/current_restaurants.csv
  entities/current_storefronts.csv
  entities/subway_stations_weekly_activity.csv
  geography/nyc_2020_census_tracts.geojson
```

The geography file is required for the hex map and vector tile export. The first six files support the dashboard. Existing download and refresh tools in `demo/` remain available; follow `demo/README.md` for their source-specific preprocessing. Optional walking-network, MBTiles, verified property and concept-image files keep their existing paths.

## Publish the current concept map as vector tiles

Edit `backend/examples/concept-query.json` to use the dashboard's query arguments. Every normalized combination of cuisine, service style, price and audience gets its own concept key. Rent budgets, map detail level and other presentation settings do not change that key because the existing concept surface does not score them.

```bash
docker compose run --rm api python -m groundwork_backend.cli export-screening \
  --snapshot screening_korean_20261008 \
  --query /app/backend/examples/concept-query.json
```

With the host API workaround, run the exporter in a second terminal after setting `DATABASE_URL` as above and `PYTHONPATH=backend`:

```bash
backend/.venv/bin/python -m groundwork_backend.cli export-screening \
  --snapshot screening_default_YYYYMMDD \
  --query backend/examples/concept-query.json
```

This precomputes H3 resolutions 7, 8 and 9 with the existing scoring model. The frontend asks `/api/v1/spatial/resolve` for the matching immutable tile URLs. Published concepts use vector tiles; concepts without a matching export retain `/api/hex-demand` GeoJSON. A budget or map-style change does not rerun the offline surface computation.

Use a new snapshot name for every release. Snapshot identifiers contain 1-80 letters, digits, underscores or hyphens. Publishing commits geometry, metadata and the active-layer pointer in one transaction. A failed publication leaves the previous layer active. Active pointers are independent for Huff and each concept, so publishing screening tiles never hides a Huff release. Older snapshot URLs continue to work. Refresh the dashboard after publishing a new release.

## Ingest source exports and build Huff demand

The ingestion boundary is **versioned normalized JSONL**, rather than hard-coded assumptions about every source's changing CSV layout. The existing source download scripts provide the acquisition step; the new normalizer maps cleaned exports to the spatial contract.

Each JSONL record includes:

| Field | Meaning |
| --- | --- |
| `source` | `acs`, `lodes`, `mta`, `dohmh`, or `walkability` |
| `source_id` | Unique geographic or current-entity identifier |
| `vintage` | Explicit release or observation period |
| `observed_at` | Provenance timestamp or date |
| `geometry` | WGS84 GeoJSON; polygons for ACS/LODES, points for MTA/DOHMH |
| `properties` | Numeric source metrics and optional retained context |

Required metrics are `residents` for ACS, `workers` for LODES, `transit_inflow` for MTA, and `capacity` plus `attractiveness` for current restaurant supply. Optional ACS `median_income` becomes `median_income_proxy`: a population-weighted mean of source medians, explicitly not an estimated hex median. Walkability records may be staged, but the new Huff pipeline does not use them; the original concept screening and site-analysis APIs retain their walking evidence.

A small example record:

```json
{"source":"mta","source_id":"station_1","vintage":"2026-week-36","observed_at":"2026-09-07","geometry":{"type":"Point","coordinates":[-73.97,40.75]},"properties":{"transit_inflow":1000}}
```

For CSV exports, make a mapping based on `examples/acs-column-mapping.json`. The normalizer supports polygon joins by GEOID or point coordinates and explicit constants for scenario parameters. It rejects duplicate IDs; raw DOHMH inspection histories must first be reduced to a validated current-establishment inventory. DOHMH inspection records do not provide measured restaurant capacity: supply capacity and attractiveness must come from explicit scenario assumptions or partner data. Do not silently treat every inspection row as another restaurant.

```bash
# Run on the host with the backend environment installed.
cd backend
.venv/bin/python -m groundwork_backend.cli normalize \
  --input ../data/cleaned_sources/acs.csv \
  --mapping examples/acs-column-mapping.json \
  --geography ../data/integrated/current/geography/nyc_2020_census_tracts.geojson \
  --output ../data/normalized/acs.jsonl
cd ..

# Repeat normalization with the appropriate mappings for the other sources.
docker compose run --rm api python -m groundwork_backend.cli ingest /app/data/normalized/acs.jsonl
```

Ingestion is transactional and replayable, keyed by source, source ID and vintage. Validation failure rolls back the import. Select exactly one vintage for each of the four required sources in a file like `examples/vintages.json`. Supply a polygon or FeatureCollection defining the NYC study boundary.

```bash
docker compose run --rm api python -m groundwork_backend.cli build-huff \
  --snapshot huff_20261008 \
  --boundary /app/data/geography/study_boundary.geojson \
  --vintages /app/backend/examples/vintages.json
```

This creates H3 grids at resolutions 7, 8 and 9, allocates extensive polygon counts by projected overlap area, and calculates Huff allocations offline. Cells without ACS or LODES observations are excluded and counted in release metadata. Partial coverage still needs source QA. Supply and transit entities are allocated to containing cells. Demand is conserved across captured and outside-option demand within the modeled study area.

The default demand scenario is `residents + 0.5 * workers + 0.1 * transit_inflow`. Optional `--weights` accepts a JSON file with those three weights; `--radius` controls a bounded H3 neighborhood, 1-10 rings. Defaults are scenario assumptions, not measured restaurant visits. Normalize periods, prevent demographic/mobility double counting, and calibrate weights, distance decay, outside attractiveness and supply capacity before drawing business conclusions. Straight-line distances are used; the existing walking-graph analysis remains separate.

Huff results contain demand, unserved demand, outside-option share, captured demand, capacity pressure and excess demand. The map's `score` is 100 times the outside-option share. It represents this allocation scenario, not survival probability or measured unmet spending. The frontend enables **Huff Market Gaps (Scenario)** only when a published Huff layer is available. It remains distinct from the concept-specific screening map and does not vary with a restaurant brief.

## Load a real survival model and precompute explanations

No trained model was included. The loader accepts trusted XGBoost `.json` or `.ubj` models using `binary:logistic` with positive class `survived`. The target is survival at a declared horizon; it does not support AFT/Cox artifacts or invent probabilities from the screening index.

Use `examples/model-manifest.template.json` to declare the model version, ordered feature names, artifact SHA-256, prediction horizon, H3 resolution, training cutoff and validation evidence. The current feature matrix represents `hex_location` predictions. A restaurant-level model requiring cuisine, establishment age or operating financials needs a separate feature/context adapter before use; the loader deliberately rejects a mismatched model contract.

Features must exist in the published Huff properties. Built-in numeric candidates are `residents`, `workers`, `transit_inflow`, `capacity`, `attractiveness`, `median_income_proxy` where available, and the derived Huff measures. Models requiring additional demographic age distributions or other covariates need a versioned feature enrichment step. Never substitute zero for absent covariates.

```bash
docker compose run --rm api python -m groundwork_backend.cli precompute \
  --snapshot huff_20261008 \
  --artifact /app/data/models/survival_v1.json \
  --manifest /app/data/models/survival_v1.manifest.json
```

The batch checks the artifact checksum, objective, class meaning, resolution and feature order, then computes native XGBoost TreeSHAP contributions. Contributions and the base value are in log-odds, and their sum must reconstruct the model's raw margin. Results commit atomically and are keyed by snapshot, cell and immutable model version. Request handlers perform lookups only, so model loading and SHAP computation cannot block dashboard requests. Before a new snapshot has predictions, the API returns 404 for that model/snapshot combination; clients can pin the previous snapshot during a refresh.

Schedule these offline commands in an existing scheduler or a one-shot container job after data updates. Celery was omitted because the current UI does not submit long-running user jobs: a separate scheduled batch process meets the roadmap's latency requirement with fewer moving parts. Add a durable queue if interactive jobs are introduced.

Before training, define permanent closure and censoring with verified business outcomes; do not assume a health-enforcement closure is business failure. Use time-stamped features preceding each outcome, temporal and spatial holdouts, calibration checks and Brier scores. These data and validation decisions remain outstanding because the ZIP contains neither historical labeled outcomes nor the pretrained artifact referenced by the roadmap.

## API additions

| Method and path | Result |
| --- | --- |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Schema and spatial-release readiness |
| `GET /api/v1/spatial/manifest` | Most recently activated release metadata |
| `GET /api/v1/spatial/resolve?...` | Matching concept-screening tile URLs |
| `GET /api/v1/spatial/huff` | Active Huff tile URLs and scenario metadata |
| `GET /api/v1/tiles/{snapshot}/{layer}/{resolution}/{z}/{x}/{y}.mvt` | PostGIS MVT with layer name `demand` |
| `POST /api/v1/locations/analyze` | Published Huff metrics for a coordinate |
| `GET /api/v1/models` | Model manifests |
| `POST /api/v1/predictions/survival` | Precomputed probability, horizon and SHAP explanation |

Point requests accept `latitude`, `longitude`, `resolution` (7, 8 or 9; default 8), and optional `snapshot`. Prediction requests also require `model_version`. Coordinates outside the NYC service extent, unknown fields and invalid identifiers are rejected. Missing spatial coverage or predictions return 404; unavailable infrastructure returns 503.

Tile URLs include immutable snapshot versions; cache keys include snapshot, layer, resolution and XYZ. The API returns ETags, conditional 304s and one-day public caching, including empty tiles. Redis misses or outages fall through to the spatially indexed PostGIS query. Cached tile hits avoid database access. JSON payloads in PostGIS are exposed as MVT scalar attributes through `ST_AsMVT`; clipping uses `ST_AsMVTGeom` in Web Mercator.

The existing Flask API paths remain available and are documented in `demo/FRONTEND_ARCHITECTURE.md`; they are not duplicated in FastAPI's OpenAPI schema. Account/workspace data remains in the original SQLite service with a persistent instance volume. A future multi-host deployment should migrate account storage to a shared service.

## Tests and validation

```bash
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check .
cd ..
node --check demo/static/js/dashboard.js
node --test backend/tests/frontend_hex.test.cjs
```

To run spatial integration tests, set `TEST_DATABASE_URL` to a **disposable** PostGIS database. Each test uses an isolated schema and drops it afterward. Integration tests cover source replay, projected count allocation, Huff publication, actual MVT decoding, independent active-layer pointers, immutable releases and persisted model predictions. `.github/workflows/backend.yml` provisions PostGIS and executes these tests in CI.

Local verification: 38 backend Python unit tests, 131 existing demo tests, 4 frontend map-contract tests, and 2 PostGIS integration tests passed; lint and JavaScript syntax checks passed. The PostGIS tests used a separate disposable database. The XGBoost tests use a temporary synthetic model exclusively as a test fixture; it is not shipped as a forecasting artifact. The mounted Flask dashboard, default concept resolution, a nonempty PostGIS vector tile, and Redis cache miss/hit behavior were smoke-tested with the local integrated release. No Huff layer or survival prediction was published.

The optional `data/samples/walkability-smoke.jsonl` fixture is local reference data, not a training input. Tests using it skip when the fixture is absent from a shared checkout.

## Design references

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) for database resource lifecycle.
- [PostGIS ST_AsMVT](https://postgis.net/docs/ST_AsMVT.html) and [ST_AsMVTGeom](https://postgis.net/docs/ST_AsMVTGeom.html) for tile encoding and clipping.
- [H3 indexing](https://h3geo.org/docs/api/indexing/) for coordinate-to-cell lookups.
- [XGBoost prediction API](https://xgboost.readthedocs.io/en/release_2.1.0/python/python_api.html#xgboost.Booster.predict) for native contribution predictions.
