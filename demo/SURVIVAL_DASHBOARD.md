# Survival connections

The current demo uses a genuine Atharv tract export generated from his documented
workflow. See [ATHARV_DEMO.md](ATHARV_DEMO.md) for artifacts, demo steps and
reproduction. `tract_scores` in the private config (or `GROUNDWORK_ATHARV_SCORES`)
selects this contract. It does not require a historical-aft-v1 audit file.

## Separate optional historical AFT inference

The dashboard reuses the inference/validation path from Otis Week 10 `dce1e03`.
Dated feature helpers are extracted into `survival_features.py` so web requests
do not import the research training pipeline. No training occurs at startup or
on requests. `/api/models/survival` reports status; `/api/dashboard` adds
`survival_model` and per-location `survival`. Market Profile displays the
three-year estimate, feature coverage and artifact version when available.
Screening scores, ordering and explorers retain their existing meaning.

## Missing bundle and exact contract

No compatible historical-aft-v1 artifact bundle is installed. The separate
Atharv archive-based export is active; it must not be relabeled as this dated model.
Default required files are:

- `data/output/atharv_model/model/survival_model.json`: native XGBoost
  `survival:aft`, normal distribution, feature order below.
- `data/output/atharv_model/model/model_meta.json`: schema `historical-aft-v1`,
  ordered `features`, ISO `trained_as_of`, `n_training_rows`, `aft_scale`,
  `horizon_years: 3.0`; optional `limitations`.
- `data/output/atharv_model/model/audit.json`: status `research_model_trained`,
  `training_performed: true`, at least one evaluated fold, matching `features`,
  `as_of`, `eligible_rows`, and `artifact_sha256.survival_model.json`.
- Manifests under `data/evaluation/snapshots/`:
  `2023-04-v0/historical_core_snapshots.json`,
  `2023-12-v1/historical_core_snapshots.json`, and
  `2024-12-v2/partial_historical_snapshots.json` (or explicitly configured paths).
- Every CSV referenced by those manifests, relative to the configured data root.

Feature order: `population_density_per_sq_mile`, `median_household_income`,
`job_density_per_sq_mile`, `national_walkability_index`. The transform is log1p;
missing values remain missing. Inputs join by explicit 11-digit tract GEOID.

Each manifest has a `snapshots` list. Entries require `feature`, `path`,
`historical_reconstruction_verified: true`, `source_url`, `observed_through`,
`available_on`, and file `sha256`; optional `column` defaults to `feature`.
CSVs require `geoid` and the value column, with unique IDs and nonnegative finite
values or blank cells. Observation/publication dates and checksums are checked.

## Connecting an existing compatible bundle

Keep the base Flask install unchanged. Actual inference additionally needs
numpy, pandas and XGBoost compatible with the supplied native artifact.
This checkout has numpy 2.0.2, pandas 2.2.3 and XGBoost 2.1.4. Artifact/runtime
compatibility has therefore not been established. Otis's research dependency
pins target Python 3.14 and must not be copied over this Python 3.11 baseline.

After obtaining the bundle and matching runtime dependencies, validate and
write the private pointer (repeat --snapshots for each actual manifest):

```bash
.venv/bin/python demo/connect_survival_model.py \
  --model-dir /absolute/path/to/audited-run \
  --snapshots /absolute/path/to/historical-manifest.json \
  --data-dir /absolute/path/to/private-data
```

The pointer is `data/output/atharv_model/dashboard_model.json` with `model_dir`,
`snapshots` (list), and `data_dir`. Relative paths resolve from the repository.
`GROUNDWORK_SURVIVAL_CONFIG` can select a different pointer at Flask startup.
Changed models/snapshots invalidate the adapter cache without a restart.
`GROUNDWORK_DATA_DIR` continues to select dashboard data independently.

Missing/invalid bundles produce unavailable estimates with null probability.
Experimental three-year estimates are not validated business-success forecasts.
Archive research models, CAMIS-level evaluation predictions and cuisine gap
scores are not substituted for survival estimates. `hex_cuisine_scores.csv` is
not required for this display-only connection; ranking blends remain deferred.
