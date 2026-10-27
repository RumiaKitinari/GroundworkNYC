# Customer Access and Model Feature Engineering

This module adds the walking component of Groundwork's proposed inverse
walkability measure. It measures access **to a candidate business** from nearby
resident and workplace origins. It is not the reciprocal of the EPA index,
observed pedestrian activity, a full transport model, or a visit forecast.

The implementation follows the customer-access distinction in the latest
Methods Report. Cuisine remains separate: it belongs to the cuisine-gap model,
not the general survival predictor or this walking-access calculation.

## Calculation

For origin tract `o`, candidate `j`, and concept `c`:

```text
t_oj = (origin connector + shortest walking path + site connector) / 80
k_oj = 2 ** (-t_oj / half_life_c), for t_oj <= 30 minutes; otherwise 0
resident_fit_oc = min(1, median_household_income_o / (2000 * average_check_c))
access_jc = sum_o k_oj * (resident_weight_c * residents_o + worker_weight_c * jobs_o)
price_access_jc = sum_o k_oj * (resident_weight_c * resident_fit_oc * residents_o
                               + worker_weight_c * jobs_o)
```

Style half-lives are 5, 10, and 15 minutes for quick service, casual dining, and
fine dining. Audience and daypart parameters are explicit in
`customer_access_config.json`. These are hypotheses for sensitivity testing,
not measured travel preferences or fitted behavioral parameters. Household
income adjusts only the resident component; worker spending is not inferred
from neighborhood residents' income. Missing resident income is documented
through separate price coverage, not filled with a favorable value.

Both raw outputs are **weighted opportunity units**, not unique people,
customers, transactions, or demand predictions. An employee may also be a
resident, so the two populations cannot be interpreted as unique visitors.
Percentiles compare the complete pinned candidate inventory for each concept.
Filtering the properties afterward does not renormalize the access percentiles.
Raw levels should be inspected when comparing different concepts.

## Routing and Coverage

The implementation uses the existing private OSM SQLite graph. It preserves
directed edges and reverses routing from each destination to obtain
origin-to-destination paths. Dijkstra searches are bounded to 2,400 meters.
Only one full-node distance vector is allocated per search, and the resulting
candidate-by-tract matrix is saved for reuse across concepts.

Origin and destination connectors are included. A point farther than 200 meters
from the network is unavailable, not snapped arbitrarily. Infinity represents a
known no-path/over-budget result; NaN means the route could not be evaluated.
Neither can be substituted for the other. There is no silent straight-line
routing fallback. Connectors and tract-centroid origins are approximations;
they cannot establish storefront entrances or every physical barrier.

The output reports routing-mass coverage, origin-count coverage, resident price
coverage, source-feature coverage, and reachable origin tracts. Ranking requires
at least 70% routing and source-feature coverage. Price-adjusted ranking also
requires 70% resident price coverage. The thresholds are explicit assumptions.
Route coverage does not establish population representativeness or a confidence
interval. It is assessed over origins within the maximum straight-line screen.

Transit ridership, cycling, driving, restaurant quality, dietary demand, and
competition are not mixed into walking-access opportunity units. They remain
separate context or competition features. A full inverse-access measure still
needs transit journey times, additional travel modes, and behavioral calibration.

## Inputs and Outputs

Inputs are the full integrated tract master, the 1,000-property synthetic
inventory, and the existing local pedestrian network. No Google/Yelp collection,
individual-level records, synthetic closure labels, or new source download is
required. Tract counts are allocated to their centroid origin, not to invented
household points. The graph's hash is recorded; historical availability is not
claimed for the graph.

Each run preserves hashes, configuration, software versions, source paths,
matrix identifier order, feature dictionaries, coverage, and sensitivity results.
Existing outputs are never overwritten. Generated files remain local under
ignored `data/output/`; they must not be committed as training outcomes.

The run also exports 38 current-context features in `current_context_features.csv`
with explicit transformations and missing-value rules. It uses existing
area-allocated TLC density, separates percentages from fractional shares, keeps
monitor distance beside pedestrian counts, retains missing bike observations,
uses past-year district event context, and does not mislabel property vacancy as
a storefront vacancy rate. `feature_dictionary.csv` and `feature_audit.json`
show coverage, invalid observations, constants, and high correlation pairs.

These are prospective feature candidates, **not** a replacement historical
survival training matrix. The dated AFT feature allowlist and outcome evidence
requirements are unchanged. Current OSM supply and synthetic property attributes
must not be inserted into opening-time survival features.

## Commands

From the repository root, in a compatible environment:

```sh
python -m pip install -r codes/requirements-access.txt
python -m unittest discover -s codes -p test_customer_access.py -v

python codes/engineer_customer_access.py \
  --master data/integrated/current/master_tract_features.csv \
  --listings data/listings/synthetic_properties.csv \
  --network data/osm/nyc_walk_network.sqlite \
  --output data/output/feature_engineering/NEW_RUN

python codes/score_customer_access.py \
  --access-run data/output/feature_engineering/NEW_RUN \
  --service-style quick_service --price-tier '$' \
  --audience workers --daypart lunch \
  --output data/output/feature_engineering/NEW_CONCEPT.csv
```

An exact `--average-check` can replace `--price-tier`. The dollar tiers assume
$18, $35, $65, and $110 per guest. No cuisine is needed for this component.
Repeat a build with `--reuse-routes PREVIOUS_RUN` to change concept assumptions
without rerouting. Source and route hashes and routing parameters must match.

For integration into a recommender, call:

```python
from customer_access import AccessConcept, score_cached_run

access = score_cached_run(run_directory, AccessConcept(
    service_style="casual", average_check=35, audience="residents", daypart="evening"
), eligible_properties, prediction_date="2026-10-27")
```

This returns features aligned to the eligible property index, but calculates
their percentiles against the full pinned inventory. It refuses changed inputs,
coordinates, tract associations, route ordering, backdated use, and altered
route bytes. Pin the input release rather than redirecting its absolute paths
to files with different bytes. The existing 60/40 survival/cuisine-gap ranking
should remain the baseline until a separate access ablation is evaluated.

## Evaluation Scope

The validation export tests distance sanity, full-inventory coverage, monotonic
responses to price and travel decay, and rank sensitivity to 20% changes in
walking half-life. The unit tests exercise directed routes, disconnected
components, missing measurements, price/style/audience/daypart changes, units,
repeatability, cache tampering, and fixed-inventory normalization.

These checks do not establish restaurant survival accuracy or calibrated
customer demand. No empirical survival model is trained by these commands.
Future work must evaluate incremental value against a predeclared baseline and
holdout; parameter tuning must not reuse the final test outcomes.

## Methodological References

- [EPA Smart Location Mapping](https://www.epa.gov/smartgrowth/smart-location-mapping)
  describes built-environment and accessibility measures; it does not validate
  Groundwork's concept-specific weights.
- [Esri Huff model documentation](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/business-analyst/understanding-huff-model.html)
  motivates origin-destination distance decay and the need for calibration.
  This access feature is not a calibrated Huff choice model.
- [SciPy Dijkstra documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html)
  specifies directed shortest paths and bounded searches used here.
