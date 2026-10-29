# Week 10: Otis Changes And Briefing Handoff

**For Atharv and the Groundwork NYC team. Updated October 29, 2026.**

This branch combines the current local implementation with the existing team
history. It preserves Jas's frontend design and Joseph's spatial-service work,
and adds the local feature engineering, model experiments, integration and
workflow improvements described below. `main` is not changed by this push.

**Timing:** the October 27-28 research runs and dashboard improvements are the
Week 10 progress. This branch also carries earlier local-only data preparation
and infrastructure work that had not all been shared in Git. Those earlier
tools are supporting context, not claims that every feature was built this week.

## Briefing Summary: What To Say

1. **We reran and evaluated our own saved model outputs.** A matched comparison
   uses 10,743 restaurants, identical neighborhood folds, fixed settings and
   dated core features. Saved model replay checks make the results auditable.
2. **We improved temporal feature provenance.** Population density, income,
   job density and walkability are selected using historically available
   sources rather than simply backdating today's master to every opening.
3. **We tested inverse walkability and Huff across the full synthetic inventory.**
   Four concepts and 16 one-factor checks demonstrate responses to price,
   service format, customer audience and trading period. Coverage is reported
   separately from accuracy.
4. **We made missing-data behavior explicit.** Unsupported cuisines, uncertain
   labels, unavailable routes and missing features no longer justify invented
   precision or fabricated zero values. General-fit fallback is labeled.
5. **We connected the dashboard to actual eligible property scenarios.**
   Property markers, ranking rows, details and reports use the same records;
   arbitrary synthetic-result truncation is removed.
6. **We added an integrated planning workflow.** Property shortlists, menu
   baskets, saved economic scenarios, comparisons and decision reports now
   work together without silently changing a user's budget or assumptions.
7. **Logged-in work persists in the database.** Business profiles, concepts,
   menus, property shortlists and scenarios survive a fresh browser session;
   guest work remains device-local.
8. **The combined local infrastructure is exercised end to end.** FastAPI
   mounts Flask, PostGIS serves versioned spatial layers, Redis caches tiles,
   and a release gate rejects stale spatial outputs and unsafe staged files.

**Do not say:** verified closure prediction, validated business-success
probabilities, proven financial returns, real available synthetic listings,
independent final holdout, or an accuracy improvement established by tuning.
The live demo remains screening-based while research-model validation continues.

## October 29 Demo-Polish Addendum

### Menu Studio And Business Plan

The Plan group now includes **Menu Studio: Plan / Analysis / Preview**. Each
dish has a Recipe Cost dialog with ingredient quantities, matching unit prices,
batch yield and waste allowance. Applying the calculation explicitly updates
ingredient cost per portion. Dishes can be duplicated, reordered and removed;
Undo restores the removed dish and its own recipe/basket metadata without
overwriting other financial edits. Analysis shows ingredient-only contribution,
cost percentages, missing prices/costs and loss-making items. It does not invent
sales popularity or classify dishes from nonexistent transaction data.

The Workspace group now has a separate **Business Plan** tab. It uses the
current Economics draft or a selected saved scenario, then adds starting cash,
one-time opening costs, monthly owner draw and an opening-volume ramp. Two
charts show month-end cash balances under entered and +/-20% volume assumptions,
and monthly cash in/out. The view includes shortfall timing, additional cash
needed, expandable monthly detail, CSV export and a six-item due-diligence
checklist. It will not generate a cash plan without valid operating assumptions.
Capacity caps, month-zero shortfalls and incomplete/deleted scenarios are handled
explicitly. Costs and guest volumes are assumptions, not trained profit forecasts;
purchase financing is not added automatically.

Recipes, cash-plan assumptions and checklist state use the existing private,
revisioned account database. Fresh-browser checks confirm restoration; separate
accounts and concept/transaction plans remain isolated. The detailed tools stay
inside a dialog, subtab or expandable section to preserve the current design.

Implementation and formulas: [Menu and business planning](demo/MENU_WORKSPACE.md).
Verification: **433 Python tests pass, 2 skip; 22 JavaScript unit tests pass**.
Chrome and WebKit desktop/mobile checks cover recipe application, duplication,
Undo, charts, account restoration and existing map/property/explorer workflows.
No training data, credentials, account databases or native model files are added
to this push. The release gate remains screening-only, not survival validation.

