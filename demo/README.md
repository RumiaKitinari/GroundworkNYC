# Groundwork NYC Flask Frontend Prototype

**For the integrated checkout, use [OTIS_LOCAL_SETUP.md](OTIS_LOCAL_SETUP.md).**
It records verified startup, the actual local release and generated access bundles,
and missing survival artifacts. The completion release described below is an
upstream data package, not the currently installed 107-column release.

See [Connected Account Workspace](CONNECTED_WORKSPACE.md) for property shortlists,
saved economic scenarios, menu baskets and private database persistence.

The October 20 completion release contains 2,327 tracts and 249 documented master
columns. `acs_context` downloads thirteen full national ACS 2024 detailed tables
and extracts every NYC tract, retaining estimates and margins. This bulk route
does not require a Census API key. Normal maintenance uses it for population,
age, income, commuting, education, nativity, poverty, households, tenure, and
residential rent, unemployment, and average household size. Direct Census API download options still require a key.

Additional repeatable sources are `lodes_rac`, `subway_entrances`, and
`taxi_zone_geometry`. Weekly MTA rebuilds also produce nearest-station time
shares. ZIP Business Patterns food-service rows remain at ZIP/NAICS grain;
TLC intersections retain both area fractions; separate `rideshare_*` fields
provide explicitly estimated uniform-area allocations, not observed tract trips.
The completion transform adds 400-meter subway time shares, EPA intersection
and transit measures, labeled rent/income context estimates, property-ZIP and
partial exact-address SLA context, and twelve neighboring-tract measures.
`events_historical`, `business_patterns_2015`, and `sla_active_context` are
repeatable publisher-checked sources. See `CURRENT_MASTER_COMPLETION.md` for
the precise remaining limits and how to export the team handoff.
All new sources participate in the existing monthly publisher checks, except
weekly MTA activity. A future ACS year requires a versioned field-schema update.

```bash
.venv/bin/python demo/download_sources.py --source acs_context --source lodes_rac --source subway_entrances --source taxi_zone_geometry
.venv/bin/python demo/refresh_integrated.py --source acs_context --source lodes_rac --source subway_entrances --source taxi_zone_geometry --source business_patterns --source mta_subway --publish
.venv/bin/python demo/maintain_data.py --audit
```

This is the Flask dashboard demo for the DS 440 capstone. The backend reads the active integrated Groundwork release at `../data/integrated/current/` when present, or the baseline at `../data/integrated/restaurant_bar_location_data_ready/`. It uses `master_tract_features.csv` as the primary source for NYC restaurant and bar location scoring.

## Data Setup

The integrated data package is intentionally not stored in GitHub. After downloading the private data folder, place it at this exact path from the repository root:

```text
data/integrated/restaurant_bar_location_data_ready/
```

The final layout should look like this:

```text
GroundworkNYC/
  demo/
    app.py
    templates/
    static/
  data/
    integrated/
      restaurant_bar_location_data_ready/
        README.md
        master_tract_features.csv
        data_dictionary.csv
        feature_readiness.csv
        source_catalog.csv
        entities/
        features/
        geography/
    osm/
      NewYork.osm.pbf
      nyc_walk_network.sqlite  # generated locally; do not upload
      NewYork-mbtiles-shortbread/
        NewYork.mbtiles
    subway/
      manifest.json
      station_hour_2025-03-03.csv
      station_hour_2025-06-02.csv
      station_hour_2025-09-08.csv
      station_hour_2025-12-01.csv
    concept_images/  # private local presentation assets
    raw_sources/     # versioned publisher downloads; do not upload
```

If the download arrives as a zip file, unzip it so the folder itself is named `restaurant_bar_location_data_ready`. The app expects `master_tract_features.csv` to be directly inside that folder, not one extra folder level deeper.

The current demo supports tract-level location recommendations, score explanations, source coverage, and Storefront Registry property leads. Exact asking rent, sale price, listing photos, confirmed lease or purchase availability, review sentiment, and mobile-phone foot traffic are not included in the uploaded data package.

