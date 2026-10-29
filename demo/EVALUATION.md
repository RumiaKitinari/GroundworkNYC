# Evaluating Groundwork Without Opening Restaurants

The current first-stage training gate and review protocol are summarized in
[SURVIVAL_READINESS.md](SURVIVAL_READINESS.md).

The backend supports an immediately runnable **market-presence benchmark** and
a **continued-operation evaluation** requiring verified historical outcomes.
Neither is a profitability model. Evaluation stays separate from dashboard
rankings and does not publish a business-success percentage.

## Run locally

From the project root:

```bash
.venv/bin/python -m pip install -r demo/requirements-evaluation.txt
.venv/bin/python demo/evaluate.py --cuisine korean
.venv/bin/python -m unittest discover -s demo -p 'test_*.py'
```

- `GET /api/evaluation`: available targets and local report paths.
- `POST /api/evaluation/run` with JSON
  `{"target":"market_presence","cuisine":"korean"}`: train and evaluate.
- The same POST with `{"target":"continued_operation","cutoff":"2024-01-01"}`:
  evaluate historical outcomes when a valid file exists. This date is an example,
  not a claim that the current package has historical feature snapshots.

Training is explicit, never triggered by a dashboard page load. ML dependencies
are optional. Each run creates a JSON report under `data/evaluation/reports/`.
Reports and outcome files belong with private data and must not be pushed with
demo source. Reports include input SHA-256 hashes, model settings, baselines,
held-out metrics, calibration bins and serialized numeric model parameters.

## What can be evaluated now

An additional offline subway-entry model uses three complete 2025 MTA weeks
for training and holds out a December week. Run `python demo/download_subway.py`
then `python demo/train_subway.py`. It predicts station-hour entries and reports
MAE, RMSE and R2 against a station-average baseline. It is not a restaurant
success, pedestrian-traffic or revenue model and does not affect rankings.

The market-presence target asks whether a tract has a **recorded active restaurant
of the selected cuisine**. The master table supplies eight location predictors;
integrated `entities/current_restaurants.csv` supplies cuisine labels, deduplicated
by CAMIS. Only tracts with ten or more restaurants and 80% usable cuisine labels
qualify. Zero recorded same-cuisine establishments is not a failed business.

The model is regularized logistic regression with fixed parameters. Inputs use
`log1p`, training-only median imputation and training-only scaling. No parameters
are selected using the test set. Cuisine counts, restaurant counts, grades and
Groundwork scores are excluded from predictors. Our existing scores already use
cuisine inventory, making them circular predictors for this target.

Entire NTA neighborhoods are held out using a fixed seed and 25% group fraction.
Adjacent neighborhoods can remain correlated. Compare the model against:

1. Training cuisine prevalence alone.
2. Walkability alone.
3. Resident and job density alone.

Reports include ROC AUC, average precision, Brier loss, top-quintile precision
and lift, calibration bins and borough breakdowns. The uncertainty interval
resamples held-out neighborhoods. Fractional ties avoid arbitrary baseline lift.
Training/test prevalence differences and small borough samples are flagged.
Each report also refits the model eight times, omitting one input at a time.
The Brier and average-precision differences are exploratory ablations on one
fixed holdout, not evidence that a feature causes business success or failure.

This tests agreement with today's market distribution, not success or historical
forecasting. Current survivors and inventory eligibility bias the sample. A model
of existing markets can miss novel cuisine opportunities: do not invert it into
a gap score, or claim it validates our Business Draw score. Sparse-inventory
areas are excluded, and the current demo excludes Staten Island.

## Historical continued operation

### First-stage survivability preparation

The first-stage target is **one-year continued operation**, not revenue,
profitability, or the probability that a proposed restaurant succeeds. The
October 2026 inspection export contains only establishments active on its
record date. Its 31,516 inspection-derived rows are review candidates, not
permanent-closure labels.

Generate a private, reproducible 100-row review queue across the five boroughs:

```bash
.venv/bin/python demo/prepare_survival_review.py
```