**Later main-branch review:** [Selective integration notes](demo/MAIN_INTEGRATION_20261029.md)
document the new team work at `d1005ee`, what was ported and what remains separate.
Resident/workforce comparisons, transit details, competition breakdowns and
full storefront research now extend this dashboard without replacing its
property, heatmap, menu, economics or account workflows. The optional tract
prediction CSV loader is supported, but its documented private export is not
present locally; no survival predictions have been fabricated or activated.

The feature heatmap presentation now uses thin hex borders, restrained fills,
and a separate hover outline. Hover shows the feature score and evidence
coverage; tapping a local cell opens a closable detail popup. Sector selection
retains the existing zoom-to-local-cell interaction. The popup labels the
surface as a tract-based estimate rather than suggesting storefront precision.

While a feature heatmap is active, redundant inventory/point-color controls
and existing-restaurant controls are hidden. Property clusters and other
property pins are hidden; only the selected property's marker stays visible
above the heatmap and city boundary. Turning the feature heatmap off restores
the property controls and inventory. The legend uses a hex symbol. Streets,
Aerial, 3D, pan, zoom and fullscreen behavior remain available.

This is a presentation/interaction change, not a retraining, new scoring
formula, verified demand model, or merge of subsequent team model changes.
The regression suite includes JavaScript tests for hex-layer
cleanup and hover styling; Chrome/WebKit checks cover compact controls,
desktop/mobile layout and touch details.

## 1. Model Development And Results

### What Changed

Earlier local experiments mixed current context, proxy outcomes and several
feature policies. We now retain frozen inputs, explicit experiment plans,
identical comparison rows/folds, saved native fold models, prediction replay
and source hashes. These are our local outputs; this evaluation does not depend
on receiving a collaborator's model files.

The frozen cohort has 18,860 identities. The matched comparison excludes 3,269
reserved-assessment rows and 4,848 development rows without all four dated
features, leaving **10,743 restaurants**. All configurations use the same three
neighborhood folds, proxy labels and fixed 200-round XGBoost AFT settings.

| Matched configuration | Within-fold concordance | Interval NLL |
| --- | ---: | ---: |
| Local legacy, 50 features | 0.5305 | 0.649911 |
| Current context, 35 features | 0.5326 | 0.650660 |
| Current-vintage core, 4 features | 0.5275 | 0.650308 |
| Opening-time core, 4 features | 0.5481 | 0.648012 |
| Training-fitted constant | 0.5000 | 0.648810 |

The dated core improves historical defensibility. Its concordance difference
versus the legacy baseline is +0.0176, but the paired 95% interval
[-0.0056, +0.0412] includes zero. **This does not establish predictive superiority.**
The same-four-variable vintage comparison favors dated inputs in an exploratory
development diagnostic, not an independent confirmation.

Replay validation checked **36 fold models and 161,145 saved prediction rows**.
Three disappearance definitions yield 1,797, 1,292 and 1,141 proxy events;
these change the target rather than verifying permanent closure. Only 3,345
matched records have identifiable three-year proxy outcomes; resolved-subset
Brier/calibration figures do not describe the whole population.

All cohort records appeared in earlier research cross-validation. The reserved
rows were excluded from these fits, but are not a globally untouched final
test. Earlier full-cohort optimization metrics are not directly comparable
with this matched complete-case experiment.

**Code:** [Matched evaluation](codes/evaluate_matched_results.py),
[scenario evaluation](codes/evaluate_results_scenarios.py),
[replay validation](codes/validate_results_evaluation.py),
[frozen research runner](codes/run_archive_research.py),
[experiment plan](codes/results_evaluation_plan.json).

**Background:** [Model optimization and its limitations](demo/MODEL_OPTIMIZATION_20261027.md),
[training readiness](demo/SURVIVAL_READINESS.md).

## 2. Feature Engineering And Data Quality

The active local integrated master has **2,327 tracts and 249 documented
columns**. It is the primary context source; individual cleaned sources remain
reference/fallback inputs. Full entity, route and historical evidence tables
remain separate where their grain is not one row per tract. A tract master
alone is not a complete historical restaurant-survival training table.

### Week 10 Repairs And Audits

- Generated a source-dated four-feature table for all 18,860 cohort identities.
  Coverage: population density 14,012; income 13,832; job density 13,138;
  walkability 18,850; all four 12,977. The stricter development evaluation uses
  10,743 after excluding reserved records. Missing historical values stay missing.
