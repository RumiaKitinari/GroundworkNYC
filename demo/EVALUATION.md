# Evaluating Groundwork Without Opening Restaurants

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

This tests agreement with today's market distribution, not success or historical
forecasting. Current survivors and inventory eligibility bias the sample. A model
of existing markets can miss novel cuisine opportunities: do not invert it into
a gap score, or claim it validates our Business Draw score. Sparse-inventory
areas are excluded, and the current demo excludes Staten Island.

## Historical continued operation

Build a cohort of other businesses operating at a dated baseline, including
those that subsequently closed. Use archives and independent dated evidence,
not just today's survivors. No Groundwork leases are needed.

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