The queue is in `data/evaluation/survival_review_<timestamp>.csv`. Every row
starts `independent_verification_required` and `unresolved`, including rows
with a DOHMH closure order. The reviewer must fill the evidence columns using
two distinct dated references: one showing operation at the baseline and a
later one showing continued operation or permanent closure. Add former
businesses from an independent historical source to the evidence file; the
current-active queue alone is survivor-biased. An absence from a current list,
inspection gap, health closure, or expired listing does not prove failure.
Keep ambiguous cases unresolved.

For a separate pool of potential former businesses, run:

```bash
.venv/bin/python demo/prepare_historical_review.py
```

This archives the complete official DOT Open Restaurants historical inspection
export locally and makes a private, reproducible review queue. The usable
December 2023-May 2024 window contains 1,136 geocoded restaurant candidates.
The queue samples both businesses with and without a plausible current
inventory match, records the match basis and sampling probability, and leaves
every outcome unresolved. Outdoor-dining participation is a selected subset;
neither a setup inspection nor the lack of a current match proves business
operation or permanent closure. Reviewers still need dated, independent
baseline and follow-up evidence. Do not treat these stratified review queues
as a representative failure-rate sample or directly calibrate survival
probabilities on them; sampling weights cannot correct the source-frame bias.

To prioritize manual review, match that queue against the full local DOHMH
inspection export with `demo/prepare_survival_evidence.py` as described in
`SURVIVAL_READINESS.md`. This produces dated inspection leads and record-specific
links, not survival labels. The export contains current-active establishments,
so unmatched cases must not be classified as closures.

The separate CAMIS snapshot tracker in `PERMIT_PRESENCE.md` compares complete
publisher-record-date exports and flags repeated absences for manual review.
It is wired into the daily restaurant source refresh. Its one-year target is
permit persistence, **not** verified business survival, and it publishes no
training labels or dashboard score from today's short observation window.

The core historical predictors are tract population density, median household
income, job density, and EPA walkability. They have official 2023-available and
2024-available vintages in a combined private manifest. Rebuild the earlier
archives without altering current dashboard data:

```bash
.venv/bin/python demo/build_early_historical_snapshots.py
```

The earlier ACS 2022 vintage became public December 7, 2023; 2021 LODES on
November 15, 2023. The join selects the latest source available by each
business's baseline date. Source files and manifests are fingerprinted;
SAMPLE files are ineligible. Once independently verified cases exist:

```bash
.venv/bin/python demo/prepare_historical_cohort.py \
  --feature-set historical_core \
  --evidence data/evaluation/verified_cases.csv \
  --snapshots data/evaluation/snapshots/2023-12-v1/historical_core_snapshots.json \
  --output data/evaluation/business_outcomes_core.csv
.venv/bin/python demo/evaluate.py --target continued_operation \
  --feature-set historical_core --cutoff YYYY-MM-DD
```

For a preliminary neighborhood-only check before a suitable later baseline
frame exists, omit the cutoff and pass `--validation-mode spatial_exploratory`.
Its report explicitly says temporal generalization has not been tested.

The same feature set is available in the offline `POST /api/evaluation/run`
body as `"feature_set": "historical_core"`. It does not appear in the customer
dashboard unless explicitly requested through that endpoint.

Preselect the cutoff before viewing test results. The neighborhood-plus-time
split needs 60 training and 30 test cases, including ten of each outcome in
both partitions. It compares prevalence, walkability, density, logistic
regression, and a fixed shallow histogram gradient booster. Reports include
Brier score, average precision, ROC AUC, calibration bins, and borough
breakdowns. Training stays research-only and never changes dashboard rankings.

The four-feature core is a first experiment. Transit and parcel signals still
need dated historical evidence for the full eight-feature model. Missing
cuisine labels do not block the general model; cuisine, price, format, and
operator factors require historical values before they can be added.

To prepare a private review queue from the full restaurant inspection export:

```bash
.venv/bin/python demo/prepare_outcomes.py
```

This writes `data/evaluation/outcome_candidates_<revision>.csv` and a provenance
manifest. Every row remains `independent_verification_required`. A DOHMH closure
order or long inspection gap is a lead for research, never an outcome label.
The queue is not read by model training.

Build a cohort of other businesses operating at a dated baseline, including
those that subsequently closed. Use archives and independent dated evidence,
not just today's survivors. No Groundwork leases are needed.

