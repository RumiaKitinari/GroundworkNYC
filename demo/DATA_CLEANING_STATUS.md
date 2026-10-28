# Data Cleaning and Historical Preparation

October 20, 2026 (America/New_York).

This records the initial 193-column audit. A subsequent completion release
adds the supported missing features and resolves generic numeric units;
see `CURRENT_MASTER_COMPLETION.md` and the current release's reports for
the latest state. The earlier audit and its source files remain unchanged.

## Reproduce

From the repository root:

```bash
.venv/bin/python demo/audit_training_data.py
.venv/bin/python -m unittest discover -s demo -p 'test_*.py'
```

Each audit creates a new private directory under `data/evaluation/cleaning/`.
The active release, raw datasets, adjudication packet, and frontend are not
modified. Input checksums are recorded and checked again before output.

The reviewed run is `data/evaluation/cleaning/20261021T000208383395Z/`.
An earlier preliminary run ending `000121076279Z` is marked superseded because
its initial percentage bound ignored dictionary units. Do not use its issue counts.

## Findings

- The active master has 2,327 tracts and 193 columns. The implemented ID,
  numeric-bound, denominator, dictionary-presence, and rent-unit checks found
  no violations. This does not establish source accuracy or model validity.
- Commercial rent is a 2024 reported tract median in dollars per square foot
  per month. There are 1,330 reported values, 93 publisher `*` markers, and
  904 tracts without a row in the latest-year source. No source rent code was
  rejected and no latest-year source tract fell outside the master. All
  reported monthly values and annual conversions reconcile with the raw file.
- Missing rent remains blank, never zero. No rents were invented or substituted
  from residential rent or synthetic property scenarios.
- The storefront vacancy-share column is entirely blank and excluded from the
  historical feature policy. Current source coverage does not support that rate.
- Existing `pct_` columns use mixed documented scales: six legacy measures are
  percentages (0-100), while the newer age-20-34 field is a share (0-1).
  Validation and the preparation policy use dictionary units, not the name alone.
- Eighty numeric columns still carry generic `varies` units. The column report
  identifies them for source-specific metadata review. Their units were not
  silently guessed or rewritten.
- Four identical column pairs were flagged, not deleted: pedestrian site ID/location,
  two event count/date pairs, and households/occupied housing units. Equality
  can be expected or period-dependent; it does not alone justify deduplication.

## Restaurant Identity and Historical Inputs

All 5,999 existing candidate records were processed. The packet contains 4,484
same-name/address matches, 127 possible CAMIS changes, 18 name/address changes,
and 1,370 without a current CAMIS record. The new 1,590-row review queue also
flags duplicate normalized historical identities and cross-source conflicts.
These are review leads, not automatically resolved identities or closure labels.

A separate, explicitly non-training candidate matrix retains all 5,999 cases.
For each first-cycle-inspection baseline lead it selects only historical
predictors released on or before that date. Per-feature release dates and
source paths are included; 3,486 candidates have all four historical predictors.
The remaining cases are retained with blanks, not backfilled from current data.
An inspection baseline lead is not an independently verified opening date.

The existing verified-cohort builder was rerun: zero records meet the independent
baseline/outcome evidence requirements. No survival model was trained and no
disappearance was converted into a permanent-closure label.

## Preprocessing Safeguards

The offline evaluator now fits missingness indicators alongside median
imputation inside each estimator's training-only pipeline. The evaluation
version is incremented to 0.3 and reports identify indicator feature names.
Tests verify that held-out values do not influence imputation medians or
indicator selection. Frozen prior model artifacts are not changed.

The verified survival cohort still requires complete historical predictors.
Indicators do not bypass that eligibility rule, independent-outcome checks,
or the predeclared temporal/geographic holdout. Current master fields default
to excluded unless corresponding historical provenance has been verified.

All 182 demo tests passed; `git diff --check` passed. Remaining substantive work
is identity/evidence adjudication and source-specific metadata improvements,
not replacing missing data with zero or training on unverified closures.
