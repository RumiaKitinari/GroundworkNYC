# GroundworkNYC

## Flask dashboard and UI branch handoff

The Flask dashboard lives in `demo/`; use [demo/README.md](demo/README.md) for
the data setup and launch steps for **main's current code**. Main includes the
entry screen and concept brief (`0cae33b`). It does not yet include the newer
dashboard layout or 3D map work.

The newer UI is on [`ui-concept-polish`](https://github.com/RumiaKitinari/GroundworkNYC/tree/ui-concept-polish).
Its pushed commit, `4c5f0f0`, is one commit after `0cae33b`. It adds the
workspace layout, reorganized controls and navigation, location search and
selection improvements, NYC map bounds, and a 3D Buildings option. Compare the
branches without changing your checkout:

```bash
git fetch origin
git log --oneline origin/main..origin/ui-concept-polish
git diff --stat origin/main...origin/ui-concept-polish
git diff origin/main...origin/ui-concept-polish -- demo/
```

**The remote UI branch is not the full current preview.** Later fixes are still
uncommitted in the local `ui-concept-polish` worktree on this machine at
`/Users/jas/Downloads/GroundworkNYC-ui-concept-polish-preview`. They separate
Aerial imagery from the vector 3D street map, correct Edit Brief theme/field
readability, and let the dashboard run without the optional walking graph.
That worktree also has an updated `demo/README.md` and a new
`demo/FRONTEND_ARCHITECTURE.md`. A merge or cherry-pick of `4c5f0f0` alone will
miss those fixes. Review its `git status` and diff with the UI owner before
integrating; do not reset or overwrite that worktree.

The private integrated CSV package is needed to test live location results.
It, the optional map tiles and walking graph, and instance files stay outside
Git and must not be included in a UI merge. This README change is only a
pointer for the team; it does not merge UI code into main.

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