`prepare_historical_cohort.py` now provides an audited join for this step. Place
an independently reviewed case CSV and dated tract snapshots in private `data/`.
The case CSV requires `business_id`, `geoid`, `nta_code`, `borough`, `as_of_date`,
`baseline_operating`, `baseline_source_reference`, `verification_status`,
`outcome_status`, `outcome_observed_on`, `outcome_recorded_on`, and
`outcome_source_reference`. Only `independently_verified` cases with separate
baseline and outcome evidence qualify. Unresolved cases remain unlabeled.

The snapshot JSON has a `snapshots` list. Each entry names one of the eight
evaluation `feature` values, a CSV `path` relative to private `data/`, its
`column` and `geoid` key, `observed_through`, `available_on`, `sha256`,
`source_url`, and `historical_reconstruction_verified: true`. Keep distinct
vintages as separate entries. The builder selects the latest *available* value
at each business's baseline date, rejects missing features and SAMPLE files,
and records source fingerprints. The manifest's dates and verification flag
must be checked against publisher archives by a human; they are not inferred
from file modification times.

```bash
.venv/bin/python demo/prepare_historical_cohort.py \
  --evidence data/evaluation/verified_cases.csv \
  --snapshots data/evaluation/historical_snapshots.json \
  --output data/evaluation/business_outcomes.csv
```

The script never overwrites an existing cohort. Without verified cases and
historical snapshots it reports exclusions and writes no training file. The
current 2026 integrated master is **not** a historical snapshot for earlier
baseline dates; downloading older publisher releases and documenting their
actual release dates is still required.
When rows qualify, a neighboring `.audit.json` records the case-file,
manifest, and selected snapshot fingerprints for review.

### Available Historical Snapshots

Run `.venv/bin/python demo/build_historical_snapshots.py` to reproduce the
private `data/evaluation/snapshots/2024-12-v2/` tranche. It downloads the full
official 2019-2023 ACS B01003 and B19013 tables and 2022 LODES WAC JT00 file,
then combines those with the pinned EPA v3 walkability crosswalk. The output
contains four of the eight evaluation features: tract population density,
median household income, workplace job density, and National Walkability Index.
It does not modify the active dashboard release or public Git files.

The ACS tract release became public December 12, 2024; 2022 LODES was announced
November 19, 2024; EPA v3 was posted June 2021. Source URLs, raw and snapshot
SHA-256 hashes, coverage counts, and conservative observation dates are in
`partial_historical_snapshots.json`. The first local build covers all 2,327
master tracts for population density, 2,192 for non-suppressed income, and 2,322
for walkability; it aggregated 25,279 LODES blocks. Missing values remain blank.

The 2024 partial manifest intentionally cannot produce the **full eight-feature**
training cohort. The combined 2023/2024 manifest supports the separate
four-feature core cohort once verified outcomes are supplied. Historical
nearest-subway distance, observed weekly ridership, retail area, and mixed-use
parcel count still need verified archive vintages and release dates. The MTA's
separate 2020-2024 hourly dataset is a candidate, but its present archive does
not establish when individual 2024 rows first became available. Avoid assigning
it a convenient 2024 release date. The current PLUTO release is not a substitute
for a 2024 parcel snapshot.

Run `.venv/bin/python demo/download_subway.py --historical` to archive the full
December 1-7, 2023 MTA station-hour week, then run
`.venv/bin/python demo/build_historical_transit_candidate.py` to create a
tract-level candidate. The local archive has 69,733 station-hour records, 168
hours, and 424 complexes; the candidate covers all 2,327 master tracts. These
files live under `data/evaluation/` and are **not** training eligible. The
current MTA historical table may include corrections entered after the proposed
2024 baseline; establish a dated public snapshot or revision history before
promoting the candidate. The 24v4 PLUTO documentation describes a November 2024
release, but its separate archived data file must still be retrieved and checked.

