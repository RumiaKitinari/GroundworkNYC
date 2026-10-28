# Model and Feature Evaluation

## Scope

Keep three outputs distinct: historical restaurant survival, prospective network
customer access, and cuisine-specific competition/Huff scenarios. Current access
and synthetic property features do not enter historical survival training.

`evaluate_model_features.py` evaluates the complete pinned scenario inventory,
not a sample. It verifies both route manifests, source hashes, coordinate/ID
order, consistent origins, identical network/settings, and prospective dates.
It never overwrites an earlier run or modifies the integrated master.

```bash
.venv/bin/python codes/evaluate_model_features.py \
  --property-run data/output/feature_engineering/20261027_v3 \
  --tract-run data/output/customer_access_dashboard/20261027_v1/tracts \
  --output data/output/model_evaluation/NEW_RUN
```

The default restaurant input comes from the property's pinned integrated release,
not whichever release happens to be current later. Explicit alternative inputs
can be passed with `--restaurants` and are identified by path/hash. Such an
alternative is a different present-day scenario, not a historical backtest.

## Access Ablations

For cafe, office lunch, casual dinner and premium dinner scenarios, compare full
access with no affordability adjustment, no worker component, no resident
component, no distance decay within the fixed catchment, EPA walkability only,
local population only, and local jobs only. Missing/insufficiently covered access
is not promoted into the comparison. Report common-case coverage, rank
correlation and top-50 retention. Low retention means a changed ranking, not
improved accuracy. Equal scores use stable input order, so top-50 ties should not
be interpreted as strong evidence.

## Experimental Network Huff

The existing backend H3 Huff tool remains unchanged. `network_huff.py` adds an
offline network variant using cached walking routes:

`P(candidate | origin) = candidate utility / (candidate + existing utilities + outside utility)`.

Utility uses exponential walking decay with the existing style-specific
half-life. Candidate attractiveness is fixed to one. Existing establishments
are counted at tract centroids and weighted by the existing 50-cuisine
substitution matrix. This is a generalized, uncalibrated Huff-style scenario,
not the classical distance-power calibration or measured consumer choice.
Resident opportunity mass uses the existing income/spend assumption; workplace
mass has no invented employee income. Every synthetic entrant is a separate
counterfactual; candidates do not compete with each other as though all open.

The outside option allows trips to other destinations or no captured restaurant
trip. Candidate, existing and outside shares sum to one for each origin/scenario.
This mathematical check does not establish that the probabilities match real
behavior. Jobs and residents are opportunity units, not disjoint observed diners.

Direct/keyword cuisine labels are rule-based. Weak/default/unknown labels and
unmatched tracts are audited and excluded, not assigned confident cuisines.
Unknown nearby competitor routes withhold affected scores instead of improving
a candidate's apparent market position. The original supply-gap baseline is
reproduced separately with its original cuisine defaults and NYC coordinate
filter; its population therefore differs from the stricter Huff scenario.

The run exports coverage by borough, cuisine provenance, four scenario tables,
access ablations, supply-gap/Huff ranking differences, and outside-option
sensitivity at 0.5 and 2.0. It leaves survival and the 60/40 combined score missing
without a validated empirical survival artifact. No uncalibrated Huff output is
automatically deployed or presented as visits, sales, success or survival.

## Survival Evaluation

See `TEMPORAL_SURVIVAL.md` and `model_evaluation_plan.json`. The trainer now saves
training-only constant-AFT baselines, interval likelihood, interval-order
concordance, conditional NTA-bootstrap uncertainty, fixed feature ablations and
explicitly limited resolved-outcome calibration. The independently verified
opening/operation/closure evidence gate remains active.

## Method References

- [Esri: How Huff Model Works](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/business-analyst/understanding-huff-model.html): distance, attractiveness and competing sites; empirical calibration is separate.
- [scikit-survival: Evaluating Survival Models](https://scikit-survival.readthedocs.io/en/stable/user_guide/evaluating-survival-models.html): discrimination versus calibration and censoring limitations. Its right-censoring IPCW metrics are not silently substituted for our interval-censored outcomes.