One manually checked [NYCHA public leasing opportunity](PROPERTY_DATA.md) now
supplies a source-reported asking rent and size for a restaurant-equipped space.
This does not provide general listing coverage or confirm that the space remains
available. Broker/owner snapshots can be added with `demo/import_partner_listings.py`
once display rights are documented. No third-party listing scraper is configured.

For a broader dashboard demonstration, run
`.venv/bin/python demo/generate_synthetic_properties.py` after placing the
integrated data. This generates 1,000 [explicitly synthetic lease and purchase
scenarios](SYNTHETIC_PROPERTIES.md) in `data/listings/`, separate from real
source-linked leads. These scenarios are not verified available properties or
survival-model training data.

## Repeatable Source Downloads

`download_sources.py` covers the registered source families, including ACS bulk
tables, LODES residence-area jobs, subway entrances, TLC zone geometry, the
2020 tract boundary file, optional mobile food vending violations, and
storefront rent statistics. It checks the publisher for a current vintage, downloads
into a new revision under `data/raw_sources/<source>/`, records URLs, timestamps,
file sizes and SHA-256 hashes, and skips unchanged versions. Incomplete or
invalid downloads are not published. It never overwrites cleaned or integrated
data, and it does not run on dashboard page loads.

From the repository root:

```bash
python demo/download_sources.py --list
python demo/download_sources.py --all --check
python demo/download_sources.py --source restaurants --source events
python demo/download_sources.py --source tlc_hvfhv
python demo/download_sources.py --source storefront_rent_stats
python demo/download_sources.py --all
```

`--check` contacts publishers but does not download. `--all` explicitly
downloads every source and can use several gigabytes of disk and bandwidth;
prefer selected sources for routine work. `--force` creates a new version even
when the publisher appears unchanged. Monthly and annual files probe for the
newest published vintage; NYC Open Data tables use stable 50,000-row pages,
row counts, and publisher update timestamps. MTA downloads the latest complete
published week at station-hour grain. Large public files may be subject to
publisher throttling; failed sources are reported individually for retry.

