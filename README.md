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

## Detailed frontend changes and integration notes (2026-10-06)

This compares the **application code on original main** (`0cae33b`) with the
UI work. Current main adds only the README handoff commit `0d47f04` on top of
that code; it has not received any of the UI application changes. The pushed
`origin/ui-concept-polish` branch contains commit `4c5f0f0`. The latest preview
also includes uncommitted work in the local worktree named below.

### Changes available on the remote UI branch

| File | Change from original main | Integration detail |
| --- | --- | --- |
| `demo/templates/index.html` | Loads the new `workspace.css`; replaces the sidebar's Format picker and Edit Brief button with active idea facts in the sidebar and Edit Brief in the header. Adds header System/Light/Dark controls and account actions, groups the existing feature tabs under Explore/Research/Workspace, adds a selected-location recommendation, and offers 3D Buildings in the map selector. | Keep the new element IDs (`headerEditBrief`, `activeCuisine`, `activePrice`, `activeArea`, `selectedRecommendation`) paired with the JS. The entry photo and brief form are retained. |
| `demo/static/css/workspace.css` | New, scoped dashboard stylesheet for the sidebar, header, tabs, metrics, map/details panels, ranking table, feed cards, and responsive layouts. It also styles the Reset to NYC button, map status, and guest overlay close button. | `index.html` must load it after `dashboard.css`; copying the template alone leaves the polish unstyled. |
| `demo/static/js/dashboard.js` | Adds location matches to header suggestions; selecting a match focuses the result. Ranking rows gain keyboard activation, selected-row reveal, escaped text, and scroll preservation. Map dots and ranking rows share `selectedId`; the selected-location note uses the API's existing recommendation. | These are browser interactions over the existing `/api/dashboard` response, not new scoring or API fields. Preserve the paired template IDs and CSS. |
| `demo/static/js/dashboard.js` | Adds bounded NYC pan/zoom, Reset to NYC, 3D building extrusions, provider failure messages, and a System dashboard theme option that follows OS changes. | **This pushed version draws 3D buildings over Aerial photos.** It is an intermediate map implementation; apply the local correction below before calling the latest design integrated. |
| `demo/README.md` | Documents the intermediate 3D overlay and NYC bounds. | Its 3D description is superseded by the uncommitted correction below. |

The remote commit changes **only those four paths**. It does not change
`demo/app.py`, `demo/scoring.py`, private datasets, or the entry/brief foundation
already on main.

### Latest preview changes that are local only

These files are in `/Users/jas/Downloads/GroundworkNYC-ui-concept-polish-preview`
on this machine, on `ui-concept-polish`, **but are not in**
`origin/ui-concept-polish` or `origin/main`:

| File | Local change and reason |
| --- | --- |
| `demo/static/js/dashboard.js` | Replaces the Aerial-backed 3D overlay with two separate styles: Aerial uses Esri raster imagery and dots without buildings; 3D fetches OpenFreeMap Positron vector streets and adds building extrusions without satellite imagery. It checks the style, shows a failure message and falls back to Aerial when needed. Style switching retains the same result set and selected location. Also fixes initial restoration of the System dashboard theme choice. |
| `demo/static/css/dashboard.css` | Fixes Edit Brief input and dropdown contrast. Initial entry/brief follow system appearance when there is no dashboard choice; Edit Brief opened from the dashboard inherits its resolved Light, Dark, or System appearance. The form layout and values are unchanged. |
| `demo/osm_network.py` | Checks whether the optional walking graph exists before importing `networkx`. An absent optional graph then leaves walking evidence unavailable instead of failing the dashboard request. No scoring formula changed. |
| `demo/README.md` | Corrects the 3D setup description to vector streets without Aerial imagery and adds a UI handoff with review steps. |
| `demo/FRONTEND_ARCHITECTURE.md` | New, untracked guide to Flask, the dashboard API, the six integrated CSVs, map modes, browser state, and the deterministic model. |

The worktree also has an untracked `checkpoints/` directory containing local
handoff material. It is **not** one of the application or documentation files
to integrate. No local-only UI fix has been committed or pushed.

### How to integrate the complete version

1. Fetch and review the pushed delta with `git diff 0cae33b...origin/ui-concept-polish -- demo/`.
   In the local preview worktree, separately review `git status`, `git diff`,
   and the untracked architecture guide. A remote branch comparison cannot
   show those uncommitted files.
2. Arrange for the reviewed local fixes to be committed/shared before merging.
   Bringing over only `4c5f0f0` keeps the aerial-plus-buildings version and
   misses the theme and optional-graph fixes. Keep any newer main edits when
   resolving conflicts; do not reset or overwrite either worktree.
3. Keep private data and generated files out of Git. The Flask app expects the
   private package at `data/integrated/restaurant_bar_location_data_ready/`:
   `master_tract_features.csv`, `source_catalog.csv`, `feature_readiness.csv`,
   `entities/current_restaurants.csv` (the original package file),
   `entities/current_storefronts.csv`, and
   `entities/subway_stations_weekly_activity.csv`. Local MBTiles, walking graph,
   listings, and `instance/` files are separate optional/runtime data.
4. Test with the real dataset: `/api/dashboard` must return locations; check
   map tiles and clickable dots, rankings and selected-location details,
   Edit Brief values/submission/refresh, both dashboard themes and System,
   and Aerial/3D switching while a location is selected. A homepage HTTP 200
   does not establish that data, tiles, or interactions work.

Main's setup remains in [demo/README.md](demo/README.md). This section records
the handoff; it does not add the UI implementation to main.