- Audited 38 context features: four have supported historical alternatives;
  34 still lack replacements in the historical allowlist.
- Produced 49 corroborated coordinate-restoration candidates using stable
  CAMIS/name/address identities and unique tract containment. These remain an
  **offline candidate**, not a silently published change to live scoring.
- Nine archive-based cuisine suggestions remain unapproved. The full review
  queue contains 5,946 unique restaurants with overlapping taxonomy, provenance
  and coordinate concerns; no cuisine is invented from a name alone.
- Reconstructed capture-time same-name address counts for review, but did not
  relabel them as verified chain ownership or promote them into training.
- Joined outcome leads to cohort identities. No independently verified
  permanent-exit records were created from disappearance, temporary inspection
  closures, liquor-license records or Foursquare status alone.

### Earlier Local-Only Preparation Included Here

Repeatable publisher checks, versioned integration, the master-spec completion
tools, historical inspection/archive processing, identity review and lawful
external-source matching tools are included so teammates can reproduce the
pipeline. Source snapshots, private exports and account data are not in Git.
The release audit checks structural validity and rejects SAMPLE contamination;
it does not convert data availability into scientific training readiness.

**Details and file names:** [Feature readiness](demo/FEATURE_READINESS_20261028.md),
[master completion](demo/CURRENT_MASTER_COMPLETION.md),
[data vintages](demo/DATA_VINTAGES.md),
[repeatable maintenance](demo/maintain_data.py),
[feature repair builder](codes/prepare_feature_repairs.py).

## 3. Inverse Walkability, Huff And Fallbacks

Walkability describes the area's walking environment. Inverse walkability is
the concept-specific customer-access calculation using the directed local OSM
network, resident/job origins, affordability and concept assumptions. These
are weighted opportunities, **not unique visitors, observed spending or revenue**.
Price and format matter independently of cuisine. Current network calculations,
cuisine and synthetic rents are not backdated into first-stage training.

Four complete 1,000-property synthetic inventories were assessed against all
2,327 tract origins, without sampling the candidate inventory:

| Concept | General fit | Cuisine screening | Network access | Repaired-anchor Huff |
| --- | ---: | ---: | ---: | ---: |
| Neighborhood cafe | 1,000 | 1,000 | 986 | 742 |
| Office lunch | 1,000 | 1,000 | 986 | 704 |
| Casual dinner | 1,000 | 1,000 | 987 | 742 |
| Premium dinner | 1,000 | 1,000 | 988 | 853 |

Audited restaurant anchors repaired ten failed competitor-centroid route
targets. These offline experiments increased assessable coverage, not proven
accuracy; they have not silently replaced live route caches. Missing competitor
routes still withhold affected assessments rather than inflate opportunity.

Sixteen one-factor checks confirmed responses to price, format, audience and
trading period. A 20% price increase never increased affordability-adjusted
opportunity mass. A conservative uncertain-cuisine competitor stress test
retained only 4-76% of the top 50, showing that cuisine-label quality is a major
remaining uncertainty, not something additional tuning can simply fix.

The evidence policy distinguishes general fit, limited cuisine evidence,
cuisine-supported fit and insufficient evidence. Unsupported cuisines can use
clearly labeled broader fit; missing inputs do not become zero-demand claims.

**Code:** [Network/Huff](codes/network_huff.py),
[access coverage experiment](codes/audit_access_optimization.py),
[dashboard access adapter](demo/customer_access_inference.py),
[fallback policy](demo/EVIDENCE_FALLBACK_POLICY.md),
[policy implementation](demo/evidence_policy.py).

## 4. Dashboard Changes: Section By Section

Jas's visual direction and top navigation remain. This is still Flask templates
and vanilla JavaScript, not React. The changes make each section serve a
different decision rather than repeat score explanations.