Direct Census API queries require a key. Obtain one from the
[Census Data API](https://api.census.gov/data/key_signup.html), set
`CENSUS_API_KEY` in your local environment to use the optional API sources. The key
is used in requests but never written to the download manifest. `--check`
still discovers the latest published ACS vintage without a key. The default
`acs_context` bulk source downloads and integrates ACS without API credentials.

Keep `data/raw_sources/` outside GitHub along with the other private data.

The NYC storefront rent statistics are rebuilt into the integrated master from
the versioned raw snapshot. The scheduled maintainer checks the publisher
monthly and refreshes the tract features when a new revision appears. The
latest available report is 2024. The Economics view shows its tract-level median monthly rent per square
foot for occupied class 2 and 4 storefronts where published. This is historical
reported rent context, **not** a live asking rent, property quote, or budget
fit calculation. See [NYC's source table](https://data.cityofnewyork.us/City-Government/Storefront-Registration-Class-2-and-4-Statistics/dxru-eun8).

## Repeatable Integrated Refresh

`refresh_integrated.py` rebuilds **restaurant inspections, permitted events,
MTA subway activity, TLC HVFHV taxi-zone activity, OSM food/nightlife POIs,
Citi Bike trips, PLUTO land use, storefront filings, published storefront
rent medians, EPA walkability, and Central Park daily weather**.
It uses versioned raw downloads; OSM can also use `data/osm/NewYork.osm.pbf`
when no raw-source revision has been downloaded. It updates the
associated entities, feature tables, master tract table, source catalog, and QA
metadata. It verifies raw SHA-256 checksums, retains the baseline package, and
stages a complete new package before activating it. A failed refresh leaves the
active release unchanged. The Flask app follows `data/integrated/current`, so
the next request uses a newly activated release without a server restart.

From the repository root, with the private integrated package installed:

```bash
python demo/download_sources.py --source restaurants --source events --source mta_subway --source tlc_hvfhv --source citibike --source pluto --source storefronts --source storefront_rent_stats
python demo/refresh_integrated.py --as-of 2026-10-06
python demo/refresh_integrated.py --as-of 2026-10-06 --publish
python demo/refresh_integrated.py --source osm --as-of 2026-10-06
python demo/refresh_integrated.py --source osm --as-of 2026-10-06 --publish
python demo/refresh_integrated.py --list-releases
python demo/refresh_integrated.py --activate 20261001T000000Z_1234abcd
```

The first refresh is a **preview**: it builds and validates a temporary package
without changing the dashboard. `--publish` is required to activate a release.
The release name above is only an example; copy a real name from
`--list-releases` to roll back. Use `--download` on a refresh command to fetch
the selected raw sources first, `--source restaurants` (repeatable) to rebuild
only specific supported transforms, and `--revision SOURCE=DIRECTORY` to pin a
particular raw revision for reproducibility. Each release records its raw
revision IDs, as-of date, updated sources, carried-forward sources, and
validation results, raw and scoring-input SHA-256 hashes in
`refresh_manifest.json`. Score-affecting refreshes also write
`score_audit.json`: a before/after score and top-decile comparison across
restaurant formats, price tiers, cuisines, dayparts, and dietary positioning.
Review its flags before activating a preview. These are behavior checks, not
training metrics or evidence that the scores predict business success.

The OSM transform reads tagged nodes and ways from the PBF, assigns them to
NYC tracts, removes same-name near-duplicates, and reports a conservative
name-and-distance match against active inspection records. That match is QA
only; OSM competition and inspection cuisine inventory remain separate.
Install `pip install -r demo/requirements-data.txt` for the OSM and TLC
transforms; the EPA spatial crosswalk also requires GDAL's `ogr2ogr`. The
downloader covers more sources than this rebuild does. Full LODES workplace
blocks and DOT pedestrian monitors now have automatic tract transforms. ACS
estimates retain baseline values until a keyed full-source download and tract
transform are available. ZIP business-pattern counts are not tract
measurements and remain separate. Citi Bike latest-month columns
are separate from the retained August 2026 columns. PLUTO code 11 counts
vacant land; code 10 is parking and is excluded. Storefront filings are
reported vacancy, not verified availability. Events use rolling 90-day columns;
the retained 2026 columns count only events occurring in 2026. It does not create
listing rents, sale prices, foot-traffic estimates, or other unavailable data.
See [DATA_VINTAGES.md](DATA_VINTAGES.md) for the source-by-source freshness audit
and integration priorities.
The TLC latest-month taxi counts are taxi-zone aggregates repeated across tracts in the
same zone. They are available in the API for context, but are not yet weighted
into the location score.

## Scheduled Data Maintenance

Run from the project root with the local virtual environment:

```bash
.venv/bin/python demo/maintain_data.py --audit
.venv/bin/python demo/maintain_data.py --check-only
.venv/bin/python demo/maintain_data.py
```

The scheduled command is the last one. It checks restaurants, events, and
weather daily; OSM and subway weekly; all other registered publishers monthly.
It downloads only changed, full source revisions. Supported transforms run
tests and a preview, then publish an immutable release only when validation
passes. `data/update_state.json` records check periods, `data/update_runs/`
records each run, and `data/training_inventory.json` lists the full raw files,
integrated revisions, reference-only samples, and remaining training gaps.
`--audit` never contacts publishers; `--check-only` downloads but does not
publish. `--source NAME` and `--force` support targeted retries. Normal maintenance
uses `acs_context` for both core ACS and additional context; optional direct
API sources can still be selected explicitly with a Census key.

Only the 2020-tract feature matrix belongs in `master_tract_features.csv`.
Full trip, parcel, POI, ZIP, and citywide-day files remain in clearly named
`data/raw_sources/` or separate integrated entity/feature tables. Nothing
named `SAMPLE` is a training input. See `data/README.md` for the directory
contract. Structural readiness does not mean a business-success model can be
trained: verified longitudinal outcomes and historical, leakage-safe feature
snapshots are still missing.

Restaurant briefs include 50 cuisine and specialty categories, plus fusion and
custom concepts. Typing an idea such as "Korean Bistro" offers cuisine and
format suggestions. Pricing can be entered as a $-$$$$ range or an exact
average spend per guest. The brief also accepts dietary identity and a free-text
description. Appearance can be switched between light and dark in Settings.
Lease, purchase, and combined searches have separate budgets and listing filters. See
[PROPERTY_DATA.md](PROPERTY_DATA.md) for the optional listing CSV contract.
`POST /api/concepts/resolve` accepts a JSON concept brief and returns the
resolved cuisine, dietary identity, format, price basis, and evidence status.
`POST /api/sites/analyze` accepts `latitude`, `longitude`, and optional concept
fields, and returns local walking-catchment evidence for a proposed NYC site.

The Menu tab offers editorial dish ideas for supported cuisines and formats,
custom additions, editable sections, prices, descriptions and ingredient costs,
per-concept saving, a printable preview and CSV export.
`GET /api/menu/suggestions` is the reusable
backend contract for the upcoming frontend. Current sources do not include
dish ratings or orders; see [MENU_DATA.md](MENU_DATA.md) for the catalog and
optional rights-cleared review-evidence schema.

The Streets map is served locally from the New York OpenStreetMap MBTiles extract.
Streets can be panned through the NYC metro area and zoomed out to a regional
view; Aerial keeps a tighter NYC-area envelope. The 3D view combines online
Esri imagery and OpenFreeMap height-bearing building geometry with local OSM
street labels and named points of interest. Buildings, streets and named POIs
can be hovered or clicked for available details; location markers retain their
score and property popups. The 3D mode requires an internet connection and
returns to Aerial if its building tiles are unavailable. Its rendered building
height is a map attribute, not a verified measurement or property listing.
All three views share zoom, pan and expanded-map controls. The map's Concept Demand layer
shows H3 sectors at overview zoom, local cells after zooming in, and finer
single-grid cells at street zoom. Its API and limitations are documented in
[SCORING.md](SCORING.md); the block-coverage experiment is in
[HEX_RESOLUTION_STUDY.md](HEX_RESOLUTION_STUDY.md).
Download `NewYork.osm.pbf` and `NewYork.osm.mbtiles-shortbread.zip` from
[BBBike NewYork](https://data.bbbike.org/osm/bbbike/NewYork/), place the PBF in
`data/osm/`, and unzip the tiles archive there so `NewYork.mbtiles` has the path
shown above. The PBF is used to build the private pedestrian graph; MBTiles is
the rendered map's vector source. Both files are private local data and
should remain outside GitHub. The Aerial view uses Esri imagery online; OSM
does not include aerial photography.

For address-level 10-minute walking catchments, build the local graph once from
the PBF. The generated SQLite file is roughly 400 MB and must also stay outside
GitHub:

```bash
pip install -r demo/requirements-geospatial.txt
python demo/build_walk_network.py
```

The dashboard still runs without this graph; property cards report walking
evidence as unavailable. A catchment counts geocoded active restaurants and
subway stations reachable on the OSM pedestrian network. It is not measured
foot traffic or a visit forecast.

## Concept Images

The concept brief loads a local image from `demo/static/images/concepts/` when
one is present. Name each JPEG after the matching cuisine option value in the
brief, for example `korean.jpg`, `steakhouse.jpg`, or
`vegetarian_vegan.jpg`. Use `general.jpg` for the default concept. Until an
image is added, the existing brief image remains as a temporary fallback.
Keep image source, creator, license, and attribution information with the
image collection; a Creative Commons label alone is not enough to verify
reuse rights. Images are presentation assets and do not affect scoring.

The team's `Cuisine Idea List.docx` can be imported locally with
`python demo/import_concept_images.py '/path/to/Cuisine Idea List.docx'`.
This extracts 31 reviewed images into `data/concept_images/`, outside the
publishable source tree. The document contains no image credits or license
links, so these images are for the local demo only until reuse rights are
verified. The remaining categories keep the fallback image.

## Hourly Subway Data

Run `python demo/download_subway.py` from the repository root to download
four complete 2025 weeks from the [MTA hourly ridership dataset](https://data.ny.gov/d/5wq4-mkjj).
Files are grouped by station and hour across fare types and validated for
168 hours, over 400 stations and a SHA-256 checksum. They remain in private
`data/subway/`, not GitHub. Market Profile shows observed weekday morning,
midday and evening station entries averaged across those weeks. These are
station entries, not sidewalk traffic or restaurant customers.

Run `python demo/train_subway.py` after installing
`requirements-evaluation.txt` to evaluate a station-hour model against a
station-average baseline on a held-out December week. The report is written
to `data/evaluation/reports/`; this research model does not change location
scores. After an integrated refresh is published, the station-week totals in
that release become the primary transit input for dashboard scoring. The four
2025 weeks remain a separate daypart research view.

For the combined local dashboard, run from the repository root:

```bash
.venv/bin/python -m pip install -r backend/requirements-dashboard.txt
.venv/bin/python run_local.py --check
.venv/bin/python run_local.py
```

This uses the private `.env`, existing PostGIS and Redis services, and the same
account/workspace files. It does not migrate or delete saved user work. See
`backend/README.md` to start the infrastructure. The combined service uses port
5001 by default and exposes `/docs`, `/health/ready` and spatial tile APIs on
the same origin as the dashboard. Keep the current model environment and install
`codes/requirements-temporal.txt` when using the optional survival tools.

For standalone Flask-only development without spatial storage, run from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then visit `http://localhost:5001`.

The entry screen supports guest access and local demo accounts. Guest work is
saved on that device. Signed-in briefs, saved concepts, comparison lists and
menus sync to `instance/accounts.sqlite3`; sign-in imports guest work created
since the last import without replacing existing account entries. The browser keeps a local copy if
account sync is unavailable. The Settings tab shows sync status and lets users
reopen saved concepts. Account hashes and the Flask signing key stay in the
private `instance/` folder. Back up this folder before moving computers.
This is not a production authentication system: the data APIs are not
access-controlled, and there is no account recovery, rate limiting or
multi-device conflict-resolution UI. Do not expose the demo to the public
internet as an account service. See [DASHBOARD_DATA_AUDIT.md](DASHBOARD_DATA_AUDIT.md)
for the provenance and missing-data audit.

## Concept Scoring

The brief supports cuisine, average spend per guest, service style, customer
focus and trading period. Walkability describes the area; Business Fit is a
concept-specific screening index. Customer Access (inverse walkability) is a
separate network-derived walking-access assessment. None is a visit or revenue forecast.
The Budget tab calculates required sales and covers only after the user enters
other fixed costs, variable costs, and operating days. It excludes unentered
costs, taxes, and debt service; no default profit or survival forecast is shown.
See [SCORING.md](SCORING.md) for assumptions, data coverage and validation plans.
Keep `entities/current_restaurants.csv` in the integrated package for cuisine
counts. No private datasets are included in the application source.

## Backend Evaluation

See [EVALUATION.md](EVALUATION.md) for the runnable cuisine-presence benchmark,
historical continued-operation model, and non-lease validation methods. Install
`requirements-evaluation.txt` to use the optional ML tooling. Generated reports
stay under `data/evaluation/` and must not be uploaded with demo source.

## Customer Access Dashboard

The Customer Access tab and map layer use the prepared local OSM walking matrix,
ACS residents and resident income, and LODES workplace jobs. Changing dining style,
spend, audience or service hours recomputes the assessment from cached routes;
HTTP requests do not rebuild the walking graph. Access ranking is opt-in and
does not change the underlying location scores. Origin areas and coverage are
available through `/api/customer-access?geoid=<11-digit-tract-id>`.

After preparing a property feature bundle with `codes/engineer_customer_access.py`,
prepare the dashboard's separate tract-centroid bundle:

```bash
.venv/bin/python demo/prepare_dashboard_access.py \
  --property-run data/output/feature_engineering/20261027_v3 \
  --output data/output/customer_access_dashboard/20261027_v1
```

Use a new output directory for each run. This publishes the local pointer at
`data/output/customer_access_dashboard/dashboard_access.json`. Keep the pinned
source files, manifests and routing matrices in place; missing or altered inputs
disable the assessment instead of substituting estimated distances. Scores for
synthetic properties use their own coordinates, not their containing tract's score.
Unprepared real property listings show access as unavailable. These are
uncalibrated present-day opportunity indices, not observed visits, survival
probabilities, transit catchments or historical training features.
