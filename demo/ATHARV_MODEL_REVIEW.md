# Atharv Model: Local Integration and Reporting Notes

Reviewed October 21, 2026. Imported main commit `2935dba`, including Atharv's
`40e0c0d` upload from `ADM6112-complete-v1`. Existing local changes were retained.

## What Was Imported

The `codes/` directory contains the complete training and recommendation
implementation; `Readme/README.md` describes the author's intended workflow.
The push does **not** include `survival_model.json`, `model_meta.json`,
cross-validation output, or trained-model feature importance. README metrics
are author-reported, not independently reproduced training results.

This is a separate research pipeline. Merging it does not automatically replace
the Flask dashboard's scoring engine or its optional model loader. No frontend
or dashboard endpoint was changed in this integration.

## Actual Pipeline

1. `label_cuisines.py` maps DOHMH cuisine labels and restaurant-name patterns
   into 50 categories. Outputs include rule provenance. Broad labels can receive
   default guesses; those are not independently verified cuisine labels.
2. `cuisine_matrix.py` creates a symmetric, manually specified 50-by-50
   substitution matrix with self-competition of 1. These weights are assumptions,
   not learned consumer preferences.
3. `make_heatmaps.py` counts active classified establishments in H3 resolution-9
   cells and produces smoothed supply, weighted competition, and gap scores.
4. `build_lifespans.py` constructs restaurant-level time intervals from the
   cuisine-atlas consolidated DOHMH archive.
5. `features.py` prepares tract context and restaurant predictors.
   `train_survival.py` trains XGBoost using `survival:aft`.
6. `recommend.py` filters synthetic properties and combines survival ranking,
   cuisine gap, and optional property preferences.

## Stage One: Interval-Censored AFT Model

The observation unit is a restaurant/CAMIS, not a tract or hexagon. Cuisine and
rent are excluded from the predictor list. There are 47 tract predictors and
three restaurant predictors: inferred chain status, estimated competitors within
400 meters at opening, and opening year.

The opening proxy is the first recorded pre-permit inspection. A restaurant
absent from the newest archived snapshot is assumed closed. Its event interval
runs from the last snapshot containing it to the next inferred snapshot date.
Restaurants present at the newest snapshot are right-censored. The midpoint
closure estimate is also used in reconstructing competitor counts.

The cohort requires a pre-permit date after November 6, 2020 and nonnegative
estimated duration, then filters missing coordinates and latitude outside
40.4-41.0. The model uses a normal AFT error distribution with log-time scale 1,
learning rate 0.03, maximum depth 5, minimum child weight 25, row subsampling
0.8, column subsampling 0.7, L2 regularization 2, and seed 440.

Five-fold GroupKFold uses NTA codes. Each fold allows up to 2,000 rounds and
early stopping after 100 rounds without improvement. The final model fits all
rows using the median best round count across folds. Three-year survival is
calculated from the predicted AFT median time through the normal CDF.

The reported C-index is a sampled concordance estimate over pairs whose event
intervals can be ordered, not classification accuracy. The README reports
approximately 0.563 overall; that number has not been rerun locally.

## Stage Two: Supply-Based Cuisine Gap, Not Huff

For each cuisine, counts are weighted by the manually defined substitution
matrix. Local supply combines the cell itself with its six adjacent cells,
giving adjacent cells weight 0.25 and dividing by 2.5. Surrounding activity is
the mean weighted count over the 54 cells in rings 2-4.

The surrounding value is normalized by the cuisine's positive-value 95th
percentile and capped at 1. The gap is this normalized value multiplied by
`max(0, 1 - local / surrounding)`. Zero surrounding activity produces zero gap.
Existing supply is therefore a demand proxy, not a direct measure of customers,
spending, demographic preference, or unmet demand.

This code does not implement Huff choice probabilities or demographic origin-
destination demand allocation. The repository's other Huff implementation is
separate; it is not invoked by Atharv's `run_all.py` or `recommend.py`.

## Property Recommendations

Hard filters include transaction, asking rent or purchase price, size, borough,
ground floor, and former food use. Rent does not change survival predictions.
Default ranking is `0.6 * survival percentile + 0.4 * cuisine gap`.
Optional bonuses are 0.05 for former food use and 0.03 each for potential outdoor
space and a corner position. The total is not a calibrated success probability
and can exceed 1 with bonuses. Percentiles depend on the filtered candidate set.

