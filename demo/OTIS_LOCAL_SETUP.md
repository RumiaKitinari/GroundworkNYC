# Integrated Otis runtime — local run, October 29, 2026

Target source: `origin/otis-week-10` at `11aaece42fd91cc5ea43c5869358c74573c76e26`.
The current checkout combines that behavior with the existing explorers, shared
`GROUNDWORK_DATA_DIR` resolution and workspace reliability fixes. This document
describes this machine's verified inputs; upstream Week 10 reports describe
Otis's separate data and research runs.

## Start the dashboard

Python **3.11** is the verified local interpreter. From the repository root:

```bash
python3.11 -m venv .venv  # only if no environment exists
.venv/bin/python -m pip install -r demo/requirements.txt -r codes/requirements-access.txt
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Open http://localhost:5001 and continue as guest. Edit Brief, submit a concept,
then select a property or switch the map inventory to areas. Location Analysis
contains resident/worker, transit and competition explorers. Customer Access
shows the network index and origin areas. Storefront Explorer remains available
under properties. Save locations to Compare; guest workspaces persist in that
browser. Registered accounts use the existing private SQLite workspace store.

`GROUNDWORK_DATA_DIR` may point directly to an integrated release directory.
Without it, the app uses `data/integrated/current` when present, otherwise
`data/integrated/restaurant_bar_location_data_ready`. The package needs its
master, geography and entity/feature tables. This local release has **2,327
tracts and 107 master columns**, SHA-256
`a74125b6424184ecb6ba59d656474f4996651c61cef6e8b28bcdb34b5ae70c4b`.
It is not Otis's newer 249-column completion release. Missing optional source
columns remain unknown; no values are fabricated to complete that schema.

Local Streets tiles use `data/osm/NewYork-mbtiles-shortbread/NewYork.mbtiles`.
Aerial and 3D styles require network access. The combined FastAPI/PostGIS/Redis
runtime remains supported by `run_local.py`; install
`backend/requirements-dashboard.txt`, configure the private database settings,
start its services, and run `run_local.py --check` first. This machine currently
has no `DATABASE_URL`/`POSTGRES_PASSWORD` configured and no running Docker daemon.
Standalone Flask is the verified runtime, not a claim of live PostGIS validation.

## Actual customer-access outputs

The following were generated locally using Otis's documented scripts, without
training a survival model:

1. `demo/generate_synthetic_properties.py --release data/integrated/restaurant_bar_location_data_ready`
   published 1,000 explicitly synthetic property scenarios (seed 440).
2. Downloaded `https://data.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf`
   (publisher Last-Modified October 24, 2026), then ran
   `demo/build_walk_network.py`. The graph has 1,973,951 nodes and 4,756,512
   directed edges.
3. `codes/engineer_customer_access.py` generated the property run, then
   `demo/prepare_dashboard_access.py` generated tract routes and the active pointer:

```bash
.venv/bin/python -m pip install -r demo/requirements-geospatial.txt
.venv/bin/python demo/build_walk_network.py
.venv/bin/python codes/engineer_customer_access.py \
  --master data/integrated/restaurant_bar_location_data_ready/master_tract_features.csv \
  --listings data/listings/synthetic_properties.csv \
  --network data/osm/nyc_walk_network.sqlite \
  --output data/output/feature_engineering/otis_local_20261029
.venv/bin/python demo/prepare_dashboard_access.py \
  --property-run data/output/feature_engineering/otis_local_20261029 \
  --output data/output/customer_access_dashboard/otis_local_20261029
```

These commands refuse to overwrite completed runs. Choose new output names to
reproduce. No download or computation happens during web startup. The scripts'
`manifest.json` and `validation.json` files record input hashes, configuration,
code hashes, coverage and checks. Source population, income and jobs come from
the installed release, not a newly downloaded demographic release.

The active pointer is
`data/output/customer_access_dashboard/dashboard_access.json`. Teammates need:

- Both run directories above, including `routes.npz`, `manifest.json`, CSVs and
  validation reports; the tract run is under `otis_local_20261029/tracts`.
- `data/listings/synthetic_properties.csv` and its adjacent `.manifest.json`.
- The same master release, `codes/customer_access_config.json`, and
  `data/osm/nyc_walk_network.sqlite` referenced by the manifests.

Pointers and manifests contain absolute source paths. On another machine,
regenerate/publish the bundles against that machine's paths rather than assuming
a copied pointer is portable. Changing the master requires new bundles; the
loader validates source hashes. Keep these generated files outside Git.

The index is a concept-specific percentile of walking-accessible, distance-decayed
resident/worker opportunities, adjusted by income and check-size assumptions.
It is **uncalibrated**, not predicted visits, business success or survival.
Synthetic property coordinates are approximate tract points, not real entrances
or available listings. This local master lacks reported occupied-rent fields;
scenario prices therefore use the generator's explicit modeled fallback, not
newly verified market rents. Historical evaluation claims do not validate this
locally generated access run.

## Survival and missing inputs

The default model pointer is now `data/output/otis_model/dashboard_model.json`.
The preserved older `data/output/atharv_model/dashboard_model.json` and
`presentation_20261029/` export are **not automatically loaded**. Do not set
`GROUNDWORK_ATHARV_SCORES` for an Otis demonstration. The API reports
`awaiting_artifact`, and survival estimates remain unavailable.

Otis's native adapter requires a compatible historical-AFT bundle containing
`survival_model.json`, `model_meta.json`, and `audit.json`, plus dated snapshot
manifests and their referenced source files. The documented default manifests
are:

- `data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json`
- `data/evaluation/snapshots/2023-12-v1/historical_core_snapshots.json`
- `data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json`

These and the compatible bundle are absent locally and were not supplied in Git
or the referenced shared Drive package. The default native bundle location is
`data/output/atharv_model/model/` (an upstream historical path name); use
`demo/connect_survival_model.py --model-dir ... --snapshots ...` to validate and
publish an actual bundle. Optional H3 cuisine scores are a separate input.
See [SURVIVAL_DASHBOARD.md](SURVIVAL_DASHBOARD.md). No old CSV, screening index or
archive-reobservation research model is substituted for this missing model.

Native adapter tests on this machine need the existing OpenMP runtime:
`DYLD_LIBRARY_PATH="$PWD/.venv/lib/python3.11/site-packages/sklearn/.dylibs"`.
For a fresh macOS native-inference installation, provide a compatible OpenMP
runtime; the web dashboard does not need XGBoost when no native model is active.

Optional published rent benchmarks and `data/listings/public_opportunities.csv`
are absent; corresponding source-dependent tests cannot pass with this package.
This does not imply a confirmed property offer. The full newer integrated release
and live database services remain separate prerequisites for their respective
upstream data/release checks.
