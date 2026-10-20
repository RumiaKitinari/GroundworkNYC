# GroundworkNYC

The Flask dashboard remains in `demo/`. The optional [FastAPI spatial backend](backend/README.md)
mounts that dashboard at `/` and adds PostGIS vector tiles with Redis caching.
It does not replace the existing routes or publish an unvalidated survival model.
Private integrated data, accounts, and model artifacts stay outside Git.
Run the backend locally using the instructions in `backend/README.md`.

## Jas — frontend and UI changes

- Added Log in, Sign up, and Continue as guest.
- Redesigned the restaurant brief while keeping the photo.
- Made Restaurant Idea, Cuisine, and Price Range required.
- Added restaurant idea suggestions and optional concept-description suggestions.
- Removed the duplicate Format control and separate per-guest pricing control.
- Improved brief layout, scrolling, validation, and saved values.
- Polished the dashboard layout, navigation, search, and location selection.
- Added System theme, NYC map bounds, Reset to NYC, and 3D.
- Corrected Aerial/3D separation, Edit Brief theme/readability, and an optional walking-graph dependency issue.
- Documented the frontend architecture, map modes, APIs, and dataset in `demo/FRONTEND_ARCHITECTURE.md`.
- Added CSV-backed existing-restaurant dots with clustering and name, cuisine, and address popups.
- Kept restaurant dots, their toggle, and their legend in 3D Buildings only; recommendation markers stay visible in every map mode, and the toggle choice is remembered.

## Changes to merge into main

- Port the `ui-concept-polish` 3D-only restaurant overlay into main's newer dashboard: the map API, clustered blue dots, detail popups, and 3D-only toggle and legend. Keep recommendation selection in every mode.
- Selectively review remaining UI-branch differences against main: duplicate Format removal, conditional local Streets availability, tighter NYC bounds and position-preserving map switches, Edit Brief presentation, and the optional walking-graph fallback. Main already has a dashboard, System theme, Aerial, and 3D.

## Data Folder

https://drive.google.com/drive/folders/12AUfzjVhSleP6oE60xbNeRY4rN6MpQhP

## OpenStreetMap PBF to CSV

The repository includes `scripts/osm_pbf_to_csv.py`, a streaming converter for
OpenStreetMap PBF extracts. It exports tagged, map-ready features (POIs, roads,
buildings, parks, land use, natural features, transit, routes, and boundaries)
while skipping untagged support nodes. Ways include GeoJSON geometry and a
representative map coordinate; relation rows retain their tags and member count
but do not attempt to assemble multipolygon geometry.

The converter uses a temporary disk-backed location index, so it does not load
the whole PBF into Python memory. Raw PBFs and `data/output/` are intentionally
gitignored. The small example in `data/samples/` shows the output format.

From the repository root on macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/osm_pbf_to_csv.py \
  ~/Downloads/new-york-260920.osm.pbf \
  data/output/osm/new-york-260920-osm-features.csv \
  --sample-output data/samples/osm_features_sample.csv \
  --overwrite
```

Run `python scripts/osm_pbf_to_csv.py --help` for all options. The
`geometry_geojson` cell is valid GeoJSON and `tags_json` preserves the complete
OSM tag dictionary for later MongoDB imports.