Properties use their assigned tract features, current reconstructed competition,
the concept's chain flag, and a reference opening year of 2023 for this archive.
The reference year is a comparison convention, not a forecast for a 2026 opening.
The properties remain synthetic scenarios, not verified available listings.

## Local Verification

The imported code was connected to existing local inputs without copying or
modifying source datasets:

- Master: `data/integrated/current/master_tract_features.csv`, 2,327 rows and
  249 columns. All 47 tract predictors build; none is infinite.
- Current establishments: `data/integrated/current/entities/current_restaurants.csv`.
- Properties: `data/listings/synthetic_properties.csv`.
- Archive: existing pinned cuisine-atlas commit
  `20db98e6d2a1b2699b7a42c2e90df2edaed154e5`, 67,790 records.
- Generated lifespan table: `data/output/atharv_model/restaurant_lifespans.csv`.
- Newest archived snapshot: October 4, 2026, not today's live DOHMH export.
- Lifespan eligibility: 19,051 before training-coordinate filtering.
- Training rows: 18,860, comprising 4,534 assumed closure intervals and 14,326
  right-censored observations. All interval bounds are ordered correctly.
- Borough counts: Bronx 1,552; Brooklyn 5,146; Manhattan 7,108; Queens 4,363;
  Staten Island 691. All training rows have an NTA; there are 218 NTA groups.
- The income weighting function returns weight 1 for every training row.
- Three path-resolution tests pass. An eight-row synthetic runtime check passes
  for the XGBoost AFT objective and survival probability bounds; the cuisine
  matrix symmetry and partial cuisine matching checks also pass.

The full five-fold real-data fit, heatmap build, property ranking, and dashboard
model integration have **not** been executed or validated in this review.

## Important Reporting Qualifications

- Archive disappearance is a **closure proxy**, not verified permanent closure.
  Interval censoring accommodates uncertainty in timing, not incorrect status.
- A pre-permit inspection does not independently establish the exact opening
  date. The code's `open_known` name should not be described as proof of opening.
- Current or recent tract features are attached to older cohorts. This includes
  current OSM supply and upcoming events. Excluding current DOHMH inspection
  grades does not make the full pipeline historically leakage-free.
- Chain status uses name frequencies across the full archive. It is neither
  independently verified ownership nor restricted to information at opening.
- Restaurants are assigned to the nearest tract centroid, not point-in-polygon
  boundaries. Tract-edge assignments can be wrong.
- Income groups are made by ranking restaurant rows into equal-sized quintiles.
  Inverse group-size weighting is consequently uniform here; it does not deliver
  the README's claimed equal influence across tract-income groups or boroughs.
- The fold used for evaluation also controls early stopping. There is no
  untouched final temporal test or nested validation in this implementation.
- Cuisine defaults and name rules can misclassify establishments or collapse
  distinct cuisines. The matrix and 60/40 ranking weights need sensitivity tests.
- The recommendation CSV does not carry every synthetic-inventory provenance
  column through to output. Retain an explicit synthetic label in any API/UI.
- The requirements installed locally are not evidence of the environment used
  for Atharv's reported run. Obtain his saved artifacts, package versions, input
  identifiers, and CV outputs to reproduce that specific run.

## Safe Summary for the Report

The current prototype implements a two-stage recommendation pipeline. The first
stage uses an interval-censored XGBoost accelerated failure time model to compare
restaurant persistence across locations without cuisine as a predictor. The
second stage estimates cuisine-specific gaps from the spatial distribution of
existing establishments and a manually specified cuisine-substitution matrix.
Filtered synthetic properties are ranked using the two outputs and selected
property preferences. Historical opening and closure dates remain proxies
derived from inspection and archive records, and recent neighborhood features
limit historical interpretation. The resulting scores support prototype
comparisons rather than verified forecasts of restaurant survival.

## Local Commands

From the repository root:

```sh
.venv/bin/python -m unittest discover -s codes -p test_paths.py -v
.venv/bin/python codes/run_all.py --list
.venv/bin/python codes/run_all.py --only lifespans
```

Research training, when deliberately requested:

```sh
.venv/bin/python codes/run_all.py --only train
```

Default outputs stay under ignored `data/output/atharv_model`. `CAPSTONE_ROOT`
retains the original flat data/outputs layout for collaborators, and
`CAPSTONE_OUTPUTS` overrides the output directory. The local adapter refuses to
choose silently between multiple pinned archive files.
