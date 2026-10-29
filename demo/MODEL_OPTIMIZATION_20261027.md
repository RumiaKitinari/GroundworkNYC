# Model Optimization and Access Coverage

## Status

Completed locally on October 27, 2026. This is an offline research extension of
the frozen archive-AFT run, not a newly verified restaurant-survival model.
No frontend redesign, production-model promotion, dataset upload, or Git push
was performed. The previous frozen benchmark remains unchanged.

## Evaluation Protocol

- Parent: `data/output/research_runs/20261027_archive_aft_v2/`.
- Optimization: `data/output/optimization/20261027_v1/`.
- Replay validation: `data/output/optimization_validation/20261027_v1.json`.
- Deterministic neighborhood-group partition: 15,591 development restaurants
  and 3,269 reserved-assessment restaurants; no neighborhood crosses roles.
- Three grouped development folds; 12 fixed candidates from two feature
  policies and six tree-parameter configurations. Selection uses interval
  negative log likelihood, not assessment concordance.
- `selection_lock.json` records the chosen features and parameters before
  reserved outcomes are evaluated. Native models, predictions, source hashes,
  software versions, and split assignments are retained.

Every cohort restaurant appeared in earlier research cross-validation.
Consequently, the reserved partition is excluded from this optimization only;
it is **not a globally untouched final test**. Repeatedly selecting new models
using its results would invalidate even that narrower assessment role.

## Selected Research Candidate

The selected model uses 35 corrected current-context features, depth 3,
minimum child weight 25, L2 regularization 5, learning rate 0.03, and 200 rounds.
The eligible feature policies deliberately exclude opening year, full-archive
chain status, and reconstructed opening competition. The selected policy also
excludes three current food-service density measures. This reduces some
obvious temporal concerns but does not make the remaining current-context
variables historically valid.

Reserved-assessment results:

| Configuration | Concordance | Interval NLL |
| --- | ---: | ---: |
| Constant training-fitted AFT | 0.5000 | 0.868302 |
| Untuned 38-feature context baseline | 0.5612 | 0.863724 |
| Selected 35-feature candidate | 0.5693 | 0.863714 |
| Full 41-feature diagnostic, not eligible for selection | 0.5657 | 0.863357 |

Selected-minus-untuned paired concordance is +0.00810, with a neighborhood
bootstrap 95% interval of [-0.00926, +0.02347]. The interval includes zero and
the likelihood difference is tiny. This is not convincing evidence that
tuning improved generalizable predictive performance. Do not substitute the
diagnostic model merely because one assessment metric is more favorable.

The three-year Brier values describe only the resolved subset, not population
calibration or IPCW evaluation. Of 3,269 assessment records, 1,631 have unresolved
three-year outcomes. The later-opening development challenge contains no known
three-year survivors, so its resolved-subset calibration is especially
unrepresentative and must not be reported as a useful forecast assessment.

## Feature and Disappearance Diagnostics

On matched development folds, full-model concordance was 0.5495; removing
opening year gave 0.5500, removing chain status gave 0.5236, and removing both
gave 0.5270. Opening-year-only concordance was 0.4963; chain-only was 0.5267.
These are diagnostics, not causal estimates of feature value. Full-archive
chain counts require reconstruction using information available at opening
before inclusion in a historical model.

Requiring at least two later archive captures re-censored 714 of 3,782
development disappearance events; requiring three re-censored 940. The
predicted-duration ranking correlations with the primary rule were 0.9268 and
0.8937. Weak events were censored at their existing last-observed lower bound,
not declared to have survived until the latest archive. Capture opportunities
are inferred from consolidated archive endpoints, not independently verified
per-business closure observations. Lower likelihood losses across these
different targets are **not evidence of improved prediction accuracy**.

## Inverse Walkability and Huff Coverage

Final experiment: `data/output/access_optimization/20261027_v3/`.
Earlier incomplete/intermediate attempts remain separate and are not the
canonical result. Full inventory: 1,000 synthetic properties, 2,327 population
origins, and the pinned local OSM walking graph. No sampled-property shortcut
was used.

Forty-one competitor tract-centroid targets failed the existing 200-meter
road-snap limit. For ten of them, an active observed restaurant in the same
tract provides an anchor within 500 meters of the original centroid and within
200 meters of a walk-network node. These ten destination rows were re-routed
using directed network paths. Other targets, population origins, property
routes, walking thresholds, and the graph itself were not changed.

| Concept | Previously assessable | With audited anchors |
| --- | ---: | ---: |
| Neighborhood cafe | 602 | 742 |
| Office lunch | 575 | 704 |
| Casual dinner | 623 | 742 |
| Premium dinner | 578 | 853 |

Existing jointly assessable rankings were unchanged. The gain is additional
coverage, not independently verified accuracy. Competitors remain aggregated
within tracts; an observed anchor is not the exact location of every competing
restaurant. Thirty-one failed competitor targets remain unresolved; bad
population-origin snaps also remain unchanged.

The shared Huff coverage check now uses actual competitor-target coordinates
when deciding whether an unknown route might matter, rather than assuming all
destinations coincide with population centroids. Missing competitor routes
still withhold affected assessments instead of increasing apparent demand.
The repaired route artifact is offline and has not replaced live route caches.

## Sensitivity and Remaining Data Priorities

- Walking half-life +/-20%, outside-option strengths 0.5 and 2, and average
  check +/-20% were evaluated for all four concepts. Common-case rank
  correlations were approximately 0.978-1.000, with top-50 retention of 74-100%.
- A separate conservative scenario treats all 4,799 tract-matched uncertain
  cuisine labels as full competitors. Common-case rank correlations fall to
  0.499-0.804; top-50 retention ranges from 4% to 76%. This is a deliberately
  strong stress test, not inferred cuisine, a fitted parameter, or a confidence
  interval. Cuisine completeness is a material second-stage uncertainty.
- Another 788 active records have unmatched tract IDs and no usable NYC
  coordinates. They are exported for repair; no coordinates were invented.
- Neither access opportunities nor Huff shares are observed visits, restaurant
  revenue, or validated success probabilities. No weights were selected as
  optimal without observed consumer outcomes.

The next substantive improvements should be historical feature vintages,
opening-date chain reconstruction, independently checked closure evidence,
and high-impact cuisine/coordinate repairs. More hyperparameter searching is
not the main bottleneck shown by these experiments. A future independent
assessment cohort must be protected before further outcome-driven iteration.

## Reproduction and Verification

Use a new output directory for each run; existing experiments are never
overwritten. Run from the repository root:

```sh
.venv/bin/python codes/optimize_archive_model.py --source data/output/research_runs/20261027_archive_aft_v2 --output data/output/optimization/NEW_RUN
.venv/bin/python codes/validate_archive_optimization.py --run data/output/optimization/20261027_v1 --output data/output/optimization_validation/NEW_VALIDATION.json
.venv/bin/python codes/audit_access_optimization.py --output data/output/access_optimization/NEW_RUN
.venv/bin/python codes/validate_access_optimization.py --run data/output/access_optimization/20261027_v3
.venv/bin/python -m pytest codes demo -q
```

Verified all 225 frozen parent artifacts and 18 optimization artifacts; three
saved native models reproduce reserved predictions within 1e-6 tolerance.
Access validation checks 14 artifacts, all four full-inventory profiles,
anchor constraints, route identity order, choice-mass conservation, missing
scores, and the monotonic effect of added competition. The combined model and
dashboard suite passes 287 tests.
