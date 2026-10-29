# Menu Studio And Business Plan

## Workflow

1. Add suggested or custom dishes in Menu Studio. Edit section, description and
   planned price; Recipe Cost opens the batch ingredient calculator.
2. Enter ingredient quantity and price in the same unit, batch yield and waste.
   Apply explicitly updates the dish's ingredient cost. Duplicate copies a recipe;
   Undo restores the last removed dish without reverting unrelated planning work.
3. Analysis compares price less ingredients per portion, ingredient cost percent
   and items needing review. The full table includes all dishes with a price and
   known cost; the chart shows the top 20. Missing costs are not zero estimates.
4. Configure a guest basket to carry average spend into Economics. Complete all
   operating costs separately; ingredient cost does not include labor or overhead.
5. Open Business Plan under Workspace. Choose the current Economics draft or a
   saved scenario, enter cash/opening/owner-draw/ramp assumptions, and review cash
   balance sensitivities, monthly cash flows, shortfalls and due diligence.
6. Export the three cash cases to CSV from Monthly Detail. Synthetic properties
   remain scenarios, and neither volume sensitivity nor cash flow is a validated
   forecast of demand, profitability or financing availability.

## Calculations

Recipe purchase cost = sum(quantity * cost per unit).
Waste-adjusted batch cost = purchase cost / (1 - waste percent / 100).
Ingredient cost per portion = adjusted batch cost / batch yield.
This waste allowance assumes extra purchases are needed to retain the entered
usable yield. It is not an automatic unit converter or ingredient price source.
The API accepts 1-30 ingredient lines, integer yield 1-2,000 and waste 0-50%.
Costs above $1,000 per portion are rejected for review.

Cash month zero = starting cash - one-time opening costs.
For each month, guest volume ramps linearly from the entered month-one percentage
to full entered volume by the selected ramp month. A one-month ramp means full
volume immediately. Lower/entered/higher cases multiply volume by 0.8/1/1.2,
then cap it at entered daily capacity. Guest spend is held constant.

Monthly cash in = daily guests * spend per guest * operating days.
Monthly variable cost = days * (unit cost * guests + congestion cost * guests^2 /
(2 * daily capacity)), matching the existing Economics cost model.
Monthly fixed cost = monthly rent + other monthly fixed costs.
Monthly cash out = variable cost + fixed cost + owner draw.
Cash balance accumulates receipts less payments. Opening costs occur once, not
every month; rent is not counted twice. Additional cash needed is the magnitude
of the lowest negative balance, including month zero.

These are month-end operating scenarios, not a full accounting or tax model.
Intramonth payment timing, borrowing, purchase financing and later capital costs
are not inferred. Users must include applicable payments in their assumptions.

## Persistence And Safety

`menu_planning.py` and `business_plan.py` provide pure calculation APIs in Flask.
No publisher data, model training or scoring weights change. Recipe and planning
payloads are strictly validated by `workspace_schema.py` before the existing
authenticated, CSRF-protected, revisioned workspace writes. Guest work is local;
account work is privately stored in the existing account database. No account
database or generated financial file is committed. CSV text cells are escaped
against spreadsheet-formula injection.

`menu_lab.js` and `business_workspace.js` add focused UI behavior without a new
frontend framework. Stale calculation responses are discarded, invalid inputs
clear stale forecasts, and deleted named scenarios are not silently replaced.
Missing operating assumptions produce an Economics action, not invented values.

## Verification

Python: `python -m pytest codes demo backend/tests -q`.
JavaScript: `node --test backend/tests/frontend_*.test.cjs`.
Focused coverage: `test_menu_planning.py`, `test_business_plan.py`,
`test_workspace_planning.py`, `frontend_menu_lab.test.cjs`.

Browser checks use Chrome and Playwright WebKit at desktop and mobile sizes:
recipe inputs and yield/waste arithmetic, apply/cancel, duplicate/remove/Undo,
analysis charts, cash charts, saved scenarios, account database restoration and
overflow. Existing properties, heatmap, all three map styles and main-branch
explorers are checked separately. No scientific-accuracy claim follows from
passing these operational tests.
