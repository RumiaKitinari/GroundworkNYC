> Historical run: preserved for provenance, but not selected by the integrated
> Otis runtime. Reproduction commands below refer to the original run code at
> `ad5d229`, not the updated temporal training pipeline. See
> [current setup](OTIS_LOCAL_SETUP.md).

# Atharv model demo: real tract predictions

Source handoff: `origin/ADM6112-complete-v1`, commit
`40e0c0dfab1aedeff631fe38d244eaeb9283e20f`, `Readme/README.md`.
The branch was re-fetched on October 29 and remains at that commit.

## Run the existing demo

From the repository root:

```bash
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Open http://localhost:5001, continue as guest, submit a restaurant brief, select
an area on the map, then open Market Profile (View Location Analysis).
“Estimated Three-Year Survival” shows the selected tract's actual model export,
its version and its archive-proxy qualification. `/api/models/survival` reports
`available`, `source_type: atharv_tract_export` and 2,327 tracts. Predictions join
by the exact 11-digit GEOID; absent tract predictions remain unavailable.
Existing screening rankings and cuisine/explorer behavior are preserved.

## What was actually run

`tract_survival_scores.csv` is an output of `codes/train_survival.py`, not a
file supplied in Git. `codes/build_lifespans.py` generates its training labels
from the documented real cuisine-atlas archive. No review labels or alternative
model were substituted.

This is a locally generated run from October 29, 2026, not a trained artifact
supplied by Atharv. The local run trained on 18,860 restaurants, using the author's 5-fold NTA
GroupKFold, early stopping and AFT parameters. Final fit: 139 rounds; reported
spatial CV concordance: 0.556. The source cohort has 67,790 records and 19,051
eligible records before coordinate filtering. Latest archive snapshot:
2026-10-04. Reference opening year: 2023. Horizon: 3 years.

Results are archive-based research estimates. Disappearance is a closure proxy,
not verified permanent closure; contemporary context, inferred chain identity,
nearest-centroid assignment and the reference opening year limit interpretation.
Concordance is not classification accuracy. No calibrated success forecast is
claimed. This run uses the existing author's workflow, not Otis's incompatible
`historical-aft-v1` artifact contract; that optional path remains available.

## Local files and activation

All outputs stay under ignored `data/output/atharv_model/`:

- `source/restaurants_raw.parquet`, `source/provenance.json`: public archive,
  pinned to `20db98e6d2a1b2699b7a42c2e90df2edaed154e5`.
- `source/storefront_statistics.csv`: actual 2019–2024 published counts from
  the team's Shared Drive; preparation uses only the latest 2024 tract rows.
- `restaurant_lifespans.csv`: produced by the unchanged lifespan script.
- `presentation_20261029/master_tract_features.csv` and `.provenance.json`:
  separate prepared input; the active dashboard master is untouched.
- `presentation_20261029/model/`: native `survival_model.json`,
  `model_meta.json`, `cv_report.txt`, `feature_importance.csv`, and
  `tract_survival_scores.csv` (2,327 unique tracts).
- `presentation_20261029/run_manifest.json`: input/output and code hashes.
- `dashboard_model.json`: private activation pointer, containing
  `{"tract_scores":"data/output/atharv_model/presentation_20261029/model/tract_survival_scores.csv"}`.

A fresh clone needs the generated export restored or regenerated. Set
`GROUNDWORK_ATHARV_SCORES` to select another genuine export, or use `tract_scores`
in the private pointer. `GROUNDWORK_SURVIVAL_CONFIG` selects another pointer.
CSV changes invalidate the cache; the loader validates unique GEOIDs, finite
0–1 probabilities/borough ranks and the author's column names. No pandas or
XGBoost is needed merely to serve the saved CSV.

## Reproduce the documented preparation/training/export

Install `demo/requirements.txt` plus `demo/requirements-atharv.txt` into `.venv`.
Keep the private integrated package, including its tract GeoJSON. Download the
real inputs into ignored local storage:

```bash
mkdir -p data/output/atharv_model/source
curl -L --fail 'https://raw.githubusercontent.com/CharlesFainLehman/nyc-cuisine-atlas/20db98e6d2a1b2699b7a42c2e90df2edaed154e5/data/restaurants_raw.parquet' \
  -o data/output/atharv_model/source/restaurants_raw.parquet
