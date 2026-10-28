# Opening-date survival research: temporal contract

`train_survival.py` now fails closed on the old archive-derived lifespan summary.
This is an intentional compatibility boundary: `closed=True` based on archive
absence is not a verified permanent closure, and a retrospective record cannot
establish what was known at opening. Existing artifacts are never overwritten.
The Methods Report is not changed by this implementation.

## Reused components and retained functionality

`demo/prepare_historical_cohort.py::read_snapshots` verifies source URLs,
explicit historical-provenance review, observation/publication chronology,
file hashes and numeric values. Its shared `select_snapshot` selects the latest
usable publication at or before each prediction date. Its existing one-year
binary `build_cohort` is NOT reused as a three-year survival target: that would
lose censored observations and change the scientific question.

The experimental trainer still fits XGBoost `survival:aft` with a log-normal
error distribution, writes `survival_model.json`, `model_meta.json`, feature
importance and held-out predictions, and supports the existing property filters,
cuisine-gap calculation, 60/40 recommendation weighting and preference bonuses.
Models are research-only. Current dashboard scoring is unchanged.
The previous automatic current-master `tract_survival_scores.csv` is no longer
generated; prospective location scoring requires explicit dated snapshots through
`recommend.py` instead of mixing contemporary tracts with a fictitious opening year.

## Inputs

All dates are explicit ISO dates (`YYYY-MM-DD`); identifiers are read as strings.
Use a pinned, reviewed evidence export, not an edited copy of the archive with
verification flags filled automatically. One CAMIS must identify one consistent
business/location spell. Transfers, relocations, and reopened businesses need
adjudication before inclusion; conflicting closure/operation evidence stops a run.

### Baseline CSV (`--baselines`; `--lifespans` is an alias)

Required columns:

```
camis,open_date,baseline_available_on,baseline_source_reference,verification_status,geoid,nta_code,borough
```

`open_date` is the inferred opening and prediction origin. All baseline attributes,
including the location/geographic association and NTA, must be supported by the
referenced evidence available no later than that date. Only
`verification_status=independently_verified` is accepted. Later-known baselines
are excluded rather than backdated. `geoid` must be an explicit 11-digit tract ID;
there is no nearest-current-centroid fallback. Opening-date uncertainty is still
not explicitly modeled: review whether an inspection/pre-permit date is an
appropriate origin before using it. Do not reinterpret a pre-permit inspection
as verified first trade.

### Observation ledger (`--observations`)

Required columns:

```
camis,status,observed_on,available_on,source_reference,verification_status
```

Only independently verified `operating` and `permanent_closure` statuses count.
`observed_on` is the dated evidence of operation or closure, and `available_on`
is when that evidence could first have been used. Observation must precede or
coincide with availability. Preserve separate original observations when new
follow-up arrives; do not replace earlier ledger entries with a final summary.
Source references must identify reviewable evidence, not just a website homepage.
A hash protects bytes; it does not independently authenticate an assertion.

At each model fit date, only available evidence is eligible:

- Lower AFT bound = `(last verified operating day - inferred opening)/365.25`.
- With subsequent verified permanent closure, upper bound =
  `(first verified closure-observation day - inferred opening)/365.25`.
  This is an interval, not an invented midpoint or an exact closure date.
- Otherwise upper bound is infinity: censor at the last verified operating day,
  never the extraction date, last inspection record retained in an archive,
  or an arbitrary validation cutoff.
- Rows without positive verified follow-up are excluded; no epsilon duration
  or operating-at-opening assumption is invented. A closure needs a distinct
  supporting reference from the last operating observation.
- Operating evidence on/after a claimed permanent closure is a conflict.
- Three-year outcome is closed if the upper bound is at most 3; known beyond
  three years if the lower bound is at least 3; otherwise unknown. Early
  censoring and intervals straddling 3 are not assigned survival labels.

This requires an assumption that evidence refers to one business spell and that
observed operation is informative about time to permanent exit. Intermittent
operations and informative inspection/follow-up remain limitations.

### Historical feature manifests (`--snapshots`, repeatable)

Use the existing snapshot format, with a `snapshots` list of objects containing:
`feature`, `path` relative to `--data-dir`, `column`, `observed_through`,
`available_on`, `sha256`, `source_url`, and
`historical_reconstruction_verified: true`.

The fixed feature allowlist is:

- `population_density_per_sq_mile`
- `median_household_income`
- `job_density_per_sq_mile`
- `national_walkability_index`

The available local manifests can be combined explicitly (never glob-selected):

```
data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json
data/evaluation/snapshots/2023-12-v1/historical_core_snapshots.json
data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json
```

A publication must satisfy `observed_through <= available_on <= open_date`.
A 2023 observation published in 2024 cannot describe a 2023 opening-time decision.
No usable vintage means NaN, not zero or current data. Rows with all features
missing are excluded. Log1p is fixed independently of the data; XGBoost handles
remaining NaNs. No fitted imputer, scaler, neighborhood imputation, income
quintile weighting, or test-cohort preprocessing is used.

Current rent, mobility, upcoming events, property counts, neighbor features and
all other current-only predictors are excluded. `is_chain`, retrospective chain
names, opening-time competition, and opening year are excluded. Counting names
or reconstructing operating status from a later lifespan summary is not an
as-of registry. To restore chain/competition, first supply independently dated
name/location/status observations and a documented coverage policy. Missing
registry coverage must not become zero competition.

## Temporal and spatial validation