Run `.venv/bin/python demo/audit_hex_resolution.py --resolutions 8 9
--integrated-dir data/integrated/current --output data/evaluation/reports/hex_resolution_<date>.json`
to measure Census-block coverage against the active single-hex grids. Then run
`.venv/bin/python demo/validate_groundscore.py --hex-report
data/evaluation/reports/hex_resolution_<date>.json --output
data/evaluation/reports/groundscore_behavior_<date>.json` to audit 30 concept
scenarios, component overlap, and +/-20% weight sensitivity. Use a new output
filename for each run. These reports test geometry and score behavior, **not**
accuracy or survival. The October 13 audit uses H3 resolution 8 as the single-
hex default; resolution 9 is exploratory because it subdivides the same tract
inputs. Demand/customer fit and demand/market-gap overlap need review before
weight calibration. The audit fingerprints the active master and geometry so a
stale hex report cannot be paired with a newer release. `/api/evaluation` exposes the current historical-feature
readiness and keeps candidate subway features separate from verified snapshots.

- ACS 2022 release: https://www.census.gov/programs-surveys/acs/news/data-releases/2022/release.html
- ACS 2023 release: https://www.census.gov/programs-surveys/acs/news/data-releases/2023/release-schedule.html
- LODES 2022 announcement: https://lehd.ces.census.gov/announcements.html
- EPA v3 source: https://edg.epa.gov/data/public/OLEM/SLD/
- MTA 2020-2024 archive: https://data.ny.gov/d/wujg-7c2s

Use `examples/business_outcomes.template.csv` as the column contract and place
the completed file at `data/evaluation/business_outcomes.csv`. One row per business:

- `business_id`, `nta_code`: unique business ID and neighborhood.
- `as_of_date`: prediction date; `baseline_operating` must be `true`.
- `features_observed_through`: latest period covered by any feature.
- `features_available_on`: latest release date among those feature snapshots.
- `outcome_status`: `verified_operating`, `verified_permanent_closure`, or
  `unresolved`. Regulatory closures are not permanent business failures.
- `outcome_observed_on`, `outcome_recorded_on`: occurrence and evidence dates.
- `source_reference`: independently checked dated evidence or archive.
- Eight numeric feature columns: historical values available at baseline.
  Use the applicable historical income vintage in `median_household_income`.

The validator requires feature observation <= availability <= prediction date
< outcome observation <= evidence recording <= today. Metadata cannot verify
provenance automatically; audit the sources. Never use current 2026 features as
predictors for 2022 outcomes.

A positive is verified operation 365-455 days after baseline. A negative is a
verified permanent closure within 365 days. Later closures, absent listings,
unresolved records and immature observations are not failures. Excluded records
are counted. This binary baseline is not a censored survival model. Continued
operation itself does not imply profitability or uninterrupted operation.

Training uses earlier cohorts with outcomes recorded before the cutoff; tests
use later cohorts in separate neighborhoods. Both partitions require ten or more
examples of each outcome, with at least 60 train and 30 test rows. Insufficient
data returns a status, never invented accuracy. The initial operation model pools
businesses and uses location features only; cuisine, prices and operator details
need additional historical inputs and separate evaluation in later versions.

## Other practical validation methods

1. **Historical cohorts:** archived permit/business listings, owner websites and
   dated opening/closure announcements. Verify closure across sources. Include
   failures and freeze features before observing outcomes.
2. **Independent demand counts:** observe pedestrians and restaurant entries at
   matched existing sites and consistent dayparts. Record weather/day-of-week;
   pedestrians are not diners. Compare predicted rankings without revealing them
   to observers in advance.
3. **Customer-choice study:** show realistic menus, prices and locations to
   prospective diners; hold out respondents and locations. Stated preference is
   not actual purchasing behavior.
4. **Blinded operator review:** experienced operators rank sites without seeing
   Groundwork scores. Examine agreement and disagreements. Opinion is a separate
   benchmark, not a success label.
5. **Consented partner aggregates:** established operators provide historical
   visits, covers or sales. Hold out operators, locations and later periods.

Predefine targets, horizons and acceptance criteria. Preserve a final untouched
cohort, compare against simple baselines and report uncertainty and subgroup
failures. Repeatedly using one holdout eventually makes it development data.

## Sources

NYC DOHMH states that only restaurants active on the record date are included.
An inspection export cannot be assumed to contain representative failed
businesses. Multiple violations also repeat inspections. Health closures, poor
grades and missing establishments must not become financial-failure labels.

- NYC source: https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j/about_data
- Group holdouts: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html
- Logistic regression: https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html
- Brier loss: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html