| Section | What is improved in this branch | Main implementation |
| --- | --- | --- |
| Restaurant Brief | Concept-specific context, cuisine/diet/style/price inputs feed one consistent request; exact guest spend and dollar tiers remain supported. | [Dashboard JS](demo/static/js/dashboard.js), [template](demo/templates/index.html) |
| Overview | Full eligible property scenarios, consistent map/list/details, numbered ranks versus cluster counts, address/property-ID search and persistent selected marker. No arbitrary 48-scenario backend cap. | [Backend matching](demo/app.py), [integration notes](demo/DASHBOARD_INTEGRATION_20261028.md) |
| Maps | Separate Streets/Aerial/3D; pan, zoom, fullscreen and reset preserved. NYC partition in every mode; tiny display-only tract seams cleaned; dots and numbers stay above boundary lines. | [Geography](demo/map_geography.py), [ordering tests](backend/tests/frontend_map_order.test.cjs) |
| Heatmaps | Select actual feature surfaces: demand, customer fit, accessibility, market gap, competition balance, walkability, inverse walkability, commercial fit and location score. Unsupported coverage is unavailable, not colored as zero. | [Hex surfaces](demo/hex_demand.py), [heatmap notes](demo/HEATMAP_ECONOMICS_20261028.md) |
| Market Profile | Real tract demographics, jobs, transit/activity context and source-specific coverage; selected-location context stays synchronized. | [Scoring](demo/scoring.py), [dashboard API](demo/app.py) |
| Customer Access | Area and property access are distinguished; resident/workplace reach, route coverage, origin areas and trading assumptions remain visible and interactive. | [Access adapter](demo/customer_access_inference.py), [access engine](codes/customer_access.py) |
| Competition | Search the actual recorded supply and inspect cuisine-label coverage; uncertain labels do not become a false verified market gap. | [Competition endpoint](demo/app.py), [evidence policy](demo/evidence_policy.py) |
| Compare | Area comparisons remain; a separate property shortlist compares up to four specific spaces, prices, floor area, kitchen information, access and area scores. | [Planning JS](demo/static/js/planning.js) |
| Properties | Full eligible synthetic inventory plus distinctly labeled sourced/registry records; save/remove/open properties. Records outside the current search remain saved and labeled, not silently deleted. | [Matching API](demo/app.py), [property notes](demo/PROPERTY_DATA.md) |
| Economics | Explicit selected-lease-rent transfer; daily revenue/cost, profit, MR/MC and price sensitivity charts; break-even and capacity checks; named scenario save/load/remove and curve comparisons. Lease and purchase assumptions stay separate. | [Scenario calculator](demo/economics.py), [planning workflow](demo/CONNECTED_WORKSPACE.md) |
| Menu Studio | Editable/custom dishes, cost-based pricing, ingredient margin, section balance, shared ingredients, preparation complexity, per-guest baskets, spend transfer, CSV and print preview. Unsupported cuisine ideas remain unavailable rather than fabricated. | [Menu catalog](demo/menu_catalog.py), [planning JS](demo/static/js/planning.js) |
| Decision Report | Selected property, alternatives, menu, basket, current assumptions, saved-scenario results, a profit-volume graphic, release identifier and outstanding checks. Print waits for financial results. | [Report workflow](demo/static/js/planning.js) |
| Sources | Actual vintages, geography and coverage; separates screening, network scenarios, synthetic inventory and unavailable survival inference. | [Sources rendering](demo/static/js/dashboard.js) |
| Settings / Accounts | Private business profile and database-backed concepts, menus, shortlists, baskets and financial scenarios. Fresh-browser recovery, CSRF/revision checks, conflict reconciliation, sync status and logout save attempt. Guests remain device-only. | [Workspace schema](demo/workspace_schema.py), [account API](demo/app.py) |

Economic graphs are deterministic user-assumption scenarios, not fitted demand
or profit forecasts. Menu ingredient margin excludes rent, labor and other
operating costs. Synthetic inventory is not evidence that a property is listed
or available. Source-reported property availability is not owner confirmation.

## 5. Infrastructure And Storage: What Is Actually Connected

- `run_local.py` starts one FastAPI service mounting Flask at `/`, preserving
  existing dashboard routes while exposing the spatial API.
- PostGIS stores immutable spatial publications. Redis caches repeat tile
  requests and is replaceable; it is not the database for account records.
- Accounts/workspaces remain in private `instance/accounts.sqlite3`. Passwords
  are hashed; workspace ownership comes from the authenticated session. New
  planning fields extend the existing JSON contract rather than creating a
  second disconnected account store.
- Workspace saves use CSRF, bounded validation and version checks inside a
  write transaction. Three-way reconciliation retains independent remote
  edits and intentional local deletions; same-field conflicts retain this
  editor's draft. Account isolation and fresh-login recovery have tests.
