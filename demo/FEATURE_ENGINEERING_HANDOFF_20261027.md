# Feature Engineering Update for Atharv

## Completed and Tested

The latest Methods Report is the primary design reference. All four supplied
briefings and the previous proposal were checked for changes in direction.
The current implementation keeps cuisine out of general survival modeling and
introduces customer access as a separate prospective feature component.

We added a working first version of inverse walkability's **walking component**.
It estimates how readily surrounding resident and workplace populations can
reach a candidate via the local OSM pedestrian network. Style, guest spend,
customer audience, and daypart change the outputs. Cuisine remains in the
separate gap score. The assumptions are versioned and adjustable without
rebuilding routes. They have not been fitted to observed customer journeys.

The complete run uses 2,327 tract origins and all 1,000 synthetic properties.
The existing graph contains 1,972,718 nodes and 4,753,526 directed edges.
Routing-mass and source-feature coverage are sufficient for 994 properties;
four lack acceptable network matches and two have limited coverage.
After income coverage checks, price-adjusted percentiles are available for
986 cafe/lunch scenarios, 987 casual-dinner scenarios, and 988 premium-dinner
scenarios. Unavailable values are not converted into favorable zeroes.

For +/-20% changes in travel half-life, rank correlations are approximately
0.996-1.000 and top-50 retention ranges from 90% to 98% across the four profiles.
Cafe and office-lunch top-50 sets overlap in 42 properties, so the concept
changes some selections rather than merely relabeling the same surface.
These are sensitivity/engineering results, **not predictive validation**.
Staten Island has lower rated coverage: 43-45 of its 50 scenarios, depending on
concept, versus substantially higher proportions in the other boroughs.

We also exported 38 current-context feature candidates with a data dictionary,
coverage, domain checks, transforms, and redundancy review. No expected source
column is missing, and none of these features is constant. The subway activity
and nearby-complex-count features have a Spearman correlation of about 0.970;
they should be tested as alternatives before both are weighted independently.

The new context export uses the master's corrected area-allocated taxi density,
proper percentage/share units, historical event context, property-level vacancy
definition, and explicit missing bike observations. It does not alter the master
or silently replace inputs to an existing model artifact.

## Local Files to Share With the Team

Final run folder: `data/output/feature_engineering/20261027_v3/`.
It contains the four concept CSVs, current context features, feature dictionary,
route cache, input/code hashes, coverage, and sensitivity results. These files
are local research artifacts and are not being uploaded to GitHub.

Shared implementation: `codes/customer_access.py`,
`codes/customer_access_config.json`, `codes/engineer_customer_access.py`,
`codes/score_customer_access.py`, `codes/model_feature_catalog.py`,
`codes/test_customer_access.py`, `codes/requirements-access.txt`, and
`codes/CUSTOMER_ACCESS.md`.

The local recommender additionally accepts an optional access bundle and
experimental access weight. Its default remains zero, preserving the existing
60/40 ranking. This local adapter depends on the earlier uncommitted temporal
survival changes and is not part of the isolated feature-module publication.
The standalone module/API is usable without that adapter.

## What Is Not Finished

This is not a completed or optimized empirical survival model. The current
guarded trainer still needs dated baseline/operating/permanent-closure evidence
and historically available predictors. Current neighborhood observations,
this walking graph, and synthetic property characteristics cannot be backdated
into older restaurant cohorts. Snapshot disappearance remains an unverified
closure proxy, not independently verified exit.

The supplied slides/report describe the older 47-plus-3 retrospective model.
The guarded local trainer has a smaller historical feature contract. The report
and actual fitted artifact must identify which workflow is being evaluated;
we cannot combine their claims. Saved weights/CV outputs from Atharv's reported
run have not been present in the fetched main/branch heads checked today.

No new predictive-accuracy, fairness, revenue, or visit-forecast result is
claimed. Walking access does not yet include actual transit journey times,
all transport modes, calibrated travel willingness, or dish/dietary preferences.
Income-based affordability is an explicit area-level assumption, not a claim
about individual tastes or employee spending.

## Next Evaluation Sequence

1. Agree on the empirical target and evidence standard: verified permanent
   closure or explicitly labeled archive/permit persistence. Do not describe
   one as the other. Freeze the cohort, identity policy, and feature vintages.
2. Freeze development and final temporal/geographic holdouts before tuning.
   Test the general model against an intercept/prevalence or survival baseline,
   then feature-group ablations; do not use the test fold for early stopping.
3. Evaluate the access component separately from survival and cuisine gaps.
   Retain 60/40 as the baseline and test predeclared optional access weights.
   Report coverage exclusions and results by borough and missingness groups.
4. For survival, report comparable-pair concordance with uncertainty and
   censoring coverage. Assess three-year calibration only where follow-up and
   the censoring methodology support it. Sensitivity of rankings is not accuracy.
5. Lock the selected configuration, rerun the untouched final holdout once,
   and save artifacts, hashes, exclusions, limitations, and result tables for
   the week's report. Until evidence supports that run, retain the model guard.

## Source Priority

Primary: `Report 3 - Methods (7).docx`. Background: `Project Proposal Group 11 (3).docx`.
Chronological checks: Week 6, Week 7, Week 8, and Week 9 briefing copies supplied
on October 27. Older scraping/API workarounds were not implemented.
