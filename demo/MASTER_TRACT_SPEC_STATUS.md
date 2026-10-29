# Master Tract Feature Spec: Implementation Status

As of the October 20 completion release: 2,327 unique tracts and 249 documented columns. It is the current-context source of truth; current-year tract context must not be joined to a retrospective restaurant survival cohort. See `CURRENT_MASTER_COMPLETION.md` for the handoff and exact proxy limitations.

| Spec area | Current state | Remaining work |
| --- | --- | --- |
| Geography | 2,327 unique 2020 tract GEOIDs and boundary-sharing neighbors. Projected TLC crosswalk has 3,378 overlaps across 263 zones; 791 tracts overlap multiple zones. PLUTO property-ZIP crosswalk and dominant ZIP context added | Property ZIP is not a centroid ZIP or population crosswalk; ZIP business totals remain explicitly ZIP context |
| ACS | Thirteen complete national 2024 detailed summary tables downloaded through official bulk files without an API key. Adds age 20-34, poverty, per-capita income, household income bands, commuting, education, nativity, households, tenure, residential rent, unemployment, and household size. Estimates and margins retained separately | Suppressed/missing values remain blank, with original income and separate neighbor estimates preserved. A newer ACS vintage requires an explicitly versioned schema |
| Jobs | Full 2023 WAC workplace jobs plus RAC jobs by home block. RAC aggregates 30,850 NYC blocks into 3,769,974 jobs; workplace/home job ratio is allowed only for matching vintages | All-job counts can include more than one job per person; they are not a count of unique workers or daytime population |
| Access and movement | Full entrance inventory and complete MTA station week; nearby-complex counts, ridership and four period shares within 400 m. Full HVFHV month supports separately labeled area-allocated drop-offs and night/evening shares. Full historical permitted events produce past district-year context | Distances are straight-line centroid proxies; network sensitivity and multi-season coverage remain to be tested. Legacy TLC totals retain zone grain; area allocations are not observed tract trips; DOT monitors and district event totals are not tract-wide foot traffic |
| Property | Full PLUTO 26v2 with 854,596 coded lots now supplies all-lot commercial/mixed and vacant-land shares plus floor counts. DOF publishes 2024 occupied-rent medians for 1,330 tracts. Complete 2024 registry filings cover 29,834 distinct BBL parcels and 2,000 tracts | 2025 storefront records are vacancy-only so they cannot yield a vacancy rate. Multiple spaces share a BBL; `reported_storefront_vacancy_share` remains blank. Neither DOF median rent nor a vacancy filing is a current asking rent or a live lease listing |
| Restaurant market | Full OSM and DOHMH context. Complete 2015 and 2023 ZIP food-service extracts linked as dominant property-ZIP context, not tract counts. Full active SLA source supplies partial exact-address license matches and ages; Foursquare remains identity/outcome review evidence | Do not sum nested NAICS levels or treat ZIP context as tract establishments. Matched license zeros are not verified absence. Historical turnover and confirmed closures require further verification |
| Derived and neighbors | Original 21 fields plus current completion measures, explicit income/rent/walkability context and status, and twelve additional area-weighted neighbor means. Generic numeric units resolved | Add only ratios with defensible denominators and time-aligned inputs. Daytime population and true storefront vacancy remain unavailable. Do not use contemporary neighbor fields as historical predictors |
| Survival cohort | A pinned third-party DOHMH archive is downloaded privately; `build_restaurant_lifespans.py` reconstructed 67,790 interval-censored CAMIS records and 5,999 strict review candidates. Three dated four-feature predictor vintages are available by baseline | Verify business identity, actual operation at baseline, and one-year outcomes independently. Snapshot disappearance is not permanent closure; all candidates remain unresolved and excluded from training. The current master is not a historical training matrix |

The source files are retained. New releases are staged, schema-validated, score-audited, and atomically activated by `demo/refresh_integrated.py`. Run `--source pluto --source storefronts --publish` to rebuild the changed raw-source transforms and normalized tract context; any later refresh also recomputes the normalized context.

The absence of an inspection record is not closure evidence. A 2026-only feature must not explain a historical opening or outcome. Synthetic property scenarios are for interface and robustness testing, not observed survival labels.

The new source transforms are in `enrich_location_data.py` and participate in
`refresh_integrated.py` and monthly publisher checks. The source download uses
complete files, not samples. `features/tract_acs_context.csv` contains the new
demographic measures; `features/acs_context_estimates_and_margins.csv` retains
source estimates and margins as JSON records per tract/table. ZIP industry
context and the taxi-zone overlap crosswalk remain separate from tract counts.

The disappearance-label pilot is saved privately as
`data/evaluation/lifespans/disappearance_audit_20261020_v1_sample.csv`.
Twelve cases were selected with seed 440 from the 122 strict proxy negatives.
Search results contained identity and freshness conflicts, and no dated
permanent-closure event was established. Of the full 122 addresses, 91 have
another current restaurant listing at the same normalized address; a new tenant
does not establish continuity or date the prior tenant's closure. Queens
building-number normalization now finds 127 possible CAMIS changes across the
full 5,999-case review frame, up from 104. Use v5 adjudication for new review.
