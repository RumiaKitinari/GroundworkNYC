# Groundwork Data Vintages

Audited October 6, 2026. The active 2020-tract master has 2,327 rows and 128 documented columns. These are the **observation periods**, not the date a file was downloaded. The machine-readable audit is `data/training_inventory.json`; the active release's `source_catalog.csv` and `refresh_manifest.json` pin its inputs.

| Signal | Active observation period | Refresh and limitation |
| --- | --- | --- |
| Population, age, income | 2020-2024 ACS five-year | Monthly publisher check. Baseline tract features are retained; automated rebuild needs a Census API key and tract transform. Not a 2024 point-in-time count. |
| Workplace jobs | 2023 LODES WAC | Monthly check; full 2023 archive local. Baseline tract transform is not yet automated. |
| Subway entries | Complete week of September 14, 2026 | Weekly check and automatic rebuild. One week is not typical annual ridership. |
| Citi Bike departures | September 2026 | Monthly check and automatic rebuild from the full monthly trip archive. August 2026 columns remain historical. |
| HVFHV taxi activity | August 2026 | Monthly check and automatic rebuild from the full trip file. Taxi-zone totals are inherited by tracts, not measured within each tract. |
| Restaurant inspections | Downloaded October 6, 2026 | Daily check and rebuild. Inspections do not prove current operation. |
| Permitted events | October 6, 2026 to January 3, 2027 | Daily check and rolling-window rebuild. Community-district exposure is inherited by tracts. |
| ZIP Business Patterns | 2023 | Monthly check; full ZIP archive local. ZIP counts are not tract counts, so do not copy them into the master as tract observations. |
| EPA walkability | Smart Location Database v3, underlying population circa 2018 | Monthly integrity check. Full block-group geometry is crosswalked to 2020 tracts with area-allocated population weights; five tracts remain blank. Static built-environment proxy, not current foot traffic. |
| PLUTO land use | 26v2 | Monthly check and automatic parcel-to-tract rebuild. Vacant land is distinct from available restaurant space. |
| Storefront Registry | 2025 filings | Monthly check and automatic rebuild of latest property filings. Reported vacancy is not an available listing. |
| Storefront rent statistics | 2024 | Monthly check and automatic rebuild. Published occupied-rent medians, not current asking rents. |
| OSM food and nightlife | October 3, 2026 replication | Weekly check and automatic PBF rebuild. Tagged POIs may be incomplete; not a complete business registry. |
| DOT pedestrian monitors | Biannual count sites | Monthly check; full raw source local. Baseline nearest-monitor feature is not yet automatically rebuilt; sparse monitors are not tract-wide foot traffic. |
| NOAA weather | Central Park through September 29, 2026 | Daily check and rebuild into a separate citywide daily table, never copied as tract-level observations. |

The updater checks each publisher on its cadence, downloads full versioned source files, tests and previews supported transforms, and activates a new release only after structural and score-change validation. Unsupported sources are reported as pending integration rather than silently treated as current. Fixed 2020 geography and mobile food vending violations are kept separately as reference sources.

This matrix is ready for **feature engineering and descriptive evaluation**, not yet for a supervised business-success model. Verified longitudinal outcomes and historical feature snapshots at the time each business opened are still needed to avoid leakage. Asking rents, sale prices, confirmed availability, listing photos, and observed site-level sales are not supplied by these public sources.
