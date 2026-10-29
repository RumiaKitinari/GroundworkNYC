# Experimental survival model in the local dashboard

The Flask dashboard now includes optional native XGBoost AFT inference through
`survival_inference.py`. `/api/models/survival` reports whether a compatible run
is connected. `/api/dashboard` includes a `survival_model` status and per-location
`survival` objects; the Market Profile displays the three-year estimate and the
interface identifies the active ranking method.

See [current local setup](OTIS_LOCAL_SETUP.md) for preserved legacy artifacts
and the active customer-access run. Legacy CSVs require explicit opt-in and are
not selected by the default Otis pointer.

## Current artifact availability

The checked remote branch `ADM6112-complete-v1` at
`40e0c0dfab1aedeff631fe38d244eaeb9283e20f` contains the experimental source code,
not trained `survival_model.json` / `model_meta.json` artifacts. No corrected
empirical survival model is currently present locally. Archive-reobservation
`.joblib` models are a different target and are never loaded by this integration.
The live interface therefore shows that the survival artifact is pending and
continues to identify its current scores as screening.

## Connect an audited model

Use a new run produced by `codes/train_survival.py` with verified, dated evidence.
The run must include `survival_model.json`, `model_meta.json`, and `audit.json`.
The loader checks the temporal schema, feature order, successful chronological
and spatial evaluation, matching model/audit metadata, model checksum, native
AFT objective, distribution, scale and three-year horizon. It rejects legacy
current-context models and never trains as part of a web request.

```bash
.venv/bin/python -m pip install -r demo/requirements-survival.txt

# Replace the run path with an actual successful, audited temporal training run.
.venv/bin/python demo/connect_survival_model.py \
  --model-dir data/output/atharv_model/ACTUAL_TEMPORAL_RUN \
  --snapshots data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json \
  --snapshots data/evaluation/snapshots/2023-12-v1/historical_core_snapshots.json \
  --snapshots data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json \
  --cuisine-scores data/output/atharv_model/hex_cuisine_scores.csv

PYTHONPATH=demo .venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5001 --no-reload
```

The connector validates the run before atomically writing the local
`data/output/otis_model/dashboard_model.json` pointer. Changed artifacts and
snapshots invalidate the inference cache; model activation needs no server
restart. Missing optional cuisine scores can be omitted from the command.

## Scoring contract

- Prediction inputs are selected from checked historical manifests using their
  observation and publication dates, shared with training; no current-master
  substitution occurs. The prediction date is today and cannot predate model fit.
- Missing inputs remain NaN; no prediction is returned where all historical
  features are unavailable. The response records feature coverage/provenance.
- If a matching resolution-9 cuisine-gap CSV exists and all candidate tracts
  have survival predictions, locations rank by `100 * (0.6 * survival percentile
  + 0.4 * cuisine gap)`. Percentiles are over eligible tract screening points
  in the selected borough filter. This differs from property-level filtering
  in `codes/recommend.py`; the API explicitly reports that scope.
- A ranking score is not a survival probability. Screening/context components
  remain separately labeled. The individual probability is shown in Market
  Profile with training date and feature coverage.
- With adequate native-model coverage but unsupported/missing cuisine scores,
  Otis uses 60% survival percentile plus 40% concept-specific general fit.
  Incomplete prediction/feature coverage retains screening rankings for the
  whole batch. Available estimates remain separately labeled.
- Existing property filters consume the selected area ranks. Property-level
  survival inference, property-specific hard filtering before percentile ranks,
  and model-derived H3 heatmap tiles are not introduced by this change.
- A missing/invalid survival artifact never becomes a zero survival probability,
  and screening scores are never presented as survival predictions.

Verification uses temporary synthetic evidence and real XGBoost fits through the
Flask HTTP test client. Synthetic test models are not activated in the running
dashboard. Actual historical validity still depends on the provenance and
verified outcome requirements documented in `codes/TEMPORAL_SURVIVAL.md`.
