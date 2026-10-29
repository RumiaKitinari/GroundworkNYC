# Archived NYC Restaurant Lifespans

The private source is a pinned copy of
[`nyc-cuisine-atlas`](https://github.com/CharlesFainLehman/nyc-cuisine-atlas)
at commit `20db98e6d2a1b2699b7a42c2e90df2edaed154e5`. Its author consolidated
13 Internet Archive captures of the NYC DOHMH restaurant-inspection feed from
September 2015 through April 2026 plus a current October 2026 export. The
local `data/raw_sources/nyc_cuisine_atlas/<commit>/` directory contains the
consolidated restaurant and inspection Parquet files, source scripts and README,
and one original November 2023 capture for a spot-check. The original capture's
28,376 CAMIS IDs were all present in the consolidated table with compatible
first/last snapshot dates. The full original Wayback capture archive was not
downloaded; the third-party consolidation still needs broader independent QA.

The [official DOHMH feed](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j)
contains active-status establishments as of its record date, not a permanent
closure registry. The third-party project's script assigns randomized closing
dates inside snapshot intervals; those dates are **not** used here. Source
code and data should remain private pending redistribution/license review.

`build_restaurant_lifespans.py` reconstructs one row per CAMIS with first/last
observed snapshot, the next dated snapshot, first operational pre-permit
inspection, an opening-date proxy, 2020 census tract, and lower/upper bounds
on **listing persistence**. These bounds are not proven restaurant lifespans.
The conservative candidate flag requires a post-November-2020 operational
pre-permit inspection no later than first appearance, first appearance within
365 days, no earlier inspection, and a mapped tract. It excludes the first
post-archive-gap snapshot to reduce left truncation. This is a review filter,
not a verified opening or outcome label. NYC's
[pre-operational inspection guidance](https://www.nyc.gov/site/sbs/businesses/food-establishment-form.page)
says no food or drink may be on site during that inspection. The CSV's
`open_date` is retained for compatibility with the source specification but
actually means **pre-permit inspection date**, not verified opening. The review
queue deliberately leaves `as_of_date` blank. Its `first_cycle_inspection_lead`
is a stronger operating-date lead because [NYC says routine inspections occur
when a restaurant is open and serving customers](https://portal.311.nyc.gov/article/?kanumber=KA-01057),
but it may occur well after opening and must still be checked. The latest
name/address in the archive may reflect a later identity change.

The October 20 build produced 67,790 CAMIS rows, 5,999 strict candidates,
1,073 potential one-year operational follow-up inspections, and 80 within-year
snapshot exits for priority review. All candidates have `outcome_status` set
to `unresolved` and `training_eligible=false`. The current review queue is
`data/evaluation/lifespans/review_queue_20261020_v4.csv`; the corresponding
candidate table is `restaurant_lifespans_20261020_v4.csv`. Earlier v3 files
remain for audit history but should not be used for adjudication because they
pre-filled the pre-permit date as the baseline. An operational
inspection can prompt review of continued operation; absence, temporary
health closure, or a snapshot exit does not establish permanent closure.

The current private manual pilot is
`data/evaluation/lifespans/manual_pilot_20261020_v2.csv`: 20 suspected exits
and 20 comparison cases with inspection-follow-up leads. This targeted sample
is not representative and cannot estimate citywide survival prevalence or
calibrate a probability. It includes direct CAMIS lookup, manual search links,
and State Liquor Authority license leads; it does not scrape search results or
infer labels.

The consolidated private adjudication packet is
`data/evaluation/lifespans/adjudication_packet_20261020_v4.csv`. Its exact
same-name/address check across *different* current CAMIS IDs found 104 possible
permit transitions among candidates missing under their original CAMIS. These
are identity-review leads, not established continuity. A 600-case random
review sample from 4,030 follow-up-mature candidates is saved beside it; see
`SURVIVAL_READINESS.md` for its selection rule and limitations.

The official [NYS inactive license](https://data.ny.gov/d/6dg3-2z7i) and
[active license](https://data.ny.gov/d/9s3h-dpkz) tables are downloaded through
their public Socrata APIs into `data/raw_sources/sla_licenses/`. The October 20
private revision contains 29,754 inactive and 24,846 active NYC license rows.
Conservative name, borough, address, and ZIP matching yields 122 inactive-only,
431 active-only, and 67 both-status leads among 5,999 DOHMH candidates. The
full cross-reference is `data/evaluation/lifespans/sla_review_leads_20261020_v2.csv`.
These are **license** records, not restaurant operating records. A restaurant
may lack a liquor license, move, change licensee, or remain open after one
license becomes inactive; `expiration_date` is not a closure date. Do not use
these matches as model labels. The current manual pilot includes this context
but has all outcome fields unresolved.

For each pilot row, first decide whether it is a restaurant/bar in scope and
whether the CAMIS, name, and address refer to one continuous business. Record
the earliest dated evidence that it was actually operating, then verify either
the same business operating 365-455 days later or a documented permanent
closure within 365 days. A successor tenant, an expired permit, a missing
DOHMH row, a temporary health closure, or a company filing alone is not enough
to date permanent closure. Keep uncertain or never-opened cases unresolved.
Record source URLs, dates, reviewer, and notes; obtain a second review before
moving any row to the training evidence file. For official permit/closure
history not visible publicly, NYC DOHMH lists additional records as available
by [request](https://www.nyc.gov/assets/doh/downloads/pdf/ogc/foil-subject-matter-list.pdf).

The separate `build_pre2023_historical_snapshots.py` downloads official 2021
ACS tract population/income and 2020 LODES workplace jobs, then adds them to
the already pinned later historical features. The manifest is
`data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json`.
Release dates come from the [Census 2022 schedule](https://www.census.gov/data/what-is-data-census-gov/latest-releases.2022.html)
and [LEHD announcements](https://lehd.ces.census.gov/announcements.html).
The cohort builder selects only features published by each business baseline.

Reproduce a fresh private lifespan table, audit it, and prepare a review queue:

```bash
.venv/bin/python demo/download_lifespan_archive.py
.venv/bin/python demo/build_restaurant_lifespans.py --output data/evaluation/lifespans/new_lifespans.csv
.venv/bin/python demo/audit_lifespan_source.py data/evaluation/lifespans/new_lifespans.csv
.venv/bin/python demo/prepare_lifespan_review.py --lifespans data/evaluation/lifespans/new_lifespans.csv --output data/evaluation/lifespans/new_review_queue.csv
.venv/bin/python demo/download_sla_licenses.py
.venv/bin/python demo/match_sla_lifespan_leads.py --queue data/evaluation/lifespans/new_review_queue.csv --output data/evaluation/lifespans/new_sla_leads.csv
.venv/bin/python demo/prepare_manual_lifespan_pilot.py --queue data/evaluation/lifespans/new_review_queue.csv --sla-leads data/evaluation/lifespans/new_sla_leads.csv --output data/evaluation/lifespans/new_manual_pilot.csv
```

The guarded training command accepts the review queue as input but returns
`needs_verified_outcomes` without a model until a reviewer records independent
baseline and outcome evidence. Once that evidence exists, set a predeclared
cutoff and run `demo/run_survival_training.py` as described in
`SURVIVAL_READINESS.md`. Do not promote snapshot-derived exits to failures.
