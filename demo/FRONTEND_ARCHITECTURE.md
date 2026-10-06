# Frontend architecture — Flask dashboard preview

**Scope:** The Flask app in `demo/`. A separate React prototype exists in the `frontend-demo` worktree.

**Branch scope:** This guide describes the `ui-concept-polish` dashboard preview. Its workspace stylesheet, 3D map, Aerial/3D separation, System dashboard control, and Edit Brief theme behavior are specific to that UI branch; they are not in main until the UI code is merged. The Flask APIs and integrated dataset paths apply to both branches.

## Why this structure

- **Flask serves the page and data.** This preview already scores locations in Python and reads local CSVs. Flask can serve the HTML, handle the brief request, and call that scoring code in one process; the frontend needs no build step or duplicate scoring logic.
- **The browser owns interaction.** `templates/index.html` defines the entry, brief, and dashboard; `static/js/dashboard.js` handles controls, requests, selection, and rendering. CSS lives in `static/css/dashboard.css` and `static/css/workspace.css`. This keeps UI behavior separate from the server's data and scoring work.
- **One dashboard response feeds the views.** The brief becomes query parameters for `GET /api/dashboard`. Its JSON supplies the same ranked locations to the map, ranking list, and details, so those panels do not need separate location searches.

## How a search runs

1. The user submits a brief or changes a dashboard filter. `dashboard.js` sends the concept, budget, deal type, and borough to `/api/dashboard`.
2. `app.py` validates those inputs, resolves the concept, reads the integrated package through a cached loader, and uses `scoring.py` to rank eligible NYC census tracts. The server returns up to 24 locations with scores, coordinates, evidence, and related panel data.
3. The browser renders that response and keeps the selected location ID in one place. Clicking a dot or ranking row updates the shared selection. A new response keeps that selection if the location remains in the results; otherwise it uses the server's top result. A failed request shows an error and offers Refresh.

**Why score on the server?** The Python model, input checks, and private dataset stay together. Map style changes only redraw the presentation; they never rerun or change the score.

## API boundaries

- **`GET /` and `POST /auth/<action>`:** Flask renders the page and handles guest/login/signup/logout sessions. The page receives a flag for whether local Streets tiles exist, so that option can be enabled only when available.
- **`GET /api/dashboard`:** The main page's data contract. It returns locations, the default selected ID, score components, property leads, source coverage, and finance/panel data. Filters go in the query string; ranking and evidence are calculated by the backend.
- **`GET /api/osm/tiles/{z}/{x}/{y}.pbf`:** Reads a tile from the optional local MBTiles database. This is map background data, not location scores.
- **`POST /api/concepts/resolve` and `POST /api/sites/analyze`:** Separate endpoints for concept interpretation and coordinate-level walking evidence. The main dashboard does not call them directly.

## Dataset: what is read and why

**Required path:** `data/integrated/restaurant_bar_location_data_ready/`, relative to the repository root. This private package is Git ignored. `app.py` expects these six CSVs at these exact paths:

| File inside the package | Why the app reads it |
| --- | --- |
| `master_tract_features.csv` | Primary tract coordinates and demographic, mobility, land-use, and competition signals used for screening. |
| `entities/current_restaurants.csv` | Cuisine and nearby-restaurant evidence for competition and concept fit. Use the original package file. |
| `entities/current_storefronts.csv` | Registry storefront records for property research leads, without assuming a verified asking price. |
| `entities/subway_stations_weekly_activity.csv` | Station activity and access evidence. |
| `source_catalog.csv` | Provenance of source data shown in coverage/context. |
| `feature_readiness.csv` | Which features are ready and their coverage limits. |

The loader caches parsed data and precomputed percentiles so every filter change need not reread all CSVs. This is a tract-level screening dataset, so a dot represents a candidate tract location, not a verified available storefront.

**Optional data:** `data/osm/NewYork-mbtiles-shortbread/NewYork.mbtiles` enables local Streets tiles; `data/osm/nyc_walk_network.sqlite` adds walking-catchment evidence; `data/listings/verified_properties.csv` adds verified listings. Each has its own role: without MBTiles Streets is disabled, without the graph walking evidence is unavailable, and without listings registry storefronts remain unpriced research leads.

## Why the map has separate modes

- **MapLibre GL JS** is bundled under `static/vendor/maplibre/`. One map instance holds NYC bounds and the current camera; switching modes changes its style, not the dashboard results or selected location.
- **Aerial** uses Esri satellite raster tiles to show real-world context. It has no building extrusions because 3D shapes over photos obscure streets and dots.
- **3D** fetches OpenFreeMap's Positron vector style and adds building extrusions from its building geometry. It excludes raster imagery so the buildings read against clean streets. Buildings with positive rendered height appear when zoomed in; if the style or tiles fail, the UI reports the problem and returns to Aerial.
- **Streets** uses the optional local MBTiles source through Flask. It is useful when that extract is installed and does not depend on the external Aerial or 3D tile providers.
- **Location dots** are MapLibre HTML markers made from the dashboard API's coordinates and active score. They sit above the map canvas, remain clickable over buildings, and naturally leave view when panned or zoomed. Their click handler updates the same selected ID used by rankings and details.

## Browser state and “AI”

- `sessionStorage` restores brief drafts and submitted values after refresh. `localStorage` stores an explicit Light/Dark dashboard choice; without one, the UI follows system appearance. Edit Brief inherits the dashboard's resolved theme when opened from it.
- Idea and description suggestions use local lists and text matching. Location scoring is a deterministic, uncalibrated screening model in `scoring.py`; this frontend makes no LLM request or visit forecast.
