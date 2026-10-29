# October 20 Data Extension

The active local master is `data/integrated/current/master_tract_features.csv`:
2,327 unique NYC 2020 census tracts and 193 documented columns. The active
release is `20261020T214426Z_6d4bfdd3`. Earlier exports remain frozen at their
original schemas; use the active release or generate a new team export.

## Completed Data Work

- Eleven full national ACS 2024 detailed tables are downloaded locally. The
  official [bulk summary files](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/)
  provide a repeatable route without an API key. Core population and household
  income are rebuilt, and 24 new measures cover age 20-34, poverty, per-capita
  income, income bands, commuting, education, nativity, households, tenure,
  and residential gross rent. Source estimates and margins are retained in
  `features/acs_context_estimates_and_margins.csv`; missing and suppressed
  values remain blank. B19301 publishes 2,324 of the 2,327 tract rows.
- Full 2023 New York LODES residence-area data adds 30,850 NYC home blocks and
  3,769,974 jobs assigned by residence. These are all-job counts, so they can
  exceed the number of people. Five master fields include totals, high-earning
  and food-service jobs, vintage, and a workplace/home-area job ratio. The ratio
  is recomputed only for matching workplace and residence years.
- The full MTA entrance file has 2,120 rows, yielding 2,072 distinct coordinates
  that allow entry. Three master fields describe entrance/station counts
  within 400 meters of the tract centroid and nearest-entry distance. Distances
  use projected straight-line geometry rather than walking routes.
- All 168 hours of the integrated week at 424 station complexes produce four
  nearest-station entry shares: morning, evening, late night, and weekend.
  A station's entries remain a mobility observation, not restaurant visits.
- Official TLC geometry creates 3,378 tract/zone overlaps across 263 zones;
  791 tracts overlap multiple zones. Four master fields describe coverage and
  the largest overlap. Both directional area fractions are retained in
  `geography/tract_taxi_zone_crosswalk.csv`. Zone trips are not invented at
  tract level.
- A full native-grain ZIP Business Patterns extract retains 119,670 published
  food-service ZIP/NAICS rows across 18,323 ZIPs in
  `features/zip_food_service_business_patterns.csv`. This includes nationwide
  rows from the full publisher archive. Nested NAICS levels must not be summed
  together. These counts are not assigned to tracts.

The 40 added master fields comprise 24 ACS, five residence-job, three entrance,
four subway time-share, and four taxi overlap fields. Raw national files and
large entity tables stay separate from the tract matrix. Source catalog,
dictionary, readiness, QA, release fingerprints and training inventory are
updated. Existing screening scores did not change in the release audit.

## Repeatable Processing

The source registry now includes `acs_context`, `lodes_rac`,
`subway_entrances`, and `taxi_zone_geometry`. Existing monthly publisher checks
cover them. Weekly `mta_subway` rebuilds also refresh the time shares. Normal
maintenance uses the bulk ACS provider instead of requiring credentials for
the optional direct Census API sources. Each ACS table has a source URL,
publisher headers and SHA-256; changing any table triggers a new bundle.

```bash
.venv/bin/python demo/maintain_data.py
.venv/bin/python demo/maintain_data.py --audit
```

`demo/enrich_location_data.py` implements the transforms; the existing staged
release process validates and atomically activates them. Newer ACS years need
an explicitly versioned column schema before automatic integration. Current
2024 context is separate from the dated historical predictor snapshots.

## Disappearance Review

Queens building-number hyphens are now normalized specifically for Queens,
without merging Manhattan building ranges. The v5 private adjudication packet
finds 127 possible CAMIS transitions, versus 104 in v4, and 18 same-CAMIS
name/address conflicts. They remain review leads.

A probability sample of 12 cases was drawn with seed 440 from the 122 strict
proxy disappearances. The selection probability is 12/122. Source searches
found operating-page, name, and directory freshness conflicts; no dated
permanent-closure event was established. The review cannot estimate the true
closure fraction. Across all 122 addresses, 91 have another current restaurant
listing at the normalized address. A successor tenant does not establish
continuity or date the prior tenant's closure.

Private outputs:

- `data/evaluation/lifespans/adjudication_packet_20261020_v5.csv`
- `data/evaluation/lifespans/disappearance_audit_20261020_v1.csv`
- `data/evaluation/lifespans/disappearance_audit_20261020_v1_sample.csv`
- Corresponding manifests, plus `disappearance_source_review_20261020.json`.

The earlier proxy model remains a frozen exploratory result. No verified
restaurant-survival model or new dashboard predictor was published. The FOIL
request is drafted and unsent. Verified permanent-closure dates, licensed live
property listings, historical reconstruction of the new predictors, and a
validated postal ZIP/tract allocation remain outstanding.

## Verification

All 177 demo tests pass. Release QA checks geographic coverage, documented
columns, bounded shares, exhaustive ACS share sums, unique crosswalk keys and
taxi-zone area conservation. Training inventory is structurally valid with no
sample input in the active matrix. The five targeted publisher checks report
no blockers, failures or pending transforms, and repeat runs avoid duplicate
downloads. Korean/Queens and vegan/Mexican dashboard requests both return HTTP
200 with 24 recommendations using the active release. The source data remains
local and the frontend source was not edited by this extension.
