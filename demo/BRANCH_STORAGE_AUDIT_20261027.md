# Frontend Branch and Storage Audit - October 27

## Remote Branches Checked

Fetched all branches and checked the server's advertised branch and pull-request
heads directly. `origin` is `RumiaKitinari/GroundworkNYC`; its fetch specification
includes every branch, not just main.

| Branch | Latest Head | Finding |
| --- | --- | --- |
| `ui-concept-polish` | `ab2e4d6`, October 8 | Latest Jashkaran UI push visible in this repository; design and 3D restaurant layer retained locally. |
| `joey-backend-code` | `85ffc45`, October 13 | FastAPI/PostGIS/Redis and limited data preview; backend integrated locally, preview does not replace the full dashboard. |
| `main` | `2935dba`, October 21 | Atharv model-code merge; no newer UI. |
| `ADM6112-complete-v1` | `40e0c0d`, October 21 | Same model upload; no additional frontend redesign. |
| `3D-visualization` | `11a8bed`, September 24 | Older frontend; not a replacement for the current merged design. |
| `groundwork-flask-demo-no-data-20260922-204438` | `fc332cf`, September 22 | Older starter demo. |
| `codex/customer-access-features` | `6a7c4bd`, October 27 | Isolated customer-access feature module; current local uncommitted improvements are preserved. |

This was a source comparison, not a destructive reset or wholesale branch merge.
No additional newer Jash UI was available to pull from these heads.

## Runtime Problem Fixed

Port 5001 was serving standalone Flask. Although PostGIS and Redis were already
running in Docker, that page did not enable the spatial service. The separate
backend environment lacked pandas, while the current feature/model environment
lacked FastAPI, Redis and PostgreSQL dependencies.

Added `run_local.py` and `backend/requirements-dashboard.txt`. The same local URL,
`http://127.0.0.1:5001`, now runs the combined FastAPI service mounting the existing
Flask app. It retains all current model/access routes and the current UI. There
is one active dashboard listener, not a competing frontend copy on port 8000.

The launcher reads private configuration without printing credentials, preserves
explicit service URLs, uses the existing Compose loopback ports by default,
checks PostGIS/Redis, and reports stale screening layers. It refuses to start a
silently disconnected Flask substitute when the configured database is unavailable.
Original backend Python 3.12 requirements remain unchanged; the combined host
runtime uses the current feature environment without downgrading NumPy/pandas.

## What Stores What

- **PostGIS:** immutable spatial snapshots, H3 geometry/attributes and published
  model batches. Named Docker volume remains intact.
- **Redis:** versioned vector-tile cache, with PostGIS fallback on cache outage.
  It is not the authoritative account, training-data or model store.
- **SQLite:** existing accounts, saved briefs, comparison selections and saved
  menus in `instance/accounts.sqlite3`; browser-local guest state is retained.
  No account migration or destructive conversion was performed.
- **Local files:** original/cleaned/integrated datasets, walking graph, MBTiles,
  model/evaluation artifacts and manifests. None was uploaded.

## Spatial Release Refresh

The active database snapshot was `screening_default_20261016` from the October 16
release. The dashboard uses `20261027T135235Z_dcc7ce69`. Published the current
default-bistro concept as `screening_default_20261027_v1`, containing 7,575 cells
at resolutions 7, 8 and 9. The original immutable snapshot remains accessible.
Only its corresponding active concept pointer changed.

Other concepts continue to use the existing current-release GeoJSON fallback
until explicitly precomputed. This does not claim that every query or analytical
calculation is cached in Redis. Huff and empirical survival predictions remain
unpublished; the guarded model requirements are unchanged.

## Verification

- Real current-release vector tile decoded to 97 features; first request MISS,
  repeated request HIT, ETag conditional request 304.
- 40 backend tests passed, including PostGIS ingestion, immutable publications,
  tile decoding and model-batch tests in a newly created disposable database.
  That test database was removed; the application database was preserved.
- 223 demo tests and five JavaScript spatial-contract tests passed.
- `pip check` found no dependency conflicts in the combined runtime.
- Browser checks exercise the same-origin vector tile and Customer Access UI
  through the combined server, not a standalone Flask test substitute.

Start or check from the repository root:

```bash
.venv/bin/python run_local.py --check
.venv/bin/python run_local.py
```

The services are loopback-local. This change does not make the prototype's
authentication production-ready. Backend test output also flags upstream WSGI
and test-portal deprecations; those are future maintenance items, not test failures.