- Spatial metadata pins source release and scoring-code fingerprint. Stale
  precomputed screening tiles are rejected; the dashboard can fall back to
  current GeoJSON. Publishing uses new snapshot names, not overwriting old runs.
- `check_release.py` checks services, integrated structure, model deployment
  status, stale spatial publications and unsafe staged blobs before a push.
- Chart.js is locally bundled with its MIT license; the graphs need no CDN.
  Online aerial/3D tiles remain external dependencies.

**The live site is not serving the offline archive-AFT research models as
verified survival predictions.** The inference adapter remains guarded and
reports `awaiting_artifact` until an appropriate validated artifact is supplied.

See [Backend README](backend/README.md), [Release Readiness](backend/RELEASE_READINESS.md),
[Connected Workspace](demo/CONNECTED_WORKSPACE.md), and [release gate](check_release.py).

## 6. Verification And How To Review

The October 28 local check passes the screening-demo release gate: PostGIS and
Redis available, 2,327/249 master structure valid, no stale active screening
layer and no unsafe staged content. A warning about unavailable verified
survival inference is expected and must not be described as a passed scientific
validation.

Final local regression result: **387 Python tests passed, 2 dedicated database
tests skipped, and all 16 JavaScript tests passed**. Two upstream framework
deprecation warnings remain; they are not test failures.

Chrome and WebKit desktop/mobile checks cover all eleven dashboard views,
Streets/Aerial/3D, feature heatmaps, account restoration in a fresh browser,
property saving, three financial scenario overlays, menu baskets and reports.
Tests use temporary account databases, not personal production accounts.

Run from the repository root in the matching project environment:

```sh
.venv/bin/python -m pytest codes demo backend/tests -q
node --test backend/tests/frontend_hex.test.cjs backend/tests/frontend_planning.test.cjs backend/tests/frontend_map_order.test.cjs
.venv/bin/python check_release.py
```

Two dedicated PostGIS integration tests require a configured disposable test
database and are skipped without it. Local service checks and browser checks
do not replace those isolated database tests.

### Starting The Same Application

1. Follow [Data Setup](demo/README.md#data-setup) to restore the team's private
   integrated package. The active local release is
   `data/integrated/current/`, with a baseline fallback at
   `data/integrated/restaurant_bar_location_data_ready/`.
2. Install `backend/requirements-dashboard.txt`, retain a private `.env`, and
   start the Compose database/Redis/migration services as documented in
   [backend setup](backend/README.md). Do not copy someone else's account DB.
3. Restore required private map/network/access/property artifacts from the
   team package or build them using the documented tools. A bare clone cannot
   recreate an excluded OSM extract, model artifact or generated property file.
4. Run `.venv/bin/python run_local.py --check`, then
   `.venv/bin/python run_local.py`. Open `http://127.0.0.1:5001/`.

Research evaluation additionally needs `codes/requirements-temporal.txt`,
`codes/requirements-results.txt` and the private frozen inputs. Use new output
directories for new runs; do not overwrite the saved benchmark. Reproduction
commands and source/output paths are in the linked research documents.

## 7. What Is Still Needed For The Results Stage

1. Independently support baseline operation, opening-time origins, identity
   changes and permanent exits/censoring. Inspection disappearance is a proxy,
   not confirmation of closure.
2. Review remaining historical feature gaps, chain reconstruction and cuisine
   labels. Promote coordinate candidates only after review and rebuilding
   dependent competition/route outputs.
3. Protect genuinely independent outcome evidence before claiming final
   evaluation; the existing exposed cohort cannot become untouched by splitting
   it again.
4. Validate/calibrate second-stage attraction and Huff assumptions against
   permitted observed choice/activity evidence if it becomes available.
5. Keep synthetic property demonstration separate from live listing access.
   Production property feeds, licensing and listing verification remain open.
6. Review this branch before any later main merge. Deployment still needs
   persistent private storage/backups, HTTPS, secret management and stronger
   production account protections.

## Push Scope

Included: source code, tests, authored configuration/plans, documentation and
the licensed chart library. Excluded: datasets, personal Word/PowerPoint files,
`Miscellaneous/`, `deliverables/`, native trained models, per-restaurant
predictions, raw/integrated/generated data, `.env`, account stores and caches.
The existing repository's small OSM format example is not newly uploaded
training data and is never substituted into the master.
