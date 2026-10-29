# Property listing input

The integrated Storefront Registry has addresses and vacancy filings, but it is
not an active listing feed. The dashboard labels those rows as research records.
The separate `data/listings/public_opportunities.csv` holds one manually checked
NYCHA restaurant-ready space from its [public leasing page](https://www.nyc.gov/site/nycha/business/store-leasing-available-properties.page),
with the latest check date recorded in that CSV. Its asking rent and size are
source-reported; call NYCHA to confirm availability, use restrictions, and lease terms. This is not
citywide listing coverage. No photo is displayed because none was licensed.
NYCHA does not approve new bar uses, so the lead is excluded for bar searches.

The dashboard also reads `data/listings/synthetic_properties.csv` as a clearly
separate **synthetic demonstration** inventory. Its 900 modeled leases and 100
modeled purchases have approximate tract locations and market-calibrated
prices, but no actual address, broker, source listing, photo, or confirmed
availability. They are never imported through the verified-listing path or
presented as live offers. See [SYNTHETIC_PROPERTIES.md](SYNTHETIC_PROPERTIES.md)
for generation, market sources, validation, and the data dictionary.

To add listings, place a CSV at `data/listings/verified_properties.csv` from the
project root. The file is private data and must not be committed to GitHub.
The backend reads it on each dashboard request so new rows appear after refresh.
It also reads separately imported provider snapshots under `data/listings/authorized/`.
Those files remain local and do not replace the manual CSV or public lead.

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
title,sqft,frontage,condition,availability,image_url,photo_display_permission,image_rights_reference,latitude,longitude,broker_name,broker_contact,notes
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

## Authorized partner snapshots

When a broker or owner supplies a **complete** current CSV and written permission
to display its listing facts, preview it from the project root:

```bash
.venv/bin/python demo/import_partner_listings.py --input /path/to/provider.csv --provider provider-name --rights-reference /path/to/permission.txt
```

After reviewing the validation report and permission terms, add `--publish`.
The importer replaces only that provider's prior snapshot. It checks positive
asking rent or sale price, source URLs, check dates within 90 days, duplicate IDs,
NYC coordinates and tract matches. If coordinates are omitted, each row must
include an integrated 11-digit `geoid`; this verifies membership, not the street
address. An `image_url` requires an HTTPS URL, `photo_display_permission=yes`,
and an `image_rights_reference` on that row, in addition to the written provider
rights reference. It does not download or grant rights to any photo. The supplied CSV
may use the columns above. The dashboard labels
availability as provider-reported and still requires independent confirmation.

The importer is intentionally not a scraper. There is no partner inventory in
this folder until a rights-cleared provider file is supplied.

The separate NYC DOF storefront rent statistics provide a reported occupied-rent
median by tract (latest published reporting year: 2024). They cannot establish
that a space is available or what its landlord currently asks. Refresh them with
`python demo/download_sources.py --source storefront_rent_stats`; unchanged
publisher versions are skipped. The backend reads the latest valid local snapshot.

Do not scrape LoopNet for the listing CSV: its [terms of use](https://www.loopnet.com/solutions/LoopNetTerms-of-Use) prohibit automated or
manual copying of listing information into a separate database without express
permission. A daily interval does not change that restriction. Use a licensed
feed or obtain listing information directly from brokers or owners with
permission to store and display it. Source URLs, usage rights, and check dates
should be retained for every row.
An API key alone is not a redistribution license: [Crosstown Street's API terms](https://www.crosstownstreet.com/terms)
also restrict republishing and competitive datasets without written approval.
