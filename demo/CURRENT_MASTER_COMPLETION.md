# Current Master Completion

October 20, 2026 (America/New_York).

## What Is Finished

The current-context release contains 2,327 unique 2020 census tracts and 249
documented columns. It preserves observed source values and adds explicitly
named estimates, allocations, coverage metadata, and neighboring-tract measures.
It is not a verified restaurant-survival label file.

New work beyond the earlier 193-column release:

| Area | Implementation | Interpretation |
| --- | --- | --- |
| Employment and households | Complete national ACS B23025 and B25010 added to the thirteen-table 2024 bundle | Unemployment uses civilian labor force as denominator; household size is published, not population divided by households |
| Commercial rent | Published medians retained; separate missingness reasons and local rent estimates | 1,330 reported medians, 93 publisher star markers, 904 absent source tracts. No blank reported rent is changed to zero |
| Estimate validation | Borough-median versus five-nearest same-borough log-distance-weighted rent, five NTA-disjoint folds | Selected local method: median absolute percentage error 23.94%, versus 27.67% for borough median; missing-tract representativeness and final independent validation remain unproven |
| Income and walkability | Separate published-or-neighbor context fields, with status columns | Observed values are unchanged; isolated missing tracts are not invented |
| Rideshare | Full August 2026 HVFHV source grouped by destination zone and time; all polygon overlaps used | Uniform-area allocation with covered-zone conservation checks, not observed tract drop-offs |
| Nearby subway | Unique station complexes within 400 meters, entries and four time-window shares | All 168 hours, no entrance double-counting; straight-line centroid proximity, not walking-network routes |
| Built environment | EPA D3B and D4C crosswalked by projected polygon overlap | Source-era weighted intersection density and transit frequency, not contemporary surveys |
| ZIP industry context | Full 2015 ZIP Business Patterns download and exact NAICS-722 comparison with 2023 | Dominant ZIP from PLUTO property counts; ZIP totals are not allocated as tract establishments |
| Liquor license context | Complete statewide active-license download, NYC restaurant/hospitality categories and exact local address matching | Partial matched counts and license ages, not all on-premises licenses or restaurant ages; ambiguous addresses remain unmatched |
| Past events | Complete official historical permitted-event export, district-year deduplication | Past-year district exposure separate from upcoming events; no fabricated tract attendance |
| Neighbor context | Twelve area-weighted means across boundary-sharing tracts | Includes rent, income, jobs, access, commercial surroundings and property-vacancy proxy; never a fold-leaking turnover target |
| Metadata and publication | Generic numeric units resolved; structural, numeric, denominator, rent and consistency checks before atomic release activation | Original source files, earlier releases and teammate changes preserved |

The local rent estimate is a current **area-context** estimate. It must not be
shown as an individual property's verified asking rent or substituted for
dated rent when evaluating a historical survival model.

## Workarounds and Boundaries

The requested specification is implemented where the underlying data supports
it. The following substitutions deliberately do not claim equivalence:

- Property ZIP replaces an unavailable exact centroid ZIP join only as a named
  proxy. Its tax-lot dominance share is included. No tract-ZIP population or
  area allocation is inferred from postal property addresses.
- A registered-property vacancy share is supplied, not a storefront vacancy
  rate. The source can identify BBL properties with vacant spaces but not a
  reliable count of all individual spaces.
- Commercial rent estimates fill a separate context column, not published
  values. Dollar-per-square-foot units are explicit and annual conversions checked.
- Matched license density is a lower-bound match inventory, not verified full
  tract license coverage. Zero matches is not verified absence.
- Transit and event windows describe available source periods. One subway
  week and one Citi Bike month remain seasonally limited.
- No `residents + all jobs - home-area jobs` daytime population is fabricated:
  jobs are not unique people. Ratios requiring that denominator are not supplied.
- Residential rent is never substituted for commercial rent, and synthetic
  property scenarios are never substituted for observed market records.

## What Still Blocks Genuine Survival Training

The existing 5,999-record candidate frame remains unlabeled. Four historical
predictors can be selected as-of-date for 3,486 candidate inspection baselines,
but an inspection lead is not a verified opening date. Snapshot disappearance
does not establish a permanent closure or its date. Changed CAMIS values,
relocations, transfers and missed coverage must be reconciled first.

There is no defensible cleaning operation that manufactures those facts.
The available choices are independently documented historical outcomes or an
explicitly different research target such as archive reobservation. The latter
has already been tested as a weak pipeline proxy and must not be advertised as
restaurant survival or profitability. Synthetic leasing records cannot supply
restaurant outcomes either.

The 249-column current master is not a set of 249 historically available
predictors. Historical training is default-deny except for verified dated
snapshots. Outcome-derived turnover, opening-time competition, chain indicators,
income weighting and neighbor outcomes must be constructed within the dated
cohort and training folds, not from today's survivors.

Ancestry/origin-based cuisine preferences, live listings, true storefront
vacancy, unique daytime population, network catchments and multi-season
mobility remain separate enhancements or unavailable observations. No false
values are introduced just to satisfy column names in the proposal.

## Use and Reproduce

Primary data: `data/integrated/current/master_tract_features.csv`.
Units: `data/integrated/current/data_dictionary.csv`.
Source-specific dates: `data/integrated/current/source_catalog.csv`.
Rent method errors and allocation checks:
`data/integrated/current/master_completion_validation.json`.

```bash
.venv/bin/python demo/download_sources.py --source acs_context --source business_patterns_2015 --source sla_active_context --source events_historical
.venv/bin/python demo/refresh_integrated.py --source acs_context --source business_patterns_2015 --source sla_active_context --source events_historical --publish
.venv/bin/python demo/maintain_data.py --audit
.venv/bin/python demo/audit_training_data.py
.venv/bin/python -m unittest discover -s demo -p 'test_*.py'
.venv/bin/python demo/export_current_master.py --destination /Users/otismurray/Desktop/Groundwork_Current_Master_2026-10-20
```

The export creates one small checksummed folder and ZIP with the master,
dictionary, sources, quality/rent reports, and explicit training restrictions.
Raw datasets remain local; the export never overwrites an existing handoff.
No frontend work or GitHub upload is part of this data completion.

Official historical event source:
[NYC Permitted Event Information - Historical](https://data.cityofnewyork.us/City-Government/NYC-Permitted-Event-Information-Historical/bkfu-528j).
The complete export is checked against publisher row count and stable version,
with gzip transfer integrity checked before activation.
