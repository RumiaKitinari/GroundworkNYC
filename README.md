# Groundwork NYC

## About Groundwork NYC

Groundwork helps prospective restaurant operators explore New York City locations, compare neighborhood conditions, research spaces, and develop a restaurant business plan.

## Features

- Create and edit restaurant concepts, cuisine preferences, budgets, and dining formats.
- Search NYC locations and explore ranked location recommendations.
- Explore interactive maps and neighborhood heatmaps.
- Review neighborhood demographics, workforce, and market comparisons.
- Investigate transit and customer access.
- Explore nearby restaurants and cuisine competition.
- Research commercial-property records, sourced leads, and space scenarios.
- Compare locations and maintain saved shortlists.
- Plan menus, recipes, pricing, and ingredient costs.
- Model financial scenarios, cash requirements, and break-even outcomes.
- Build business plans and generate reports with PDF and CSV exports.
- Use local accounts and saved workspaces, or explore an explicitly labeled guest sample.

Location scores are screening indicators; synthetic property scenarios are not real listings.

## Getting Started

Use Python 3.11 and install the team data package. Set `GROUNDWORK_DATA_DIR` to its integrated release directory, or place it at `data/integrated/current`. See [local setup](demo/OTIS_LOCAL_SETUP.md) for package requirements.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt -r codes/requirements-access.txt
.venv/bin/python -m flask --app demo/app.py run --host 127.0.0.1 --port 5001 --no-reload
```

Open http://127.0.0.1:5001. Analytical features require the team data package.

## Tech Stack

- Frontend: HTML, CSS, vanilla JavaScript
- Maps: MapLibre GL
- Charts: Chart.js
- Backend: Python + Flask
- Scoring: Existing Python screening logic
- Accounts and saved workspaces: SQLite
- Data: Integrated NYC dataset

## Project Progress

- [x] ~~Build interactive NYC maps and heatmaps~~
- [x] ~~Implement restaurant concept onboarding and editing~~
- [x] ~~Separate sample exploration from saved restaurant briefs~~
- [x] ~~Add location recommendations and comparisons~~
- [x] ~~Connect neighborhood demographics and workforce analysis~~
- [x] ~~Add transit and customer-access exploration~~
- [x] ~~Implement restaurant search and cuisine filtering~~
- [x] ~~Distinguish property scenarios, sourced leads, and research records~~
- [x] ~~Add saved shortlists and local workspaces~~
- [x] ~~Implement menu costing and pricing planning~~
- [x] ~~Add financial scenarios and break-even charts~~
- [x] ~~Connect business plans and report exports~~
- [x] ~~Implement responsive layouts and light/dark themes~~

- [ ] Reconcile and validate the latest team dataset
- [ ] Confirm release manifests and compatible customer-access bundles
- [ ] Integrate a validated survival model when available
- [ ] Validate and calibrate experimental research before production use
- [ ] Improve verified commercial-property coverage
- [ ] Verify sourced availability, terms, and rent benchmark coverage
- [ ] Implement real email verification and password recovery
- [ ] Prepare production deployment and security
- [ ] Establish production backups and monitoring
- [ ] Complete final end-to-end verification and release preparation
