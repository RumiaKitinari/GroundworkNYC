# Dashboard Data and Interaction Audit

Checked October 5, 2026 against the active integrated release and the local
Flask/JS implementation. This is a source-to-display contract, not a claim of
predictive accuracy. The dashboard should never turn an unavailable field into
a zero or imply that a tract score is a verified property outcome.

| View | Displayed values and source | Current boundary |
| --- | --- | --- |
| Overview | The top 24 eligible tracts and their score components come from `master_tract_features.csv` through `ScreeningModel`. Walkability rescales EPA's built-environment index. Business Draw is a concept-specific index. Streets use local OSM MBTiles; Aerial and 3D use online providers. | Scores are relative, uncalibrated screening indices, not predicted visits, revenue or success. Map markers are tract centroids, not available addresses. Saved tracts outside the top 24 are fetched separately for Compare. |
| Market Profile | Residents and income are 2020-2024 ACS five-year tract estimates; income includes its margin of error. Jobs are 2023 LODES workplace counts. Subway entries use the station and week shown in the source catalog. Citi Bike departures are August 2026. Pedestrian counts are from the nearest monitored site. | A nearest pedestrian monitor is not tract-wide foot traffic; its observation date is not present in the current tract table. The separate 2025 subway daypart sample is not the current weekly station total. Missing measurements display as unavailable. |
| Competition | Restaurant inventory and cuisine labels come from the integrated, deduplicated DOHMH entity file. The view shows tract and NTA counts plus cuisine-label coverage. | Inspection-derived operating status is not proof that every restaurant is open today. Low cuisine-label coverage weakens cuisine-gap claims; scarcity is not measured customer demand. |
| Compare | Saved tract rows use the same screening model as Overview, including saved locations outside the current top 24. | This is a comparison of tract indicators, not a property or business-outcome comparison. Four locations can be saved per concept. |
| Properties | Vacant storefront research records come from the integrated Storefront Registry. One NYCHA public leasing opportunity is checked against its official page as of October 6, 2026. Optional source-linked broker or owner listings load from `data/listings/verified_properties.csv` or authorized provider snapshots only when source URL and recent check date are present. The displayed area score is the matched tract score. | Registry rows are not offers to lease or sell. The NYCHA asking rent and availability are source-reported, not independently confirmed, and do not represent citywide coverage. Partner listings still need availability, price, contact and photo-rights checks. Missing fields stay unavailable. |
| Economics | Rent and purchase budgets, guest spend and operating costs are user inputs. Required sales and covers use the entered assumptions. Lease view also shows the NYC DOF 2024 reported median occupied-storefront rent per square foot for the selected tract, when published. | The tract median is historical context, not current asking rent or a property quote. There is no verified site rent, loan model, tax estimate, or profit/survival prediction. Purchase view does not invent financing or sale listings. |
| Menu Studio | Dish ideas come from the editorial catalog; optional review mentions require a rights-cleared private input. Prices, costs and item margins come from the user. | Catalog presence is not local demand or dish popularity. Review signals are unavailable unless the optional evidence file passes its thresholds. Dietary compliance requires operator verification. |
| Report | Selected tract score, component values, flagged risks, saved alternatives and user brief are assembled from the current dashboard response. | The report is a screening snapshot. Its evidence-strength percentage is not model accuracy. Property availability and transaction terms require separate due diligence. |
| Sources | Source rows and vintages come from the integrated `source_catalog.csv`. Missing listing and market signals are enumerated by the backend. | Download date and observation period differ. An updated raw source is not integrated until its transform and joins are published. |
| Settings | Appearance is browser-local. Saved concepts, comparisons and menus are browser-local for guests and synchronized to the local account database for signed-in users. | Local accounts are demo-only. A failed sync leaves a local copy and visible status; deployment-grade recovery and concurrent-edit controls are not present. |

## Walkthrough Coverage

The UI was exercised with vegan Mexican fast casual, Korean coffee shop and
premium steakhouse concepts. Each produced different top areas and scores.
The Korean-cafe path covered comparison, walking catchment, property filters,
budget scenario, menu add/edit/export/preview, saved-concept switching, and
account restore in a second browser context. Chrome and Safari desktop/mobile
checks should be rerun after any frontend or API contract change.
