# Groundwork NYC Flask Frontend Prototype

This is the Flask dashboard demo for the DS 440 capstone. The backend reads the active integrated Groundwork release at `../data/integrated/current/` when present, or the baseline at `../data/integrated/restaurant_bar_location_data_ready/`. `GROUNDWORK_DATA_DIR` overrides both paths. The dashboard and explorer readers use the same active directory. It uses `master_tract_features.csv` as the primary source for NYC restaurant and bar location scoring.

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

An optional [NYCHA public leasing opportunity](PROPERTY_DATA.md) CSV can
supply source-reported asking rent and size for a restaurant-equipped space.
That CSV and the optional rent benchmark snapshot are absent in this checkout;
listing and rent context remain unavailable until installed. The two existing
market API tests requiring these private files fail for that reason.
This does not provide general listing coverage or confirm that the space remains
available. Broker/owner snapshots can be added with `demo/import_partner_listings.py`
once display rights are documented. No third-party listing scraper is configured.

## Repeatable Source Downloads

`download_sources.py` covers all 15 source families in the integrated package's
`source_catalog.csv`, plus the 2020 tract boundary file, the optional mobile
food vending violations source, and NYC storefront rent statistics. It checks the publisher for a current vintage, downloads
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

The Census now requires an API key for ACS data queries. Obtain one from the
[Census Data API](https://api.census.gov/data/key_signup.html), set
`CENSUS_API_KEY` in your local environment, and rerun the ACS sources. The key
is used in requests but never written to the download manifest. `--check`
still discovers the latest published ACS vintage without a key.

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
downloader covers more sources than this rebuild does. ACS, LODES, and
pedestrian counts retain their baseline tract features until dedicated
automatic transforms are added. ZIP business-pattern counts are not tract
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
publish. `--source NAME` and `--force` support targeted retries. The Census
ACS downloader needs `CENSUS_API_KEY`; without it, the run reports that source
as blocked and retains the existing ACS tract estimates.

Only the 2020-tract feature matrix belongs in `master_tract_features.csv`.
Full trip, parcel, POI, ZIP, and citywide-day files remain in clearly named
`data/raw_sources/` or separate integrated entity/feature tables. Nothing
named `SAMPLE` is a training input. See `data/README.md` for the directory
contract. Structural readiness does not mean a business-success model can be
trained: verified longitudinal outcomes and historical, leakage-safe feature
snapshots are still missing.

Restaurant briefs include 50 cuisine and specialty categories, plus fusion and
custom concepts. Typing an idea such as "Korean Bistro" offers cuisine and
format suggestions. The brief uses a $-$$$$ price range with a documented
average-spend assumption; the API also accepts an exact spend. The brief also accepts dietary identity and a free-text
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
Map modes retain NYC bounds and the camera position. The 3D view uses online
OpenFreeMap vector streets and height-bearing building geometry. Aerial uses
Esri imagery separately. Existing restaurant dots, their toggle and legend
appear only in 3D Buildings. Buildings, streets and named POIs
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

Run from the repository root with Python 3.11 or 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Then visit `http://localhost:5001`. No frontend build step is required.
Flask does not require PostGIS or Redis. For the optional combined FastAPI
service on port 8000, see [backend/README.md](../backend/README.md).

Keep the full integrated package: the resident/worker explorer reads
`features/tract_demographics_income.csv` and `features/tract_workers.csv`;
transit reads the subway, Citi Bike, pedestrian and taxi feature/entity tables.
Refreshed monthly data takes precedence over baseline columns when present.
The storefront and competition explorers read the active release's registry
and restaurant entities. Missing required files return 503; the optional
walking graph and listing sources remain explicitly unavailable.


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
focus and trading period. Walkability describes the area; Business Draw is a
concept-specific screening index. Neither is a visit or revenue forecast.
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

## Baseline reliability and optional survival inference

Python 3.11 is verified locally; Python 3.12 uses the conditional NetworkX
version in requirements.txt. Standalone Flask needs no PostGIS, Redis, pandas
or XGBoost. Keep using the root quickstart above.

The map boundary uses `geography/nyc_2020_census_tracts.geojson` from
`integrated_directory()`, including a `GROUNDWORK_DATA_DIR` override. City-mask
simplification is display-only. All five boroughs are supported. The optional
spatial backend rejects screening tiles whose release or scoring-code hash is
stale; the dashboard falls back to current GeoJSON. Re-export screening layers
after changing their data or scoring code.

Workspace revision checks and writes use one SQLite write transaction to
prevent concurrent tabs from silently overwriting a saved revision. Existing
account/workspace files remain private under instance/.

[Optional survival inference](SURVIVAL_DASHBOARD.md) is connected separately
from screening rankings. A locally generated Atharv tract export now supplies real estimates; see
[the demo/reproduction guide](ATHARV_DEMO.md). It uses the archive-based model
contract from `ADM6112-complete-v1`, distinct from Otis's dated-model contract.
Artifacts stay local, and screening scores remain separately labeled.
