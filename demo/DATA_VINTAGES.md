# Groundwork Data Vintages

Audited October 20, 2026. The completed 2020-tract master has 2,327 rows and 249 documented columns. These are the **observation periods**, not the date a file was downloaded. The machine-readable audit is `data/training_inventory.json`; the active release's `source_catalog.csv` and `refresh_manifest.json` pin its inputs.

| Signal | Active observation period | Refresh and limitation |
| --- | --- | --- |
| Population, age, income, social and housing context | 2020-2024 ACS five-year | Monthly check of thirteen official bulk tables; no API key needed for this route. Full national source files and NYC estimates/margins retained, including unemployment and household size. Not a 2024 point-in-time count. |
| Workplace jobs | 2023 LODES WAC | Monthly check; full New York workplace blocks are automatically aggregated to NYC 2020 tracts. |
| Residence-area jobs | 2023 LODES RAC | Monthly check and complete New York download; jobs by home block, not unique employed residents. |
| Subway entries and time patterns | Complete week of September 28, 2026 | Weekly check and automatic rebuild. One week is not typical annual ridership. |
| Subway entrances | MTA 2024 inventory | Monthly publisher check; unique entry-allowed coordinates and 400-meter centroid proximity. |
| Taxi-zone geometry | Current official TLC file, publisher modified February 2026 | Monthly check; projected tract/zone overlap with both area fractions. Separate area-allocated trip proxies are labeled, not observed tract trips. |
| Citi Bike departures | September 2026 | Monthly check and automatic rebuild from the full monthly trip archive. August 2026 columns remain historical. |
| HVFHV taxi activity | August 2026 | Monthly check and automatic rebuild from the full trip file. Legacy zone context is retained; `rideshare_*` supplies area-allocated drop-offs and time shares with covered-zone conservation checks. |
| Restaurant inspections | Downloaded October 20, 2026 | Daily check and rebuild. Inspections do not prove current operation. |
| Permitted events | October 20, 2026 to January 17, 2027 | Daily check and rolling-window rebuild. Community-district exposure is inherited by tracts. |
| ZIP Business Patterns | 2015 and 2023 | Monthly check; full ZIP archives and complete food-service rows local. Dominant property ZIP links retain ZIP context and boundary-change caveats; do not sum hierarchy levels or treat ZIP counts as tract observations. |
| Historical permitted events | Latest complete past calendar year represented in publisher export | Monthly publisher check; full 2,906,868-row source. District-year aggregates, not tract attendance; upcoming events remain separate. |
| Active liquor licenses | Current publisher revision, downloaded October 20, 2026 | Monthly check via `sla_active_context`; full statewide source, NYC restaurant/hospitality subset matched to local addresses. Partial matching is labeled, not treated as full license coverage. |
| EPA walkability | Smart Location Database v3, underlying population circa 2018 | Monthly integrity check. Full block-group geometry is crosswalked to 2020 tracts with area-allocated population weights; five tracts remain blank. Static built-environment proxy, not current foot traffic. |
| PLUTO land use | 26v2 | Monthly check and automatic parcel-to-tract rebuild. Vacant land is distinct from available restaurant space. |
| Storefront Registry | Complete 2024 filings | Monthly check and automatic rebuild of latest complete reporting year. Newer vacancy-only filings cannot supply a vacancy-rate denominator. |
| Storefront rent statistics | 2024 | Monthly check and automatic rebuild. Published occupied-rent medians, not current asking rents. |
| OSM food and nightlife | October 17, 2026 replication | Weekly check and automatic PBF rebuild. Tagged POIs may be incomplete; not a complete business registry. |
| DOT pedestrian monitors | Latest complete period at each site, newest May 2026 | Monthly check and automatic nearest-monitor rebuild. Only 114 sites; these are not tract-wide foot traffic. |
| NOAA weather | Central Park through October 16, 2026 | Daily check and rebuild into a separate citywide daily table, never copied as tract-level observations. |

The updater checks each publisher on its cadence, downloads full versioned source files, tests and previews supported transforms, and activates a new release only after structural and score-change validation. Unsupported sources are reported as pending integration rather than silently treated as current. Fixed 2020 geography and mobile food vending violations are kept separately as reference sources.

This matrix is ready for **feature engineering and descriptive evaluation**, not yet for a supervised business-success model. Verified longitudinal outcomes and historical feature snapshots at the time each business opened are still needed to avoid leakage. Asking rents, sale prices, confirmed availability, listing photos, and observed site-level sales are not supplied by these public sources.

The separate private evaluation tranche at `data/evaluation/snapshots/2024-12-v2/`
now has full-source 2023 ACS density/income, 2022 LODES job density, and EPA v3
walkability with publisher availability dates. It is partial (four of eight
evaluation features) and does not change the current dashboard master or make
business-success training ready. See `demo/EVALUATION.md` for coverage and gaps.

The separate `data/evaluation/snapshots/2023-12-v1/` tranche uses full 2022
ACS and 2021 LODES publisher files, with the earlier EPA vintage carried into
the combined historical-core manifest. These dates make an earlier training
cohort possible, but verified restaurant outcomes are still absent. The
private 100-row review queue is not a closure dataset or training matrix.
