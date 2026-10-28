# Evidence and Fallback Policy

Implemented October 28, 2026. Policy: `evidence-policy-1.0`.
Screening version: `concept-screening-0.3`.

## Core Decision Hierarchy

1. Validate the input and supported geography. Invalid inputs are not silently
   converted into a different restaurant or location.
2. Assess general suitability using price positioning, service format,
   audience, trading period, activity, accessibility, and commercial context.
3. Determine whether the selected cuisine has sufficient observed supply
   evidence. Strong supply coverage does not establish customer demand.
4. When cuisine evidence is sparse, reduce its influence and retain the
   concept-specific general assessment. Do not replace a rare cuisine with a
   common one or infer preferences from ethnicity or income.
5. Use survival estimates only through the existing checked model loader.
   When no admissible model is available, remain on general screening. Never
   substitute archive disappearance predictions as verified survival.
6. Return the assessment basis, coverage, missing evidence, and required
   validation actions alongside the score.

This is an evidence-management solution, not a way to manufacture missing
training data. Lower specificity is preferable to unsupported precision.

## Cuisine Support

Every supported frontend cuisine key, including aliases and custom concepts,
has one of four explicit modes:

| Mode | Meaning | Scoring Behavior |
| --- | --- | --- |
| `cuisine_supply_supported` | Sufficient city, neighborhood, and local classified inventory | Cuisine supply context may contribute within the fixed component weights |
| `pooled_cuisine_supply` | Some exact-category observations, but limited support | Neighborhood supply is pooled toward city supply; influence is capped by observed support |
| `related_supply_context_only` | Exact source classification is unavailable but broader categories exist | Related categories are reported as context, never as selected-cuisine demand or a substitute score |
| `general_concept_suitability` | Cuisine is unspecified/custom or usable exact supply is absent | Format, price, audience, trading period, and area context remain active; cuisine-specific conclusions are withheld |

The supply calculation is transparent fixed-strength pooling:

```
city_share = city_same_cuisine / city_known_inventory
pooled_neighborhood_share =
    (neighborhood_same_cuisine + 20 * city_share)
    / (neighborhood_known_inventory + 20)
expected_local_supply = local_known_inventory * pooled_neighborhood_share
```

These are supply ratios, not estimated demand probabilities. The strength of
the cuisine contribution is bounded by city support, local inventory, and
label completeness. Unknown labels remain in the coverage denominator. The
existing neutral shrinkage and fixed overall component weights remain in
place; missing evidence does not receive redistributed full-strength weight.

The initial sufficient-support thresholds are 30 city records, five
neighborhood records, ten local classified records, and 70% local label
coverage. They are explicit engineering defaults, **not empirically calibrated
thresholds**. Change them through development-only sensitivity evaluation, not
by choosing whichever values produce appealing recommendations.

## Base-Case Matrix

| Case | System Response |
| --- | --- |
| Sparse exact cuisine | Pool observed supply and cap its influence; retain general concept fit |
| Cuisine not separately classified | Use general concept fit; report broader supply context separately |
| No recorded competitors | Do not claim proven demand or a profitable market gap |
| Many unknown labels | Lower evidence coverage; do not count unknowns as confirmed absence |
| Vegan or other dietary/cuisine combination | Keep dietary identity separate; no inferred dietary demand or certification |
| Affluent area without a cuisine | Separate affordability from supply; do not equate wealth with preferences |
| Missing income | Withhold affordability-dependent conclusions; retain supported context |
| Missing walking graph/cache | Withhold network-access/Huff outputs; retain separately labeled general accessibility |
| Unknown competitor routes | Withhold affected Huff scenarios, rather than zeroing competition |
| No verified survival model | Return screening, not fabricated survival probabilities |
| Partial model feature coverage | Expose coverage; retain screening when the fallback model contract is not satisfied |
| Custom or unsupported concept | Preserve the concept; expose unresolved classification and general-fit scope |
| Insufficient general measurements | Mark insufficient evidence; exclude from dashboard recommendations |
| Missing/nonpositive/nonfinite property price | Price is unavailable; budget eligibility is not established |
| Synthetic property | Scenario-only classification; no verified availability or return estimate |
| No hard-constraint match | Return no matching inventory; never silently increase budget or change transaction |
| Mixed or older source vintages | Retain existing source dates/provenance; do not backdate data or call it real-time |
| Conflicting business identity | Withhold transfer of cuisine/outcomes pending identity reconciliation |
| Unsupported geographic coordinate | Reject outside NYC tract boundaries, even if inside the coarse bounding box |
| Unstable scenario rankings | Preserve sensitivity results; do not select optimal weights without validation outcomes |

