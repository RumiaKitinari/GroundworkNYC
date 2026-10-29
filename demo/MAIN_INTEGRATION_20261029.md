> Upstream handoff notes from Otis’s machine. For this checkout’s actual
> artifacts and verification, see [OTIS_LOCAL_SETUP.md](OTIS_LOCAL_SETUP.md).
> The older Atharv CSV exists here but is deliberately not activated.

# Main Branch Review And Selective Integration

Reviewed `origin/main` at `d1005ee2734549407a0096068f740c67468f8258`
against Otis branch `d72c79b` on October 29, 2026. Their common ancestor is
`2935dba`. This is a selective port, not a wholesale merge or a replacement
of Otis's current dashboard. Private datasets and account state are untouched.

## Material Differences

| Main change | Decision for the Otis dashboard |
| --- | --- |
| Resident/worker explorer with a second-area comparison | Ported. Available in Market Profile under expandable Resident & Workforce Details; includes income uncertainty, resident age, job age/earnings/industry and explicit missing values. |
| Subway, bike, pedestrian and taxi details | Ported under expandable Transit & Activity Details. Adapted to the local rolling-month columns and actual source dates; zone observations remain distinct from tract measurements. |
| Competition explorer and latest-record CAMIS deduplication | Ported into the dedicated Competition tab, not duplicated across tabs. Includes cuisine breakdown bars, list filtering/search, pagination and area comparisons. Shares use the full tract inventory, not filtered rows. |
| Storefront research explorer | Ported as a collapsed, separate research section within Properties. Uses all 29,834 local registry records, not the other checkout's vacancy-only extract. Distinguishes 4,493 reported vacant from 25,341 reported not vacant records. These are filings, not available lease offers. |
| Atharv-format tract CSV display loader | Ported as an explicit optional display adapter. Joins by validated unique 11-digit GEOID, rejects invalid probabilities/ranks, labels archive-proxy estimates and does not change screening scores/order. The native historical inference guard remains. |
| `GROUNDWORK_DATA_DIR` / model configuration | Ported shared dataset path selection across dashboard, map, explorers and spatial publication. External paths are not exposed as absolute filesystem paths in metadata. A release check refuses to treat a separately configured, unaudited package as the canonical audited release. |
| Boundary-cache invalidation | Ported file mtime/size cache signatures, while retaining Otis's cartographic seam cleanup and marker-over-boundary ordering. |
| Missing optional neighbor-income column | Ported the `fillna` fallback correction without replacing historical features or training rules. Missing income stays missing when no neighbor estimate exists. |
| Optional walking graph dependency | Ported the small missing-graph fallback fix. |
| Other main CSS/template replacements | Not copied wholesale. They do not contain Otis's current property inventory, feature heatmaps, economics, menu planning and extended account workspace. |
| Native-model preparation scripts / training replacement | Not substituted for Otis's stricter cohort/training workflow. The two artifact contracts and label assumptions differ. No model was retrained in this integration. |
| Old Django/MongoDB/script cleanup | Left separate; unrelated tracked files were not deleted to obtain UI improvements. |

## Model Artifact Still Needed

Main's `demo/ATHARV_DEMO.md` describes an October 29 locally generated export,
not an artifact checked into Git. Its documented CSV is:

```text
data/output/atharv_model/presentation_20261029/model/tract_survival_scores.csv
```

That file is not present in this checkout. The adapter is implemented and
tested, but the current dashboard still reports `awaiting_artifact`; no example
probabilities, proxy models or fake substitutes were activated.

After obtaining a trusted copy of the export and its provenance/run metadata,
set `GROUNDWORK_ATHARV_SCORES` to its local path before starting the server, or
add `tract_scores` to the existing private dashboard-model pointer. Keep these
files out of Git. The exact required columns are `geoid`, `borough`, `nta_code`,
`survival_3yr` and `survival_3yr_rank_in_borough`.

The CSV path displays a three-year **archive-disappearance proxy estimate**.
It is not proof of verified permanent closures, a calibrated business-success
probability, an independent holdout result or a replacement for concept-specific
screening. It never modifies the opportunity ranking. The release gate reports
that qualification separately if an export is activated.

## Verification

- Source-backed API tests compare resident/workforce, transit and registry
  responses with this checkout's actual full integrated sources.
- Fixture tests check explicit missing/zero/nonfinite values and duplicate
  restaurant status resolution. Tests no longer assume fixed missing counts,
  a vacancy-only source, or old-only monthly columns from another machine.
- Export fixtures verify GEOID matching, invalid/missing export rejection and
  that proxy probabilities cannot reorder or replace screening scores.
- Chrome/WebKit desktop/mobile checks exercise comparisons, transit details,
  competition filters/search, mixed-status registry filters and empty results.
- Existing full-dashboard and heatmap browser checks retain all eleven views,
  all property scenarios, menu pricing and all three map styles.

Primary files: `demo/app.py`, `demo/static/js/explorers.js`,
`demo/static/css/explorers.css`, `demo/atharv_export.py` and the associated
`demo/test_*explorer.py`, profile/transit/export/integration tests.