Choose `--cutoff` before looking at outcomes. Every test restaurant opens on/after
that cutoff. Training restaurants open strictly before it, and **their labels
are reconstructed only from evidence available strictly before the cutoff**.
Future closures are not clipped back to the cutoff; an earlier known operation
can support right censoring instead. This prevents outcome leakage even for a
restaurant that opened years before the split.

NTA assignments use `SHA256(nta_code) mod folds`, independent of labels. Each
future NTA group is held out from its fold's training set. This is a single
chronological cutoff with spatial holdouts, not five interchangeable random
folds. Fold membership and effective bounds/availability are saved.

Boosting rounds are fixed in advance (`--rounds`, default 200). No test labels
are passed to XGBoost during fitting or early stopping, and no test performance
selects the final number of rounds. Parameters must not be repeatedly tuned on
this holdout; introduce a separate earlier development period for tuning.

A fold needs at least two training observations, at least one finite closure
interval, and test observations. Empty/unsupported folds are reported as such.
No final model is published if no temporal/spatial fold is evaluable or if the
final data are all censored. These are minimal identification checks, not proof
of sufficient sample size or statistical precision.

The final research model fits eligible evidence available through `--as-of`.
It is NOT used for held-out predictions. Recommendation scoring rejects dates
before the model's `trained_as_of` and rejects legacy model metadata. It uses
exactly the same historical feature selector/transform; it does not insert a
fictitious older opening year or current master values. New prospective data
may use newer legitimately available vintages, with distribution shift remaining
an evaluation concern. The separate current cuisine-gap/listing ranking is not
a historical end-to-end recommendation backtest.

## Commands

From the repository root, with the project environment installed:

```bash
# In a dedicated compatible Python environment:
python -m pip install -r codes/requirements-temporal.txt

.venv/bin/python -m unittest discover -s codes -p 'test_*.py'
.venv/bin/python -m unittest discover -s demo -p 'test_prepare_historical_cohort.py'

# Audit the legacy input honestly; this does not train a model.
.venv/bin/python codes/train_survival.py \
  --snapshots data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json \
  --as-of 2026-10-22 --audit-only \
  --out-dir data/output/atharv_model/temporal_audit_NEW

# Use only after separately reviewing/creating the required evidence files.
# These two paths are required inputs, not files this change claims to supply.
.venv/bin/python codes/train_survival.py \
  --baselines data/evaluation/verified_opening_baselines.csv \
  --observations data/evaluation/verified_operating_closure_ledger.csv \
  --snapshots data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json \
  --snapshots data/evaluation/snapshots/2023-12-v1/historical_core_snapshots.json \
  --snapshots data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json \
  --as-of 2026-10-22 --cutoff 2024-01-01 \
  --out-dir data/output/atharv_model/temporal_run_NEW

.venv/bin/python codes/recommend.py --cuisine Indian \
  --model-dir data/output/atharv_model/temporal_run_NEW \
  --snapshots data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json \
  --prediction-date 2026-10-22
```

Use a new output directory for each run. `run_all.py` forwards the explicit
baseline, observation, snapshot, cutoff and as-of arguments to training and the
snapshot/model arguments to recommendation. The lifespan step remains an archive
review output, not an automatic source of verified labels.

## Evaluation Additions (October 27)

`model_evaluation_plan.json` pins the chronological cutoff, analysis date, five
spatial folds, 200 fixed rounds and historical feature list. Pass
`--evaluation-plan codes/model_evaluation_plan.json --cutoff 2024-01-01
--as-of 2026-10-27` to reject incompatible arguments and retain the plan hash.
No parameter or feature subset is selected using this final holdout.

Each evaluable fold now compares XGBoost with an intercept-only log-normal AFT
baseline fitted exclusively to its training rows. `evaluation.json` contains
interval negative log likelihood, interval-order concordance, conditional
test-NTA cluster-bootstrap intervals, and leave-one-historical-feature-out
diagnostics using the same folds and boosting settings. Cluster bootstrap
intervals describe held-out sampling uncertainty conditional on the fitted
models; they do not include training/model-selection uncertainty.

Three-year Brier and calibration tables are explicitly restricted to identifiable
outcomes, with survivor, closure and unresolved counts reported. These are not
IPCW or full-population calibration estimates. A post-January-2024 cohort cannot
have uniformly complete three-year follow-up by October 2026. Do not use its
observed-closure-only subset to claim calibrated three-year survival. Earlier
verified cohorts, shorter-horizon evaluation or longer follow-up require a
separately declared evaluation change before retuning.

## Artifacts and verification limits

A full run saves input/code SHA256 hashes, Python/dependency versions, parameters,
preprocessing policy, exclusions, per-value feature provenance, fold assignments
and effective label bounds, held-out predictions, individual fold models, the
final model and artifact hashes. The archived baseline/observation/manifest files
must remain available at their recorded paths (or be restored by hash).

Tests use explicitly synthetic evidence, not invented research observations.
They exercise real XGBoost fits, identical-run artifact reproducibility,
future-publication exclusion, delayed outcomes, spatial/temporal separation,
held-out-label perturbation invariance, missing/zero distinctions, censorship,
chronology conflicts, and rejection of legacy models and source summaries.

Passing those tests establishes software guards, not authentic historical
availability or verified business outcomes. The local legacy archive cannot
currently pass the new baseline/outcome evidence contract. No replacement
empirical restaurant-survival model should be claimed until those inputs are
verified and the actual run's exclusions and holdout coverage are reviewed.
