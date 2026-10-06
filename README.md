# GroundworkNYC

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

## Changes to merge into main

- Merge the `ui-concept-polish` dashboard polish and its Aerial/3D, System theme, Edit Brief, and optional walking-graph fixes after review.

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