curl -L --fail 'https://drive.usercontent.google.com/download?id=1p43jW2PtXAX1wEEED-g3GQAfJhfU_lAj&export=download' \
  -o data/output/atharv_model/source/storefront_statistics.csv
CAPSTONE_ROOT="$PWD/data/output/atharv_model" .venv/bin/python codes/build_lifespans.py \
  data/output/atharv_model/source/restaurants_raw.parquet \
  data/output/atharv_model/restaurant_lifespans.csv
.venv/bin/python demo/prepare_atharv_master.py \
  --storefront-statistics data/output/atharv_model/source/storefront_statistics.csv \
  --output data/output/atharv_model/presentation_20261029/master_tract_features.csv
CAPSTONE_ROOT="$PWD/data/output/atharv_model" \
DYLD_LIBRARY_PATH="$PWD/.venv/lib/python3.11/site-packages/sklearn/.dylibs" \
.venv/bin/python codes/train_survival.py \
  --master data/output/atharv_model/presentation_20261029/master_tract_features.csv \
  --lifespans data/output/atharv_model/restaurant_lifespans.csv \
  --out-dir data/output/atharv_model/presentation_20261029/model
```

The DYLD setting locates the OpenMP library already bundled with this macOS
scikit-learn environment. Other platforms may supply OpenMP normally.
The preparation command follows `integrated_directory()`/`GROUNDWORK_DATA_DIR`;
use `--integrated-data` to specify a different full package explicitly.

Compatibility work is limited to dated-field aliases/densities, published
storefront counts, the team's existing boundary-neighbor/derived-feature rules
from Otis `dce1e03` (`atharv_master_spec.py`), and fixing `fillna(None)` when an
optional neighbor-income column is absent. Absent or suppressed counts remain missing
(904 tracts); no vacancy-filing counts are relabeled as registered storefronts.
Unsupported neighbor-income estimates remain missing. Model parameters, label
construction, feature selection and CV methodology remain the author's.

To activate after regeneration, write the private pointer shown above, or
export `GROUNDWORK_ATHARV_SCORES` before starting Flask. Heatmaps and synthetic
property generation are not prerequisites for this documented tract export.

## Exact working-state handoff

To reproduce the currently displayed values without retraining, teammates need
this code, the existing private integrated dashboard package, and these files:

1. `data/output/atharv_model/presentation_20261029/model/tract_survival_scores.csv`
   (SHA-256 `c88abc3f61560d2f62972a3fcbf002a677277ecd434bf97fc3789aaaaab84357`).
2. `data/output/atharv_model/dashboard_model.json` containing the pointer above,
   or the equivalent `GROUNDWORK_ATHARV_SCORES` setting.

For the complete model handoff also include the other files in that `model/`
folder, `run_manifest.json`, the prepared master and its provenance JSON, the
lifespan CSV and the pinned source inputs. The native model is not loaded by
the CSV display path; keep it and its metadata for audit and future inference.
All these generated/private files remain outside Git.

This run's original master was
`data/integrated/restaurant_bar_location_data_ready/master_tract_features.csv`
(SHA-256 `a74125b6424184ecb6ba59d656474f4996651c61cef6e8b28bcdb34b5ae70c4b`).
It supplied May 2026 taxi and August 2026 Citi Bike data. Adjacency used that
package's `geography/nyc_2020_census_tracts.geojson` (SHA-256
`6ddc8997bc19fad3fd3b8bc8a4e9823530760b7c609bfaad36f9d3ea809df472`).
The 2024 storefront statistics and exact input/output hashes are recorded in
the prepared master's provenance and run manifest.

Completed verification: 19 focused connection/explorer tests passed; the browser
showed tract `36061007400` at **73.8%**, exactly matching its exported probability,
with zero JavaScript errors. Model version: `atharv-tract-c88abc3f6156`.
