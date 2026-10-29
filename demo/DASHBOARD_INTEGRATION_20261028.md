# Dashboard Integration Audit: October 28

## Corrected Property Workflow

Previously the Overview map plotted the 24 leading tract centers. A popup
searched a separately capped property shortlist for the same tract, so it often
reported no matched property even when the synthetic inventory contained one.
The shortlist also discarded valid scenarios after 48 records and imposed
per-neighborhood and borough caps.

The default Overview now plots actual matching property/scenario records at
their recorded coordinates. Synthetic coordinates remain explicitly approximate,
not verified storefront addresses. MapLibre clusters the full result set at
wide zooms; hovering a cluster shows its count and clicking zooms in. Individual
points expose transaction, price, floor area, area score and available
property-level access. Missing observations remain unavailable.

The Recommended Areas mode retains tract markers, and the existing heatmap
layers remain separate from properties. Streets, Aerial, 3D, zoom, movement and
expanded map controls remain available. A resize observer keeps the canvas in
sync with responsive panels and selected-property details.

`/api/dashboard` returns all qualifying synthetic records without the former
shortlist cap, plus `property_locations` for their scored tract records. The
property inventory is not restricted to the top 24 areas. Existing budget,
transaction, geography, data-coverage and format filters still apply. Registry
records remain research context, not currently available properties.

The map and opportunity table now use the same inventory. Selecting a property
updates its area context, selected-property summary, detail card and report.
Property cards link back to the map. The table loads additional rows on demand
without dropping them from the map or API. Ranking combines existing area and
property-match measures rather than putting a sourced listing first regardless
of suitability. No source listing is represented as independently confirmed.

Implementation: `app.py:matching_properties`, `select_property_candidates`,
`dashboard`; `static/js/dashboard.js:renderMap`, `installPropertyLayers`,
`renderRanking`, `renderIntel`, `renderLease`, `renderReports`.

## Navigation And Menu Studio

Explore, Plan and Workspace retain the existing design, with clearer active
group and tab states, section-specific titles, keyboard focus, and responsive
horizontal navigation. Only the selected section is shown.
On mobile, a three-way section selector keeps Explore, Plan and Workspace
reachable without searching across one long strip of tabs.

Menu Studio retains cuisine/format ideas, custom dishes, editable sections,
prices, ingredient costs, ordering, local/account workspace persistence,
preview and CSV export. Its optional pricing action uses user-entered ingredient
costs and a target ingredient-cost percentage, rounding upward to $0.50. It
only fills unpriced items and never overwrites an existing positive price.
Missing or invalid costs produce no suggested price. It is a cost scenario,
not a fitted willingness-to-pay estimate. Ingredient contribution excludes
labor, rent, tax and other expenses; it is not net profit.

The catalog cache now includes the full concept request so changes to spend
or style do not reuse the previous response. Transient catalog failures can
be retried. Menu review flags identify unpriced items and prices at or below
ingredient cost. No scraped dish ratings or measured popularity are fabricated.

## Actual Model State

The Sources section reports the ranking, survival artifact, access and inventory
states explicitly. Current screening and network-access calculations are
connected. The verified survival endpoint still reports `awaiting_artifact`.
Offline archive-disappearance research outputs have not been relabeled as
verified closure predictions or silently deployed. The new property workflow
does not change that scientific limitation.

## Verification

API checks cover Korean cafe leasing, Italian fine-dining purchasing, sparse
Haitian cuisine with either transaction, and a $2,000 Queens rent constraint.
Every returned property links to its scored tract, and property area scores
match those linked records. Default matching inventory contains 790 synthetic
lease scenarios plus one source-reported lead; counts depend on the brief.

Chrome and WebKit desktop/mobile checks cover all 11 sections, selected-property
navigation, three basemaps, zoom and expansion, area/property switching, and
menu creation, cost pricing, price preservation, preview, export and reload
persistence. Unit regressions cover uncapped synthetic inventory, linked area
scores, map fallback, evidence modes and pricing arithmetic. Two dedicated
PostGIS integration tests require their separate test database and remain
skipped in the ordinary local suite.
