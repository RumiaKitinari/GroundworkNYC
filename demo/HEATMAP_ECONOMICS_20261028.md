# Feature Heatmaps And Economics Workspace

## Numbered Results

Area markers display their result-list position. Individual property symbols
display the property-result position before coordinate filtering, so a record
without map coordinates does not renumber the remaining results. Cluster
numbers remain counts, not ranks. Existing restaurants are opt-in context and
are hidden during feature heatmaps to avoid confusing supply counts with
recommendations.

## Actual Feature Surfaces

The Heatmap Feature control calls `/api/hex-demand?metric=...` with the active
concept and borough. Supported metrics are combined concept demand, location
fit, area demand, customer fit, general accessibility, network-based customer
access, EPA walkability, competition balance, cuisine supply and commercial fit.
These are distinct calculations, not the same surface with renamed colors.

H3 cells use polygon-overlap-weighted tract measures; sectors summarize child
cells. The prior Staten Island exclusion has been removed. General access
retains the existing cell-center subway-distance adjustment; other individual
features do not inherit that adjustment. Network customer access uses the
existing cached routing inference, not a fabricated pedestrian observation.
Cells without source coverage are omitted. Empty cuisine-supply surfaces, such
as an unspecified cuisine, report `no_feature_coverage` rather than inventing
values. Higher coverage makes the fill more opaque; legend values remain on
the stated 0-100 scale.

Implementation: `hex_demand.py`, `app.py:cached_hex_surface`,
`static/js/dashboard.js:showHexLayer`, `paintHexLayer`.

## Economics

`GET /api/economics/scenario` is a deterministic scenario calculator. It does
not train or invoke a demand model. Inputs are monthly occupancy and other
fixed costs, operating days, guest spend, variable cost per guest, expected
covers, daily capacity, assumed elasticity, capacity cost premium and target
daily profit. Illustrative inputs are labeled as assumptions. Drafts are saved
on the current device, scoped to the concept/account identity; this is not a
new server-side financial-record store.

Four locally rendered Chart.js graphs show revenue versus total costs, daily
profit versus volume, demand/MR/MC, and demand-adjusted profit versus price.
The workspace reports break-even covers, target-profit covers, capacity use
and the best modeled spend/volume/profit. A selected synthetic lease rent can
be copied explicitly; it is not represented as a verified asking rent. A
purchase price is never converted automatically into a monthly financing cost.

Let p0 and q0 be entered guest spend and daily covers, e the assumed absolute
price elasticity at that point, K capacity, c variable cost per cover, g the
capacity premium, and F daily fixed costs:

```text
P(q) = p0 (1 + 1/e) - p0 q / (e q0)
TC(q) = F + c q + g q^2 / (2 K)
MR(q) = p0 (1 + 1/e) - 2 p0 q / (e q0)
MC(q) = c + g q / K
q* = clip((p0 (1 + 1/e) - c) / (2 p0/(e q0) + g/K), 0, K)
```

The bounded optimum includes zero output and capacity. Fixed costs remain at
zero output; a loss-making scenario is not relabeled as profitable. Fixed-price
break-even/target volumes solve the corresponding cost equation and return
unavailable when the target cannot be achieved within capacity. Costs not
entered, taxes and financing are excluded. Linear demand is an assumption,
not evidence of customers' willingness to pay. None of these outputs validate
the survival model or forecast realized business profits.

Implementation: `economics.py`, `test_economics.py`,
`static/js/dashboard.js:prepareEconomicsLab`, `renderEconomicsCharts`.

The MR=MC framework follows the differentiated-restaurant example in
[OpenStax, Monopolistic Competition](https://openstax.org/books/principles-microeconomics-3e/pages/10-1-monopolistic-competition).
The project's particular demand and cost functions are modeling assumptions,
not fitted parameters from that source. Charts use locally bundled Chart.js
4.4.8, with its MIT license retained under `static/vendor/chartjs/`;
[responsive chart guidance](https://github.com/chartjs/Chart.js/blob/master/docs/configuration/responsive.md)
informs the fixed-height responsive containers.
