# Groundwork NYC

## 1. What Groundwork NYC does

Groundwork NYC is our DS 440 capstone restaurant-location intelligence dashboard.
It helps prospective operators compare NYC areas, explore space options, and
build a restaurant plan using demographic, access, competition and commercial
evidence. It supports location screening and due diligence, not success forecasts.

## 2. Current demo and supported functionality

The standard demo runs locally at **http://127.0.0.1:5001** using Flask. Guests can
explore a labeled sample or submit a restaurant brief; local accounts retain
concepts, comparisons, menus and plans. The connected workflow is:

**Brief → Explore → Analyze → Compare → Plan → Report.**

Maps, H3 heatmaps, Top 5–35 recommendations, detailed market intelligence,
property records, menu costing, economic scenarios, cash planning and PDF/CSV
exports are implemented. A private integrated data release is required for
scoring; Aerial and 3D maps also require internet access. Publishing the code to
GitHub does not provision a public hosted application.

## 3. Quick setup and startup instructions

Python **3.11** is verified for the standard local runtime. From the repository
root, create an environment only if one does not already exist:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt -r codes/requirements-access.txt
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Install the team data package first. Set `GROUNDWORK_DATA_DIR` to its integrated
release directory, or use `data/integrated/current` / the documented fallback.
The entry screen can load without the private package; analytical endpoints
require their data. See [verified local setup and artifact requirements](demo/OTIS_LOCAL_SETUP.md)
for required tables, local Streets tiles and network-access bundles. Startup does
not rebuild datasets or train models. Keep `.env`, `instance/`, datasets and
native/generated artifacts outside Git.

## 4. Architecture

- **Standard runtime:** Flask templates, vanilla JavaScript, MapLibre GL and
  locally bundled Chart.js; local accounts/workspaces use private SQLite storage.
- **Optional spatial runtime:** FastAPI, PostGIS and Redis, launched separately
  through `run_local.py` with its service dependencies and configuration. It is
  not required for standalone Flask. Follow [backend setup](backend/README.md)
  and run `.venv/bin/python run_local.py --check` before starting it.
- **Offline pipelines:** `demo/` and `codes/` prepare releases, access bundles and
  research exports. See [frontend/API architecture](demo/FRONTEND_ARCHITECTURE.md).

## 5. Data sources and releases

The active loader was checked on **November 9, 2026**. This machine resolves
`restaurant_bar_location_data_ready` and reads **2,327 tract rows and 107 master
columns**. That is the installed release, not the newest documented schema.

| Package / documentation | Tracts | Master columns | Status |
| --- | ---: | ---: | --- |
| Installed `restaurant_bar_location_data_ready` | 2,327 | 107 | Verified active local input |
| October 20 shared Drive export | 2,327 | 153 | Team-reported export; not the active local package |
| Otis completion documentation | 2,327 documented | 249 | Described completion schema; not verified as installed here |