The catalog is served at `/api/assessment-policy`. Existing snapshot, historical
training, source-refresh, identity-review, and network-Huff safeguards continue
to enforce their respective contracts. The catalog documents those existing
guards as well as the new fallback behavior; it is not a claim that every
source or record has been independently verified.

## Model-Available Fallback

For policy-aware dashboard requests, a missing/unsupported cuisine surface can
use an experimental general-fit blend **only when the checked survival model
is available for every candidate in the batch**. Every candidate must have
at least 75% historical feature coverage and adequate general screening data.

The blend is 60% survival percentile and 40% concept-specific general screening
index. Those weights are not calibrated. The output is an experimental ranking,
not a success probability, demand forecast, or property-level prediction.
The same basis is applied to the whole candidate batch to avoid mixing score
definitions. If any candidate fails the contract, the batch retains screening.

No admissible survival artifact is currently active locally, so this path has
been tested with controlled fixtures but is **not supplying live survival
predictions**. Existing research proxy models remain offline.

## API and Display Contracts

- Each location carries `assessment_policy` and
  `concept_evidence.support`, including its mode and required actions.
- `survival_basis` distinguishes unavailable survival from a separate
  experimental model estimate. Cuisine demand is never marked verified.
- Properties carry an independent policy for transaction-specific budget
  evidence, synthetic status, availability, and facilities confirmation.
- `property_search.constraints_relaxed` remains false. Source listings are
  not labeled independently verified live inventory merely because published.
- Hex outputs use the shared screening model and expose their screening basis
  and minimum-coverage eligibility. They remain area-level estimates.
- The frontend design is unchanged; the experimental model status label
  recognizes both the cuisine-supply and general-fit ranking modes.
- Zero-coverage cuisine values display as `Unavailable` in the ranking table
  and report, rather than displaying the neutral internal shrinkage anchor as
  measured evidence. A general-fit model summary does not display a fake
  zero-valued cuisine-gap component.

The minimum overall screening coverage is 35%. Coverage is evidence
availability, not statistical confidence. An unmeasured score's neutral anchor
must not be presented as an evidence-backed recommendation.

## Verification

The full concept audit evaluates 62 supported cuisine keys across three formats
and 2,243 eligible tracts: **417,198 assessments**. The package is saved at
`data/output/evidence_policy/20261028_v2/`, with code snapshots, policy settings,
source hash, mode counts, coverage statuses, and score ranges. All checks are
non-training checks; they do not establish predictive accuracy.

Live API smoke tests cover a sparse-cuisine counter-service concept, the same
cuisine in fine dining, vegan Mexican, purchase-only Korean, and a custom
concept. Sparse-cuisine top scores differ by format/price (76 vs. 70 in the
checked requests), while both remain explicitly general-fit screening.
Initial Chrome and WebKit desktop/mobile checks passed without page errors or
horizontal overflow. Sources and frozen model outputs were not overwritten.
The model/dashboard Python suite passes 316 tests, including missing and
nonfinite prices, invalid model coverage, sparse and unsupported cuisines,
unknown labels, dietary identity, model fallback, and geographic rejection.

Re-run with a new output directory:

```sh
.venv/bin/python demo/audit_evidence_policy.py --output data/output/evidence_policy/NEW_RUN
.venv/bin/python -m pytest codes demo -q
```

The main next empirical tasks remain independent outcome verification,
high-impact cuisine review, and consumer/visit observations for validating the
second stage. This policy makes behavior consistent while those gaps remain;
it does not remove the gaps themselves.
