# Concept Screening v0.2

This is an interpretable screening baseline, not a trained demand model. Its
indices have not been validated against visits, conversion, sales or closures.
Scores are not success probabilities. Evidence strength is not model accuracy.

## Inputs and scope

The master tract table remains primary. `entities/current_restaurants.csv` adds
active, deduplicated CAMIS records with cuisine labels. We do not combine these
counts with OSM records because a cross-source establishment identity match is
not available. Cuisine comparisons use the tract, with NTA counts as broader
context. The benchmark includes the eligible NYC tracts used by the demo;
Staten Island remains excluded by the existing eligibility filter.

The brief specifies cuisine, format, service style, either a price tier or an
average spend per guest, dietary identity, customer focus, and trading period.
Tier mode uses a fixed planning assumption of $18, $35, $65, or $110 for
$, $$, $$$, or $$$$ respectively; it is not a user-entered exact price. The restaurant
name and description can identify supported cuisine and dietary keywords when
those structured fields are left unspecified. Other free text is retained but
does not change the score.
Ethnicity and nationality are not inputs. The integrated demographic table has
population, age totals, income, and income uncertainty; it contains no measured
cultural preferences. Existing cuisine supply is context, not proof of demand.

## Walkability and business draw

Walkability rescales the EPA National Walkability Index from 1-20 to 0-100:
`100 * (index - 1) / 19`. It is a built-environment indicator and does not change
when a user changes the concept. Missing values are reported as unavailable.
The package aggregates EPA block groups to tracts.

Business Draw is the initial implementation of the project's "inverse
walkability" idea. It is not a mathematical reciprocal. It combines demand,
customer fit, access, cuisine opportunity and competitive balance, using the
existing format-specific weights normalized without commercial suitability.
The overall location score also includes commercial suitability.

Numeric peer comparisons use empirical midrank percentiles with ties. Zero
counts receive zero, missing measurements are neutral with zero evidence.
Each aggregation shrinks weak evidence toward neutral and propagates weighted
evidence strength. This conservative rule is an assumption to validate.

- Demand: residents, jobs, subway activity, monitored pedestrian counts and
  evening cycling. Worker/lunch/morning briefs emphasize jobs. Evening briefs
  emphasize evening cycling, a partial proxy rather than footfall.
- Customer fit: audience density and affordability. Affordability uses the
  explicit heuristic `min(100, 65 * median_income / (average_check * 2000))`.
  Fine dining gives it more weight. This is not willingness-to-pay research.
  Income evidence is reduced by the ACS margin of error.
- Access: EPA walkability plus subway distance. Destination/fine-dining briefs
  place more weight on subway access. Distance uses `100/(1+(miles/.35)^2)`.
- Cuisine opportunity: compare the recorded count to labeled tract inventory
  times citywide cuisine share. A two-establishment prior shrinks small samples.
  Scarcity is multiplied by the weaker of demand and customer fit. Cuisine
  evidence uses the labeled fraction and a ten-record inventory threshold.
  Unknown cuisine never counts as verified absence.
  The cuisine-opportunity factor uses the stronger of this gap route and an
  established-ecosystem route: NTA cuisine share relative to the city, shrunk
  below five same-cuisine records and gated by the same demand/spending fit.
  An existing cluster can therefore support an opportunity without being called
  a gap. Neither route measures customers' cuisine preferences.
- Competitive balance: demand relative to format-specific OSM competition.
- Commercial suitability: retail area, mixed-use parcels and storefront records.
  It does not establish zoning eligibility, lease availability or affordability.

Pedestrian evidence decays as `1/(1+(distance_miles/.25)^2)`. Subway activity is
distance-adjusted and discounted because it covers only one observed week.
Cycling evidence is discounted for mode and geographic coverage. These decay
constants, spending assumptions, sample thresholds and weights are provisional.
For geocoded property leads, a separate 10-minute catchment follows a locally
extracted OSM pedestrian graph at an assumed 80 meters per minute. It reports
reachable active restaurants and subway complexes from the integrated entities;
it does not modify the unvalidated tract score or estimate actual pedestrians.
Missing graph coverage is reported as unavailable.

## Interpretation

"Potential Cuisine Gap" requires sufficient labeled inventory, demand and
customer fit of at least 65, and fewer recorded establishments than the cuisine
benchmark. "Established Cuisine Market" requires at least three same-cuisine
NTA records and an NTA share at least 1.25 times the city benchmark. Neither
designation implies ethnic affinity, verified customer demand or exclusivity.

Vegan and vegetarian identities use the current DOHMH cuisine labels as a weak
supply signal. Their scarcity signal has 70% of the cuisine-opportunity mix; the
selected cuisine has 30%. Because the data lacks measured dietary demand, the
dietary supply signal is heavily discounted and a review flag is added. Halal,
kosher, and gluten-free are retained as concept details but currently have no
separate demand or supply score. The effective average spend, whether explicitly
entered or derived from the tier, drives the affordability heuristic. Format changes
the component weights and competition proxy. These are screening assumptions,
not learned coefficients.

The Budget tab is separate from this model. Its required monthly sales equal
`(rent target + user-entered other fixed costs) / (1 - user-entered variable
cost fraction)`. Required daily covers divide that target by guest spend and
user-entered operating days, rounded up. No result is produced without all
cost inputs. It excludes costs not entered, taxes, debt service, and any claim
of profitability.

## Validation and next model

Run `python -m unittest discover -s demo -p 'test_*.py'` from the project root.
These tests verify behavior and missing-data handling, not predictive accuracy.

To estimate visits, collect dated store openings, outcomes, visits or sales,
hours, capacity, prices, exact storefront coordinates and competitive locations.
Use the new pedestrian-network catchments to estimate attractiveness/distance effects
using a calibrated spatial-choice model such as Huff. Split validation by time
and neighborhood to prevent leakage; compare against demand-only and
walkability-only baselines. Report errors, calibration, uncertainty and
performance by borough/concept before displaying customer forecasts.

References:
- EPA National Walkability Index: https://www.epa.gov/smartgrowth/national-walkability-index-user-guide-and-methodology
- EPA scale and database: https://www.epa.gov/smartgrowth/smart-location-mapping
- Spatial choice and calibration: https://pro.arcgis.com/en/pro-app/3.5/help/analysis/business-analyst/huff-model-overview.htm
