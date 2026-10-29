# Closure Validation Research: October 21, 2026

## Findings

Atharv's training labels have not been audited here. Training from a shared Drive
file does not establish whether its outcomes were verified. Obtain the actual
training file/version, label-generation code, time origin, horizon, feature
vintages, identity rules, splits, and evaluation results before drawing that
conclusion. No newly verified survival labels were created by this research.

### Additional Public Evidence: Overture Places

Downloaded the complete NYC-area bounding-box extract from all 16 Places
partitions in public release `2026-09-23.1`: 614,559 POIs, including 32,026
permanently-closed statuses. These are all place types in a bounding box that
also includes nearby areas outside NYC, not 614,559 NYC restaurants. There is no
sampling, confidence threshold, status filter, or row limit. Remote Parquet
filtering avoids downloading every global source byte. The manifest retains
source object sizes/ETags, extraction scope, and the local SHA-256 checksum.

The latest conservative name/address/ZIP match against all 5,999 candidates is:

| Result | Candidates |
| --- | ---: |
| Matched permanently closed | 17 |
| Matched open | 1,937 |
| Matched, status unspecified | 132 |
| Ambiguous multiple places | 18 |
| No conservative match | 3,895 |

The 17 closed matches add leads beyond the earlier Foursquare closed group:
12 had no conservative Foursquare match and five were not marked closed there.
Four of the 17 still have the same name/address in the current DOHMH review
feed. Nine earlier Foursquare closure leads now match an Overture open status.
These are adjudication conflicts, not automatically proven errors in either
source. Current directories may be stale, and businesses may reopen or change
operators. An Overture open status does not establish uninterrupted operation.

Sixteen closed matches include BrightQuery provenance; the remaining one
includes Meta/Overture. None explicitly lists Foursquare, but this does not
prove upstream independence. Overture can incorporate Foursquare, so agreement
between the two should not automatically count as independent confirmation.
The feature confidence measures existence, not calibrated closure probability;
permanently-closed features have confidence zero and must not be discarded for
that reason. Provider update times and release dates are not closure dates.

