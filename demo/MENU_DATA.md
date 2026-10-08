# Menu Studio Data Contract

Menu Studio uses `demo/menu_catalog.csv`, an editorial seed of dish names and
sections. It currently contains 183 ideas across 35 cuisine/specialty keys,
including the generic `any` category. These are suggestions, not claims about
NYC demand, dish popularity, prices, ingredients, or restaurant performance.
`GET /api/menu/suggestions` uses the active cuisine, restaurant format, price
tier, and dietary identity. Unsupported cuisines return `status: unavailable`.
Plant-based filtering identifies candidates only; the operator must verify
ingredients, preparation and cross-contact. Halal, kosher and gluten-free
compliance is never inferred from a dish name.

The browser saves each menu under its local account or guest identity, concept
name, resolved cuisine, format and dietary identity. Signed-in accounts also
sync their workspace through the local Flask account database; guests remain
device-local. The first sign-in imports guest menus without replacing existing
account dishes. Changing the spend target does not create a new menu. Existing
browser drafts are migrated from the old key when opened. Dish names,
descriptions, section order, planned prices and per-portion ingredient costs
can be edited. The summary calculates item margin only where both price and
cost have been entered; these figures are planning inputs, not market
estimates. The preview can be printed, and CSV export includes the
operator-entered values. If account sync is unavailable, local edits remain
on the device and the interface reports that state.

## Optional Review Evidence

The current integrated Groundwork datasets do **not** contain dish-level
ratings, review text or order counts. OSM cuisine tags and DOHMH inspection
grades cannot establish which dishes diners liked. The API therefore reports
`review_evidence: unavailable` unless a rights-cleared input is installed at
`data/menu/review_mentions.csv`. This file must remain private and must not be
committed to the demo source tree.

Required CSV columns:

```text
review_id,restaurant_id,dish_id,review_rating,observed_on,source_url,rights_basis
```

Each row represents a verified explicit mention of a catalog `dish_id` in a
review, with a 1-5 **restaurant review** rating, source URL and documented
permission to store/use the extracted evidence. Review text and personal data
are not needed. The importer deduplicates reviews per dish and publishes a
signal only after at least 20 mentions from at least five restaurants. It
calls the result positive restaurant-review mentions, never a dish rating.
Names and concept descriptions are not automatically mined for praise.

Do not scrape Google or Yelp reviews into this file without a separate rights
review. Their official APIs return only small review excerpts and impose
content, storage and attribution limits. Instead, seek licensed operator POS
aggregates, consented menu/order data, or a research agreement that explicitly
permits derived dish-level analysis. The next useful fields would be dated
menu prices, orders per dish, ingredient costs, portion size, dietary/allergen
verification, venue format, and location. With enough independent venues,
those could support a measured popularity or margin model; none exists today.
