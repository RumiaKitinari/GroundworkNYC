# October 27 Model Evaluation Handoff

## Completed Locally

Fetched every remote branch. Main remains `2935dba` and Atharv's upload remains
`40e0c0d`; no newer model artifact or evaluation push was available. Jashkaran's
UI branch remains October 8. The current dashboard design was not changed.

The full evaluation uses all 1,000 synthetic properties, all 2,327 tract origins
and the pinned integrated release's 31,384 restaurant rows (31,232 active).
Outputs are in `data/output/model_evaluation/20261027_v3/`. Sources and code are
checksummed. The original master and all previous artifacts remain untouched.

Added a network Huff scenario implementation alongside the existing H3 backend
tool, and reused Atharv's existing cuisine substitution and supply-gap logic.
The Huff scenario compares one hypothetical entrant at a time with existing
restaurants and an outside option. All choice shares sum to one within numerical
precision (maximum error approximately 2.22e-16). This checks the implementation,
not behavioral accuracy. The candidate's attractiveness and travel/price
settings remain assumptions rather than fitted consumer preferences.

## Findings

- Inverse walkability is not just EPA walkability renamed. Rank correlations
  with EPA are approximately -0.168 (cafe), -0.020 (office lunch), -0.157 (casual
  dinner), and -0.072 (premium dinner). These compare supported property
  scenarios; they do not prove predictive benefit.
- Access ablations test jobs, residents, affordability and distance decay, plus
  local-population and local-job baselines. Changing components can substantially
  change top-50 selections. No weight was chosen by maximizing these differences.
- Access coverage is 986, 986, 987 and 988 properties across the four profiles.
  The stricter competitor-routing Huff assessment currently supports 602, 575,
  623 and 578 respectively. The remaining scores are withheld, not filled with
  zeros or promoted as market gaps.
- The strict Huff stock uses 25,645 active direct/keyword-labeled restaurant
  records. Another 5,587 active records have uncertain labels, unmatched tracts,
  or both; 788 active records do not match the origin tract inventory.
  Direct/keyword labels themselves are rules, not independently verified truth.
- The original gap comparison retains its legacy cuisine defaults and NYC
  bounding-box filter: 28,218 active records qualify. Zero/missing coordinates
  are excluded rather than becoming restaurant clusters outside NYC.
- Halving/doubling outside attractiveness produces rank correlations of roughly
  0.972-0.995 and top-50 retention of 74%-96% on common supported candidates.
  Parameter sensitivity is material and must not be reported as accuracy.
- Access, supply gaps and Huff can rank properties differently. Huff remains
  an offline experiment; there is not enough evidence to replace the dashboard's
  current ranking or combine it with fabricated survival probabilities.

## Survival Evaluation Improvements

The guarded XGBoost trainer now exports a training-fold-only constant log-normal
AFT baseline, interval likelihood, interval-order concordance, conditional
NTA-bootstrap uncertainty, and leave-one-feature-out diagnostics. Three-year
tables explicitly count known survivors, closures and unresolved outcomes.
The resolved-subset Brier/calibration diagnostic is not IPCW or population
calibration. Saved held-out predictions include both model and baseline output.

`codes/model_evaluation_plan.json` pins January 1, 2024 as the temporal cutoff,
October 27, 2026 as analysis date, five spatial groups and 200 fixed rounds.
Passing it to the trainer rejects incompatible arguments and records its hash.
Current access/Huff/property features remain excluded from historical training.
Tests fit real XGBoost models on explicitly synthetic evidence and verify that
altered held-out outcomes do not alter fold models or training-only baselines.
Those tests are software validation, not empirical restaurant results.

## What Still Blocks Empirical Claims

The fresh audit is `data/output/atharv_model/temporal_audit_20261027_v2/audit.json`.
The legacy 67,790-row lifespan table lacks dated baseline provenance,
verification status, and required location identifiers. Snapshot disappearance
does not verify permanent closure; first pre-permit inspection does not prove
first trading day. The code still correctly refuses to turn these into verified
survival labels. The previously trained archive-reobservation proxy is not a
restaurant-survival model.

Atharv's reported fitted weights and validation outputs have not been supplied.
To audit that specific run, provide `survival_model.json`, `model_meta.json`,
fold/held-out predictions and assignments, the exact training inputs/manifest,
and environment/parameter information. Those artifacts can reproduce his proxy
experiment; they do not independently verify its outcome labels or historical
feature availability.

With a post-2024 holdout, complete three-year follow-up is impossible by October
2026. We can evaluate interval ordering and likelihood when sufficient verified
evidence exists, but full three-year calibration needs older verified cohorts
with historically available features, a separately declared shorter horizon,
or longer follow-up. Do not classify unresolved restaurants as surviving.

Immediate priorities: reconcile the 788 unmatched active records, improve routing
for affected competitor tracts, review uncertain cuisine labels, and obtain the
dated operating/closure evidence and saved model artifacts. Calibration of Huff
additionally requires permitted observed customer-origin/choice or comparable
visit evidence. No paid API or marketplace scrape was used for this work.

## Commands

```bash
.venv/bin/python -m unittest discover -s codes -p 'test_*.py'
.venv/bin/python -m unittest discover -s demo -p 'test_*.py'

.venv/bin/python codes/evaluate_model_features.py \
  --property-run data/output/feature_engineering/20261027_v3 \
  --tract-run data/output/customer_access_dashboard/20261027_v1/tracts \
  --output data/output/model_evaluation/NEW_RUN

# Audit only. Does not override missing outcome evidence or train a model.
.venv/bin/python codes/train_survival.py \
  --snapshots data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json \
  --snapshots data/evaluation/snapshots/2023-12-v1/historical_core_snapshots.json \
  --snapshots data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json \
  --evaluation-plan codes/model_evaluation_plan.json \
  --as-of 2026-10-27 --cutoff 2024-01-01 --audit-only \
  --out-dir data/output/atharv_model/NEW_AUDIT
```

Implementation: `codes/MODEL_FEATURE_EVALUATION.md`. Current working changes are
local and have not been pushed. Do not upload the private data/output directories.
