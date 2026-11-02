# GroundworkNYC

## Otis's November 2 Model Results

**Atharv: start with the [model update](MODEL_UPDATE_FOR_ATHARV_2026-11-02.md)
and [portable results handoff](reports/2026-11-02-model-results/README.md).**

The handoff includes a standalone interactive heatmap, briefing image, all
150,000 scenario/property scores, top-five selections, price-response tests,
competition-label sensitivity and the saved first-stage research control.
It covers 50 restaurant concepts at $18, $35 and $65 per guest over the pinned
1,000-property synthetic inventory. GitHub displays the image; to interact
with the heatmap, download this branch and open
`reports/2026-11-02-model-results/maps/heatmaps.html` in a browser.
No server, API key, local dataset installation or Python environment is
needed to view those saved results.

These are **offline scenario diagnostics, not an accuracy improvement or a
production model replacement**. Screening and experimental Huff selections
are exported separately. The first-stage archive-disappearance proxy remains
unverified restaurant survival. The report identifies source-coverage and
competition-label limitations rather than disguising them as measured demand.
See the [runner documentation](codes/CUISINE_BATCH.md) for the exact commands
and the private frozen inputs required to rerun the calculations.

## Integrated dashboard

This checkout integrates Otis's Week 10 update at `11aaece` with the existing
frontend, explorers and reliability fixes. Start with the verified
[local setup and artifact requirements](demo/OTIS_LOCAL_SETUP.md).

```bash
.venv/bin/python -m pip install -r demo/requirements.txt -r codes/requirements-access.txt
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Python 3.11 is verified locally. Open http://localhost:5001. The active local
results are concept screening and newly generated network customer-access
indices over the installed tract release and synthetic property scenarios.
**No validated Otis survival model is installed.** The older Atharv export is
preserved but not selected by default. Missing predictions are never replaced
with screening scores.

[Week 10 Changes](WEEK_10_README.md) and [Otis's integration notes](demo/MAIN_INTEGRATION_20261029.md)
describe the upstream work. Their data counts and research results refer to
Otis's machine; see the local setup document for the actual 107-column release,
new access bundles, missing artifacts, and verification limitations here.

The optional combined FastAPI/PostGIS/Redis runtime uses `run_local.py` after
installing `backend/requirements-dashboard.txt`, configuring private database
settings, and starting services. Run `run_local.py --check` first. See
[backend setup](backend/README.md). Private data, model files, account databases,
and generated route bundles remain outside Git.

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
