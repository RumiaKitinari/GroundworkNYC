# GroundworkNYC

## Week 10: Otis Branch

**Atharv: start with [Week 10 Changes and Briefing Notes](WEEK_10_README.md).**
It explains the new model experiments, feature engineering, data checks,
infrastructure and every dashboard section, with implementation links and
explicit remaining limitations. This branch also includes earlier local-only
work; the document distinguishes that work from the October 27-28 results.

Branch: `otis-week-10`. This is a review/handoff branch; it does not replace
`main`. Private datasets, native models, individual predictions, secrets and
account databases are not included.

The Flask dashboard runs through Joseph's FastAPI/PostGIS backend using
`.venv/bin/python run_local.py` at `http://127.0.0.1:5001`.
It preserves the Flask routes, uses PostGIS for published spatial layers and Redis
for tile caching, and retains the existing SQLite account/workspace store.
Private datasets and synthetic property scenarios remain outside Git.

Install the combined local runtime with
`.venv/bin/python -m pip install -r backend/requirements-dashboard.txt` and keep
the private `.env` configuration. Run `.venv/bin/python run_local.py --check`
to verify services before startup. See [`backend/`](backend/README.md) for
infrastructure setup. Survival predictions still require a validated artifact.

## Frontend Lineage And Current Status

This branch preserves Jas's dashboard design, login/guest entry, restaurant
brief, top navigation, themes and separate 3D map concept. It integrates the
newer local property, menu, economics, account persistence and backend work
into that design instead of maintaining two competing frontends.

The UI currently uses Flask templates, vanilla JavaScript, MapLibre GL and
locally bundled Chart.js. It is not a React migration. Streets uses local OSM
vector tiles, Aerial uses online imagery, and 3D uses a separate OpenFreeMap
style with interactive buildings/POIs. Recommendation markers remain visible
in every mode; existing-restaurant overlays remain optional and 3D-only.
Map interactions are local-app features, not a claim that imagery and 3D tiles
are fully offline.

See [Frontend Architecture](demo/FRONTEND_ARCHITECTURE.md),
[Dashboard Integration](demo/DASHBOARD_INTEGRATION_20261028.md), and
[Connected Account Workspace](demo/CONNECTED_WORKSPACE.md).

## Data Folder

https://drive.google.com/drive/folders/12AUfzjVhSleP6oE60xbNeRY4rN6MpQhP

## OpenStreetMap PBF to CSV

The repository includes `scripts/osm_pbf_to_csv.py`, a streaming converter for
OpenStreetMap PBF extracts. It exports tagged, map-ready features (POIs, roads,
buildings, parks, land use, natural features, transit, routes, and boundaries)
while skipping untagged support nodes. Ways include GeoJSON geometry and a
representative map coordinate; relation rows retain their tags and member count
but do not attempt to assemble multipolygon geometry.

The converter uses a temporary disk-backed location index, so it does not load
the whole PBF into Python memory. Raw PBFs and `data/output/` are intentionally
gitignored. The small example in `data/samples/` shows the output format.

From the repository root on macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/osm_pbf_to_csv.py \
  ~/Downloads/new-york-260920.osm.pbf \
  data/output/osm/new-york-260920-osm-features.csv \
  --sample-output data/samples/osm_features_sample.csv \
  --overwrite
```

Run `python scripts/osm_pbf_to_csv.py --help` for all options. The
`geometry_geojson` cell is valid GeoJSON and `tags_json` preserves the complete
OSM tag dictionary for later MongoDB imports.
