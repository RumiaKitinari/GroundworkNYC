# Groundwork NYC Flask Frontend Prototype

This is the Flask dashboard demo for the DS 440 capstone. The backend reads the integrated Groundwork dataset at `../data/integrated/restaurant_bar_location_data_ready/` and uses `master_tract_features.csv` as the primary source for NYC restaurant and bar location scoring.

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
```

If the download arrives as a zip file, unzip it so the folder itself is named `restaurant_bar_location_data_ready`. The app expects `master_tract_features.csv` to be directly inside that folder, not one extra folder level deeper.

The current demo supports tract-level location recommendations, score explanations, source coverage, and Storefront Registry property leads. Exact asking rent, sale price, listing photos, confirmed lease or purchase availability, review sentiment, and mobile-phone foot traffic are not included in the uploaded data package.

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

The Streets map is served locally from the New York OpenStreetMap MBTiles extract.
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

Run it from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then visit `http://localhost:5001`.

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
