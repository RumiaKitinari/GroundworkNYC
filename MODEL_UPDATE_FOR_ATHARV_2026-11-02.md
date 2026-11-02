# Model Results Update - November 2

## Portable Team Copy

Start with [the exported results and heatmap instructions](reports/2026-11-02-model-results/README.md).
The HTML viewer, image, all scenario scores, selections and aggregate first-stage evaluation are included on this branch. Download the branch and open `reports/2026-11-02-model-results/maps/heatmaps.html`; no local training datasets or running dashboard are required to view it.

## Copyable Update

I completed the separate cuisine/price runner you requested: 50 restaurant concepts at $18, $35 and $65 per guest, each assessed against the full 1,000-property synthetic inventory. It saves all 150,000 scenario/property results, the top five for each scenario, and interactive H3 heatmaps. Screening and experimental walking-Huff rankings are shown separately rather than silently combining them with new weights.

The tests show that price changes the top-five recommendations in 85 of 100 adjacent-price screening comparisons and 86 of 100 Huff comparisons. Screening selects 42 distinct properties across the whole scenario grid; Huff selects 117. This tells us how differentiated the recommendations actually are, rather than assuming that different inputs must produce different locations.

The saved first-stage model was also scored separately and attached as a research-only control. It has the required dated features for 996 of 1,000 properties; four remain unscored. Its predictions do not change with cuisine or guest price because those are second-stage inputs, not first-stage predictors.

The important remaining weakness is evidence quality, not just hyperparameters. Fourteen of our 50 concept categories have no separate source classification. In a conservative test that treats weakly classified establishments as potential full competitors, all 50 cuisines changed at least one top-five Huff selection. This is an extreme assumption, not their actual cuisine assignment, but it shows why unknown supply must not be interpreted as an empty market. Recommendations should retain their fallback and coverage warnings.

The existing first-stage result remains approximately 0.545 concordance on 2,234 reserved restaurants; the conditional neighborhood-bootstrap interval is 0.487-0.584. Capped walkability and wider training did not demonstrate an improvement. These are archive-disappearance proxy results, not verified permanent-closure survival, and the reserved records had earlier project exposure. We should not describe tonight's scenario outputs as improved survival accuracy. The next material improvement requires verified business episodes/outcomes and a new point-in-time evaluation, alongside better competition-label coverage.

All calculations were conducted locally. The scripts and an allowlisted portable results handoff are being shared on Otis's branch. No dashboard changes, deployment or production model replacement were made; main is not part of this push.

## Where To Look

Repository scripts:

- `codes/batch_cuisine_scenarios.py`: all concepts / three tiers; full-inventory screening and Huff calls.
- `codes/attach_research_stage_one.py`: saved first-stage model outputs attached without changing the second-stage rankings.
- `codes/verify_cuisine_batch.py`: independent recomputation of ranks, coverage and heatmap counts.
- `codes/stress_cuisine_competition.py`: uncertain-competitor sensitivity.
- `codes/render_cuisine_batch.py`: presentation-only maps with eligible-tract context.
- `codes/CUISINE_BATCH.md`: exact commands, dependencies and interpretation.

Authoritative local outputs:

- `data/output/background_tests/20261102_cuisine_price_batch_v3/`: completed scenario grid, selections, source/implementation hashes and independent checks. Earlier v1 failed rendering; v2 is superseded cartography.
- `data/output/background_tests/20261102_cuisine_batch_maps_v1/`: briefing PNG and standalone interactive HTML. Scores and selections are unchanged from v3.
- `data/output/background_tests/20261102_cuisine_stage_one_v1/`: saved AFT control, provenance and scenario join.
- `data/output/background_tests/20261102_cuisine_competition_stress_v2/`: conservative competition stress against the final v3 grid.
- `data/output/background_tests/20261102_cuisine_price_batch_qa/`: browser checks and desktop/mobile screenshots.
- `data/output/background_tests/20261101_locked_results_v1/RESULTS_AND_HANDOFF.md`: frozen first-stage results and uncertainty.
- `data/output/background_tests/20261102_research_bundle_v1/FINALIZATION_STATUS.md`: remaining scientific limitations and promotion decision.

The paths above document the original local runs; those entire private directories are not in Git. The [portable handoff](reports/2026-11-02-model-results/README.md) includes the generated scenario results and aggregate evaluation needed for review. Rerunning calculations, unlike viewing those saved results, requires the pinned data/route/model bundles described in the README. Do not substitute today's master into a frozen comparison.

## Checks And Boundaries

Seven focused unit tests passed. The final scenario audit independently checked 300 scenario/method rankings and 241 frequency cells. Browser checks exercised all 300 concept/tier/method combinations at desktop and mobile sizes, without page errors, external requests or horizontal overflow. Choice-share conservation, monotonic affordability response, missing-score handling and deterministic ties were checked.

Screening assessed all 1,000 candidates. Huff coverage varied by cuisine, with at least 705 assessable candidates; incomplete routes or mass coverage are withheld rather than filled with zero. Current-context walking/Huff scenarios must not be reused as opening-time historical predictors. Synthetic property outcomes must not be used as training labels.

The price anchors are hypothetical guest checks. Format, resident audience and all-day activity are held fixed. This benchmark applies no rent/size/transaction filter. Heatmap frequency is conditional on the generated property inventory and scenario grid; empty cells do not demonstrate low demand. Raw Huff opportunity mass is not a visits or revenue forecast. No combined calibrated two-stage model was validated by this work.