These counts describe different artifacts; they must not be treated as an
automatic release upgrade. Changing the master requires compatible, validated
access/model bundles. See [local release verification](demo/OTIS_LOCAL_SETUP.md),
[completion notes](demo/CURRENT_MASTER_COMPLETION.md), and the
[team data folder](https://drive.google.com/drive/folders/12AUfzjVhSleP6oE60xbNeRY4rN6MpQhP).

Sources include ACS, LODES, DOHMH restaurant records, MTA, Citi Bike, pedestrian
counts, EPA walkability, OpenStreetMap and NYC commercial/property records.
The dashboard’s Sources register identifies vintages, geography and coverage.
Tract estimates and modeled H3 cells do not establish building-level demand.

## 6. Models and limitations

Live local rankings currently use **uncalibrated concept screening**. The verified
local network customer-access bundle is available; its relative index does not
predict visits or survival. Mean/median comparisons use the full eligible tract
population for the active concept and borough, before the 35-area response cap.

The native survival adapter reports `awaiting_artifact`; no validated Otis
survival model is installed. The preserved older Atharv export is not selected
by default, and unavailable predictions are not replaced with screening scores.
The stage-one XGBoost/archive-disappearance result (concordance approximately
**0.545**) remains experimental, not a validated restaurant-survival prediction
or percentage accuracy. See [survival integration](demo/SURVIVAL_DASHBOARD.md).

Synthetic properties are modeled scenarios, not listings. Sourced leads need
availability/term checks; registry filings are research records. Economic graphs
and cash plans depend on user assumptions and omit unentered costs. The
[November 2 results](reports/2026-11-02-model-results/README.md) and offline
screening/Huff maps are separate fixed research scenarios, not live scoring.

## 7. Frontend features

- Five destinations: **Explore, Analyze, Compare, Plan and Report**, with
  contextual subnavigation and shared selected-location state.
- Empty first-time briefs, explicit sample mode, accurate restoration of saved
  ideas and intentional custom concepts; local account and guest persistence.
- Synchronized Top 5/10/15/20/25/30/35 rankings and maps; Streets/Aerial/3D,
  grouped heatmaps, H3 resolutions 7/8/9 and evidence explanations.
- Market Profile overview, visual population comparisons, strengths/tradeoffs,
  compact intelligence cards and expandable demographic/transit detail.
- Distinct property record types, shortlists, menu recipes/baskets, scenario
  outcomes and break-even charts, advanced analysis, business plans and reports.
- Responsive light/dark layouts, keyboard focus, unavailable-data states and
  print/export behavior. [Product styles](demo/static/css/product.css) extend
  the existing components without a frontend framework migration.

## 8. Tests and verification

The November 9 local frontend verification passed **43 JavaScript tests** and
**107 Python regression tests**. Browser checks covered onboarding, both Top 35
inventories, map modes/heatmaps, analysis, comparisons, property filters, menu
baskets, saved economics, cash planning and real PDF generation. Layouts were
checked at 320, 390, 768 and 1440 pixels, including light/dark themes.

Run the frontend checks with Node.js 22 or newer:

```bash
node --check demo/static/js/dashboard.js
node --test backend/tests/frontend_*.test.cjs
```

Reproduce the data-backed Python regression run with the installed team package:

```bash
.venv/bin/python -m pytest -q \
  demo/test_dashboard_exploration.py demo/test_entry.py demo/test_concept_api.py \
  demo/test_dashboard_summaries.py demo/test_resident_worker_profile.py \
  demo/test_customer_access_inference.py demo/test_economics.py \
  demo/test_business_plan.py demo/test_workspace_planning.py \
  demo/test_menu_planning.py demo/test_evidence_policy.py demo/test_hex_demand.py \
  demo/test_main_integration.py demo/test_market_api.py \
  -k 'not dashboard_keeps_reported_rent_separate_from_listings and not public_opportunity_is_source_linked_but_not_confirmed'
```

Those two existing checks are explicitly excluded because the local rent
benchmarks and `data/listings/public_opportunities.csv` are absent. No fixtures
or production values were fabricated to bypass them. A clean clone needs the
private package for these data-backed tests. The
[GitHub workflow](.github/workflows/backend.yml) runs independent backend/Flask
contracts and PostGIS-backed tests with CI services; that does not certify all
private datasets, model artifacts or local production services.

## 9. What’s completed and what’s remaining

| State | Scope |
| --- | --- |
| **Completed** | Cohesive Flask frontend and the complete brief-to-report workflow; Top 35 and full-population comparisons; shared location selection; guest/local-account persistence; property, menu, economics and business-plan tools; responsive themes and exports. |
| **Implemented, input-dependent** | Local Streets tiles, walking evidence, network-access inference, sourced leads/rent benchmarks, native survival adapter and optional FastAPI/PostGIS/Redis infrastructure. Each requires its own compatible data/artifacts/services. |
| **Experimental** | Uncalibrated screening/access indices; offline walking-Huff scenarios; stage-one archive-proxy XGBoost results and fixed synthetic-property research. These do not validate demand, closure or restaurant-success probabilities. |
| **Missing locally** | Validated native survival bundle and dated snapshot provenance; the newer documented master release; published rent benchmarks and public-opportunity CSV. Local verification here uses standalone Flask, not a claim of live PostGIS/Redis coverage. |
| **Future production work** | Real email verification, production authentication/deployment hardening, HTTPS/secret management, backups, monitoring and a maintained source of verified available properties. Current accounts are local accounts. |

Next priorities are to reconcile the 107/153/249-column handoffs with explicit
release manifests and compatible bundles; improve restaurant/cuisine labels and
independently verified outcomes; validate/calibrate research before deployment;
and connect verified property and production services. No dataset migration,
model retraining or authentication replacement is part of this frontend release.

## 10. Team documentation and research links

- [Original team documentation](Readme/README.md) · [PDF](Readme/README.pdf)
- [Week 10 changes](WEEK_10_README.md) · [Otis integration notes](demo/MAIN_INTEGRATION_20261029.md)
- [Verified local setup](demo/OTIS_LOCAL_SETUP.md) · [Data pipeline / completion guide](demo/README.md)
- [Frontend architecture](demo/FRONTEND_ARCHITECTURE.md) · [Dashboard integration](demo/DASHBOARD_INTEGRATION_20261028.md)
- [Connected account workspace](demo/CONNECTED_WORKSPACE.md) · [Optional backend](backend/README.md)
- [Survival dashboard contract](demo/SURVIVAL_DASHBOARD.md) · [Model evaluation handoff](demo/MODEL_EVALUATION_HANDOFF_20261027.md)
- [November 2 model update](MODEL_UPDATE_FOR_ATHARV_2026-11-02.md) · [Results and limitations](reports/2026-11-02-model-results/README.md)
- [Offline interactive research heatmap](reports/2026-11-02-model-results/maps/heatmaps.html) — download the HTML and open it locally; GitHub displays its source.
- [Temporal survival research](codes/TEMPORAL_SURVIVAL.md) · [Feature evaluation](codes/MODEL_FEATURE_EVALUATION.md)
- [OpenStreetMap PBF conversion instructions](demo/OSM_CONVERSION.md) — preserved detailed commands, output schema and sample-output guidance.
