# Cuisine / Price Scenario Audit

Separate offline scripts implement the requested 50-concept, three-price comparison without changing the dashboard, deployed model, or production model guards.

For teammates who only need the results, use the [portable handoff](../reports/2026-11-02-model-results/README.md). Its saved HTML, images and CSVs work without the private input bundles. `export_cuisine_handoff.py` builds that allowlisted copy from completed local runs and records checksums; it does not upload raw training data or models.

## What Is Being Called

- `batch_cuisine_scenarios.py` calls the existing location-screening implementation and the experimental walking-network Huff implementation. Both rankings are exported separately; no new blend or fitted weights are invented.
- The 50 categories match the existing project taxonomy, which includes specialties and formats as well as cuisines. Diner uses an explicitly unclassified screening fallback. Fourteen categories have no separate source classification; their source-support flags remain visible.
- Three existing guest-check anchors are used: `$` = $18, `$$` = $35, `$$$` = $65. They are not asking rents. Casual format, residents and all-day use are held fixed by default to isolate cuisine and price. These assumptions can be changed explicitly with CLI options.
- Every scenario assesses the complete pinned 1,000-property synthetic inventory before extracting five candidates. There are no rent, size, transaction or cuisine-specific format filters in this unconstrained benchmark.
- Unavailable scores remain missing. Ranking ties are resolved by property ID and cutoff tie counts are exported. Individual candidates are independent hypothetical entrants, not simultaneous new supply.

## Run Locally

From the repository root, choose new output directories for every run:

```sh
.venv/bin/python codes/batch_cuisine_scenarios.py --output data/output/background_tests/my_cuisine_batch
.venv/bin/python codes/verify_cuisine_batch.py data/output/background_tests/my_cuisine_batch
.venv/bin/python codes/render_cuisine_batch.py --batch data/output/background_tests/my_cuisine_batch --output data/output/background_tests/my_cuisine_maps
.venv/bin/python codes/stress_cuisine_competition.py --batch data/output/background_tests/my_cuisine_batch --output data/output/background_tests/my_competition_stress
.venv/bin/python -m unittest discover -s codes -p test_batch_cuisine_scenarios.py -v
```

The runner requires the existing private frozen October 27 research run, route bundles and competitor-anchor repair under `data/output/`. It verifies their manifests and identifier order. These large local inputs are not recreated or supplied merely by cloning the scripts from GitHub. Missing or modified inputs fail explicitly; no current-data or straight-line substitute is used.

## Optional Saved First-Stage Model

The trained dated-core AFT reference is an **archive-disappearance proxy**, not verified restaurant survival. It does not take cuisine or consumer price. Score each property once, then attach that invariant control to all 150 scenarios:

```sh
.venv/bin/python codes/attach_research_stage_one.py --batch data/output/background_tests/my_cuisine_batch --research-bundle data/output/background_tests/20261102_research_bundle_v1/bundle --output data/output/background_tests/my_stage_one_control --acknowledge archive_proxy_not_verified_survival
```

The guarded research runtime rebuilds its four dated predictors from pinned source snapshots and abstains if any are missing. Raw user-supplied feature values are not accepted. No first/second-stage combined score or production permission is created.

## Outputs And Interpretation

- `all_scores.csv.gz`: all 150,000 scenario/property rows, both ranking components and evidence flags.
- `top_selections.csv`: five selections per scenario per method, 1,500 rows at the default settings.
- `scenario_summary.csv`: scored/withheld coverage, source classification and ties.
- `price_sensitivity.csv`: adjacent-price rank correlations and top-five retention; 200 comparisons across the two methods.
- `selection_frequency.geojson`: H3 resolution-8 frequency cells generated directly from selected coordinates. Frequency counts distinct concept scenarios per cell, not duplicate properties within a scenario.
- `heatmaps.html`: self-contained interactive file; no keys, tile requests or web server required. Choose screening/Huff, concept and price.
- `selection_heatmaps.png`: six actual-data panels for a briefing. Presentation-only maps use eligible-tract context; it is not a surveyed shoreline. The two ranking methods have separately labeled color scales.
- `independent_checks.json`: full-inventory top-five recomputation, heatmap count verification, hashes and concentration diagnostics.
- Competition stress outputs compare the known-label baseline with counting all 4,799 weakly classified, tract-matched active restaurants as full competitors. This deliberately conservative assumption is tested separately for each cuisine; it is not an estimate of their actual cuisines or a confidence interval.

The heatmaps show recommendation behavior conditional on this inventory, these assumptions and these source versions. They do not validate visits, cuisine demand, profitability or permanent closures. The scripts are reproducible diagnostics, not evidence that model accuracy has increased.