Official documentation:
- [Places guide](https://docs.overturemaps.org/guides/places/)
- [Place schema](https://docs.overturemaps.org/schema/reference/places/place/)
- [Operating status](https://docs.overturemaps.org/schema/reference/places/types/operating_status/)

## Dated Evidence and Time-Origin Checks

These targeted cases establish useful evidence paths, not representative closure
rates. Source summaries are in the private JSON registry; articles were not
copied into a dataset.

### Lords Bakery: Strong Site-Exit Evidence

CAMIS `50118834`, 2135 Nostrand Avenue, Brooklyn. Eater's March 26, 2024
on-site reporting describes a March 25 possession notice and permanent-closure
sign. News 12's March 29 owner/court reporting supports the exit from the
Flatbush site, while mentioning possible reopening elsewhere. This supports
a site-exit review, not necessarily extinction of the brand. Do not confuse
the March 25 notice and March 29 court report as identical event dates.

The original capture now shows that the candidate April 11, 2023 first-cycle
date was a temporary DOHMH shutdown, not an operating anchor. An April 14
reopening and October 4 routine inspection provide later operating evidence.
Its February 2022 pre-permit lead is not the bakery's original opening.
Baseline operation, operator identity, and the declared target must be resolved
before assigning a one-year outcome. See the follow-up report below.

- [Eater on-site reporting](https://ny.eater.com/2024/3/26/24112793/lords-bakery-flatbush-nostrand-junction-closing-decades-old)
- [News 12 owner/court reporting](https://brooklyn.news12.com/judge-forces-lords-bakery-to-shut-down-due-to-unpaid-bills)

### Anella: Closure Report, Unresolved Operator Clock

CAMIS `50111797`, 222 Franklin Street. Greenpointers reported permanent closure
on October 19, 2022 and a May 2009 opening. The candidate pre-permit lead in
November 2021 cannot be assumed to be the site's first opening. It may refer
to a different operator/permit episode; that remains unresolved. The report
date is a closure-by bound, not an exact last trading day.

- [Address-specific local reporting](https://greenpointers.com/2022/10/19/reliable-greenpoint-restaurant-anella-closes-permanently/)

### Mimi Cheng's: An Earlier Opening Than the Candidate Permit

CAMIS `50133825`, 224 Atlantic Avenue. Brooklyn Magazine's April 6, 2023
on-site coverage establishes operation before the candidate August 2024
pre-permit lead. Eater's November 1, 2024 closing entry identifies the same
site. The roundup was later updated on November 22; preserve entry date,
page update date, and uncertain actual closure timing separately. Resolve the
operator/CAMIS episode before inferring lifespan or early failure.

- [Opening coverage](https://www.bkmag.com/2023/04/06/mimi-chengs-stellar-dumpling-and-noodles-are-now-in-brooklyn/)
- [November 1 closing entry](https://ny.eater.com/2024/11/1/24282982/restaurant-closings-november-2024)

## Practical Validation Workflow

1. Declare the unit and clock: operator-at-address versus site/brand; survival
   from actual opening versus remaining survival from a verified operating date.
   Do not redefine these after inspecting model performance. Known established
   restaurants need an appropriate entry/age treatment, not invented opening dates.
2. Prioritize the 17 Overture leads, existing 31 Foursquare closure leads, and
   source disagreements for identity and dated-event review. Do not assume these
   review strata are exhaustive or suitable for estimating overall closure rates.
3. Seek explicit operator closure notices and dated first-hand reporting, then
   permit surrender/cancellation history or official case records where available.
   A health-department temporary closure, expired license, bankruptcy filing,
   building permit, inactive corporation, disconnected phone, or missing website
   alone is not evidence of permanent restaurant exit at that address.
4. Record source URL, publication/observation/recording dates, exact identity,
   last confirmed operation, closed-by bound, reopening/relocation evidence, and
   reviewer decision. Distinguish copied reports from independent corroboration.
5. Audit probable survivors and unresolved disappearances too. Checking only
   newsworthy closures creates selection bias. Use stratified random auditing
   across borough, age, cuisine/format, and source-status groups; retain inclusion
   probabilities for audit estimates. A human-reviewed holdout should remain
   separate from iterative label-rule tuning.
6. Preserve unknown outcomes. Report coverage and label disagreement, and compare
   proxy-label results with the audited subset. Keep historical predictor cutoffs
   before the prediction date and temporal/geographic holdouts unchanged.

The existing DOHMH permit-history FOIL document is a draft, not a submitted
request or an available historical dataset. A lawful records request may help
but is not an immediate guaranteed solution. No account restrictions, CAPTCHAs,
or publisher controls were bypassed for this research.

## Timing Workaround: Interval-Censored Gradient Boosting

When a permanent exit is supported but its exact day is unknown, retain the
interval between the last confirmed operation and the confirmed closure-by date.
For a business still operating at its last verified follow-up, right-censor at
that observation rather than treating it as immortal or definitely closed later.
An unknown outcome is not automatically a verified right-censored observation.

XGBoost supports these bounds with `survival:aft`, `label_lower_bound`,
`label_upper_bound`, and `xgboost.train`. This handles uncertain timing, NOT
uncertain event identity or whether a closure actually occurred. It is a
candidate extension to the planned gradient-boosting baseline, not a reason to
change the briefing's target or mark provider leads as truth. A binary 365-day
label still requires the verified event interval to lie wholly before the
horizon, or verified operation at/after it with identity/continuity reviewed;
an interval straddling the horizon does not determine a binary outcome.

The current backend model loader accepts `binary:logistic`, not `survival:aft`.
An AFT experiment would need a separate adapter, survival-probability conversion,
calibration, and validation before deployment. It is not a drop-in replacement.

- [Official XGBoost interval-censoring tutorial](https://xgboost.readthedocs.io/en/stable/tutorials/aft_survival_analysis.html)

## Source Ruled Out for NYC

The NYS food-establishment inspection series links an inactive-establishment
table, but its coverage explicitly excludes NYC (also Suffolk and Erie).
It cannot fill our NYC outcome labels. It could only support a separately
scoped external-method exercise with careful comparability checks.

- [Official NYS series coverage](https://health.data.ny.gov/Health/Food-Service-Establishment-Inspections-Beginning-2/2hcc-shji)

## Reproduce and Review

```sh
.venv/bin/python -m pip install -r demo/requirements-closure-research.txt
.venv/bin/python demo/research_overture_closures.py --release 2026-09-23.1
.venv/bin/python -m unittest discover -s demo -p 'test_research_overture_closures.py'
```

The extractor validates cached local checksums and publishes new timestamped
match outputs rather than overwriting review history. It never edits the master,
changes outcome labels, or makes any case training-eligible. Matching is a review
aid: name/address agreement does not establish operator continuity.

Private local files:
- `data/raw_sources/overture_places/2026-09-23.1/manifest.json`
- `data/raw_sources/overture_places/2026-09-23.1/nyc_area_places.csv`
- `data/evaluation/closure_research/20261021T153343569385Z/overture_review.csv`
- `data/evaluation/closure_research/20261021T153343569385Z/report.json`
- `data/evaluation/closure_research/manual_case_sources_20261021.json`

Use the `153343569385Z` match output above. The earlier exploratory `153146710597Z`
output used an overly broad building-range normalization and is superseded.
No frontend or active integrated-release changes were made for this research.

## Follow-Up: Original Events and Additional Date Bounds

See `CLOSURE_DATE_SOLUTIONS_20261021.md` for the full original-capture event
ledger, additional published opening/exit sequences, and source-access findings.
The ledger supersedes reliance on snapshot presence as an operating observation.
