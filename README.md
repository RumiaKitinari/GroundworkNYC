# GroundworkNYC

The Flask dashboard remains in `demo/`. The optional [FastAPI spatial backend](backend/README.md)
mounts that dashboard at `/` and adds PostGIS vector tiles with Redis caching.
It does not replace the existing routes or publish an unvalidated survival model.
Private integrated data, accounts, and model artifacts stay outside Git.
Run the backend locally using the instructions in `backend/README.md`.

## Run the dashboard

From the repository root, using Python 3.11 or 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Open http://localhost:5001. The root `requirements.txt` belongs to the older
Django/data-tool setup; use `demo/requirements.txt` for this dashboard.

The dashboard, resident/worker and transit profiles, competition explorer,
storefront research, 3D restaurant overlay, saved workspaces and menu tools
are combined in `demo/`. Read [the app README](demo/README.md) for setup and
[the architecture note](demo/FRONTEND_ARCHITECTURE.md) for the API boundaries.
`GWNYC_site/` is the separate Django/MongoDB starter. The team's `codes/`
model pipeline remains separate; its instructions are in `Readme/README.md`.

## Local data and optional services

The private integrated package is required for dashboard results. Selection
order is `GROUNDWORK_DATA_DIR`, `data/integrated/current/`, then
`data/integrated/restaurant_bar_location_data_ready/`. All explorer readers
follow that selection; keep the full `features/` and `entities/` directories.
The concept-demand map also requires the tract GeoJSON under `geography/`.

Local MBTiles enable Streets. Aerial and 3D use online providers. The walking
network and verified property sources are optional. This checkout has no
optional rent benchmark snapshot or public leasing CSV: those views show
unavailable data, and the two existing tests requiring those files cannot pass
until the sources are supplied. Storefront filings do not establish current
lease availability.

Flask runs without PostGIS or Redis. The optional FastAPI wrapper serves the
same dashboard on port 8000; follow [backend/README.md](backend/README.md).
Published spatial snapshots and a trained survival model are not supplied.
Keep private data, account databases, signing keys, virtual environments,
checkpoints and generated caches outside commits.

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
