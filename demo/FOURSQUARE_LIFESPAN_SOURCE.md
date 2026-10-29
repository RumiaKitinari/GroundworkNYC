# Foursquare OS Places Closure Leads

## Dated Public Release

The current Foursquare OS Places delivery requires a Foursquare Places Portal
account and an access token. Until that is available, the project has a pinned
February 6, 2025 public GeoParquet mirror hosted by Source Cooperative, under
Foursquare's Apache-2.0 license. This is a complete extraction for the chosen
release, **not a sample**. The source and definitions are:

- https://source.coop/fused/fsq-os-places
- https://docs.foursquare.com/data-products/docs/places-os-data-schema
- https://docs.foursquare.com/data-products/docs/access-fsq-os-places

The frozen NYC-area bounding box intersects partitions `16.parquet` and
`17.parquet` of this release. The extraction applies row-level coordinates,
`region = NY`, and a `Dining and Drinking` category filter. It has 120,904
places, 33,258 of which have a non-null `date_closed`. This bounding box is
not an exact NYC jurisdiction boundary; DOHMH case matching uses street,
ZIP, name, and distance.

```bash
.venv/bin/python demo/extract_foursquare_nyc.py
.venv/bin/python demo/match_foursquare_lifespan_leads.py
```

Private files and immutable audits:

- `data/raw_sources/foursquare_os/2025-02-06/nyc_dining.csv`
- `data/raw_sources/foursquare_os/2025-02-06/nyc_dining.manifest.json`
- `data/evaluation/lifespans/foursquare_review_leads_20261020_v2.csv`
- `data/evaluation/lifespans/foursquare_review_leads_20261020_v2.manifest.json`

## Full-Cohort Match Results

All 5,999 strict DOHMH review cases were processed. Matching requires an
exact or highly similar business name, the same ZIP, and either the same
normalized street address within 150 meters or the exact name within 50
meters. Multiple place IDs remain ambiguous. The results are:

| Status | Cases |
| --- | ---: |
| No conservative match | 3,702 |
| Matched, not marked closed by the February 2025 release | 2,200 |
| Marked closed, without a later DOHMH active snapshot | 31 |
| Marked closed, but present in a later DOHMH active snapshot | 26 |
| Multiple identity candidates | 32 |
| Foursquare closure mark predates the first cycle inspection | 8 |

Foursquare defines `date_closed` as the date its database marked the POI
closed, **not necessarily when the business actually closed**. The 26 later
DOHMH listings demonstrate direct source disagreement or possible reopening.
A null `date_closed` in a February 2025 release says nothing about operation
in 2026. A first cycle inspection is an operating lead, not necessarily an
opening date. No match changes `outcome_status = unresolved`, and no record
from this source enters the survival training matrix automatically.

## Current Release and Adjudication

Sign in to https://places.foursquare.com/ to generate a Places Portal token
for the current Iceberg release. Export NYC-area Dining and Drinking rows with
the same identifying columns, category, `date_closed`, and release/snapshot
identifier. Keep that release separate from the 2025 mirror and rerun the
matcher against it. The token should stay in a local environment variable,
never in the repository or a command transcript.

For a one-year survival label, compare a dated operating baseline with a
later, independently corroborated operating observation or permanent closure.
Treat Foursquare marks as search leads, not closure dates. Keep changes of
name, owner, permit, and location unresolved until identity is checked.
