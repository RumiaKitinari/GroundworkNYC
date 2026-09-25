# Property listing input

The integrated Storefront Registry has addresses and vacancy filings, but it is
not an active listing feed. The dashboard labels those rows as research records.

To add listings, place a CSV at `data/listings/verified_properties.csv` from the
project root. The file is private data and must not be committed to GitHub.
The backend reads it on each dashboard request so new rows appear after refresh.

Required columns:

```text
listing_id,geoid,transaction,address,borough,asking_rent_monthly,asking_price,source_url,checked_at
```

`transaction` must be `lease` or `purchase`. Supply a positive monthly rent for
lease rows or a positive asking price for purchase rows. `geoid` is the NYC
census tract GEOID in `master_tract_features.csv`. Listings are matched against
all eligible tracts, not only the 24 shown in the area ranking. Listings above
the relevant lease or purchase budget are excluded. Registry filings may appear
as lease research leads but never as purchase listings.

Optional columns:

```text
title,sqft,frontage,condition,availability,image_url,latitude,longitude,broker_name,broker_contact,notes
```

Keep `source_url` and `checked_at` current. An asking price is not a transaction
price, and a listing's availability still needs confirmation with its source.
The backend requires `checked_at` to be a valid date within the last 90 days;
older, future-dated, or undated rows are not presented as current listings.
If latitude and longitude are supplied, the local OSM graph can attach a
10-minute walking catchment. Missing coordinates or a missing graph yield an
explicit unavailable status, not an estimated site score. The number displayed
on a property card is the tract's area score, not a verified property score.
The current integrated package does not contain landlord names, broker contacts,
asking prices, listing photos, or confirmed lease and sale status.
