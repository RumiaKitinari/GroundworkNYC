# Saved Model Rerun - October 27

## Current Results Package

Completed run: `data/output/research_runs/20261027_archive_aft_v2/`.
Validated replay: `data/output/research_validation/20261027_v3/`.
Canonical research pointer: `data/output/current_archive_research_run.json`.

This is an explicit archive-disappearance AFT research run, not a verified
permanent-closure survival model. The opening/closure evidence guard in the
separate historical trainer and dashboard model loader remains unchanged.
No file from Atharv's machine is needed to use these newly generated outputs.
They reproduce his recipe with our pinned inputs and environment, not his
unavailable exact local run.

## What Was Trained

- Original reference trainer from Atharv's `40e0c0d` commit, with the original
  early stopping and 50-feature recipe. Original source and a path-only local
  adapter are saved in the source snapshot.
- A fixed-200-round, 50-feature comparator and a corrected 41-feature model
  evaluated on exactly the same five NTA folds and restaurant IDs.
- Four corrected-model ablations removing residents, employment,
  built-environment or mobility groups. These diagnostics do not select a winner.
- A constant log-normal AFT comparator fitted separately on each training fold.

The corrected model uses the 38 current-context feature contract plus the
original three restaurant variables. This fixes allocation, vacancy, percentage
units, missingness and event-context semantics. It does not make those current
features historically available at older restaurant openings. Full-archive
chain counts and reconstructed competition remain retrospective assumptions.
Cuisine and rent are not survival predictors.

All 67,790 archive records are frozen as inputs; the reference recipe yields
18,860 training restaurants across 218 NTA groups, with 4,534 assumed exit
intervals and 14,326 right-censored records. No synthetic property is used as a
training observation. The full current master contains 2,327 tracts.

## Results and Interpretation

| Fixed-Round Model | Interval Concordance | Interval NLL |
| --- | ---: | ---: |
| Training-fold constant AFT | 0.4867 | 0.8887 |
| Legacy 50-feature comparator | 0.5617 | 0.8853 |
| Corrected 41-feature model | 0.5648 | 0.8846 |

Lower NLL is better. Concordance measures ordering of comparable proxy event
intervals, not percent accuracy or proven survival. The constant predictor
differs across training folds, so its pooled score need not be exactly 0.5.
The corrected-versus-legacy difference is small; its paired NTA-bootstrap
interval includes zero. Do not claim a demonstrated feature improvement.
The exact paired interval and conditional uncertainty scope are in the saved
validation JSON.

The original early-stopped reference reports approximately 0.566. Its test folds
also selected stopping rounds, so this is reported separately rather than
treated as an untouched final-test comparison with the fixed-round models.
Only 9,507 three-year proxy outcomes are identifiable; 9,353 remain unresolved.
Resolved-subset diagnostics are not full-population calibration.

## Where the Outputs Are

- `reference_model/`: original recipe's saved model, metadata, CV report,
  feature importance and tract scores.
- `corrected_research/legacy_50/` and
  `corrected_research/corrected_context_plus_restaurant/`: full fitted native
  models, explicit proxy metadata and feature importance.
- `corrected_research/*_fold_*.json`: 30 native fold models, with held-out
  predictions, complete training matrix, assignments, borough metrics,
  ablation results and baseline comparisons in the same folder.
- `scenarios/`: all 1,000 synthetic-property outputs, frozen access/Huff
  evaluations and 10%/20% optional-weight ranking sensitivity for four concepts.
  Access/Huff coverage gaps stay missing, not favorable zeroes. No weight is
  selected as optimal and no customer visits are invented.
- `frozen_root/data/`, `code_snapshot/`, `research_plan.json`, `logs/` and
  `run_manifest.json`: exact source copies, versioned code, assumptions,
  processing logs, package versions and artifact hashes.

Use held-out predictions for model evaluation; full fitted-cohort/property
predictions are not additional test observations. The new walking/Huff features
remain concept-specific property scenarios, not backdated historical predictors.

The independent validator checks every frozen artifact hash, unique cohort IDs,
complete five-fold NTA assignments and target alignment, and replays all 30 native
models on their saved held-out rows. Validation uses round-trip CSV float parsing
to preserve strict interval comparisons after serialization.

## Repeatable Commands

```bash
# New output directory required; this does not overwrite the completed run.
.venv/bin/python codes/run_archive_research.py \
  --output data/output/research_runs/NEW_RUN \
  --acknowledge-proxy

.venv/bin/python codes/validate_archive_run.py \
  --run data/output/research_runs/20261027_archive_aft_v2 \
  --output data/output/research_validation/NEW_VALIDATION

.venv/bin/python -m unittest discover -s codes -p 'test_*.py'
```

Run v1 stopped during property export after model fitting; its failure log is
retained. Run v2 is complete and is the canonical saved package. No source
datasets were deleted, no outputs were uploaded, and no proxy model was silently
promoted into the dashboard as verified survival.

These holdouts are now consumed research results. Further feature/parameter
selection requires a separate development protocol and later untouched test,
not repeated tuning against the same results described as independent validation.
