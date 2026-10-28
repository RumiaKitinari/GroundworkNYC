# Synthetic Property Scenarios

The local file `data/listings/synthetic_properties.csv` contains **1,000
synthetic demonstration scenarios**, not actual available properties: 900
modeled leases and 100 modeled purchases across all five boroughs. No row has a
real street address, owner, broker, listing URL, property photo, or confirmed
availability. Coordinates are approximate points inside a Census tract, not
building entrances. Do not contact anyone or make an offer based on these rows.
The dataset is separate from verified listings, the NYCHA public lead, and
Storefront Registry research records. It is also excluded from the survival
model's training inputs.

## Reproduce And Validate

With the private integrated release installed, run from the repository root:

```bash
.venv/bin/python demo/generate_synthetic_properties.py
```

The fixed seed is 440. The generator refuses to overwrite an existing scenario
file unless `--replace` is supplied. A release change can alter the scenarios;
the accompanying `synthetic_properties.manifest.json` records release input
hashes, CSV checksum, count checks, benchmark samples, pricing adjustments,
and distribution statistics. Flask accepts the CSV only when its checksum and
schema match that manifest. Neither file is part of the integrated tract master
or the authorized partner listing importer.

## Market Calibration

- **Neighborhood starting point:** [NYC DOF Storefront Registration Class 2
  and 4 Statistics](https://data.cityofnewyork.us/City-Government/Storefront-Registration-Class-2-and-4-Statistics/dxru-eun8)
  report 2024 occupied monthly rent per square foot by tract. Convert to an
  annual rate and shrink noisy tract values toward an NTA median weighted by
  the number of leased storefronts in each reporting tract. If a tract lacks a
  median, use its NTA median; 14 of 1,000 scenarios fall back to a modeled
  borough context. These reported rents are **not asking rents**;
  the [DOF filing rules](https://www.nyc.gov/site/finance/property/storefront-registry-requirement.page)
  explain the occupied-rent measure.
- **Asking-rent scenarios:** Apply a transparent 1.10 asking-market adjustment,
  corridor tier, condition, floor, corner, size, and modest correlated variation.
  A second-floor space receives a substantial discount. Neighborhood-main and
  secondary street scenarios are distinct. Prime Manhattan corridor scenarios
  use selected 2026 asking-rent anchors, including SoHo $374/SF/year,
  Flatiron/Union Square $329, Upper West Side $296, and Lower Manhattan $204
  from [Cushman & Wakefield's Manhattan retail MarketBeat](https://assets.cushmanwakefield.com/-/media/cw/marketbeat-pdfs/2026/q1/us-reports/retail/manhattan_americas_marketbeat_retail_q12026.pdf?rev=133d39267ee24b0f8034ff9e561ad341).
  [REBNY's H1 2026 report](https://www.rebny.com/reports/manhattan-retail-report-first-half-2026/)
  identifies high-demand Manhattan corridors. These anchors apply only to the
  simulated prime tier, never to every property in a neighborhood. Luxury-only
  flagship rates are deliberately not assigned to food-service scenarios.
  Herald Square's $503/SF is not used as a Times Square anchor, and the
  Meatpacking District's $302/SF is not used as a Chelsea anchor. Even the
  remaining NTA-aligned anchors do not establish that a modeled tract point is
  on the cited retail corridor.
- **Sales:** Estimated market annual rent multiplied by an assumed 57-69%
  net-rent share and divided by a simulated borough cap rate. This is an
  illustrative valuation, **not** an appraisal or actual sale quote. Broad
  reasonableness checks use 2026 retail sale reports from
  [Matthews/CoStar for Manhattan and Brooklyn](https://www.matthews.com/insights/new-york-retail-market-report-q2-2026),
  [Queens](https://arielpa.nyc/reports/h1-2026-queens-report.html), and
  [the Bronx](https://arielpa.nyc/reports/h1-2026-bronx-report.html), plus
  [PropertyShark's 2025 Staten Island retail market overview](https://www.propertyshark.com/mason/market-trends/retail/nyc/staten-island).
  Reported sales mix can be concentrated in premium assets or whole buildings;
  its average or median should not be imposed on every small simulated space.

The 2026 gross asking-rent corridor figures, 2024 DOF occupied rents, and sale
transaction prices measure **different things**. The 1.10 uplift, corridor
multipliers, cap rates, net-rent share, and guardrails are documented modeling
assumptions, not estimates learned from verified leases. Tenant improvements,
taxes/CAM, concessions, utilities, financing, zoning, permits, and liquor use
are not priced.

## Borough Review

The manifest contains 10th/50th/90th lease and sale examples for every borough.
The validated build using release `20261017T120459Z_c5377537` and seed 440 has
these medians:

| Borough | Scenarios | Lease annual $/SF | Purchase $/SF | Published sale check $/SF |
|---|---:|---:|---:|---:|
| Manhattan | 220 | 108.00 | 1,464 | 1,410 (Q2 2026 average) |
| Brooklyn | 340 | 45.95 | 458 | 521 (Q2 2026 average) |
| Queens | 270 | 47.57 | 486 | 670 (H1 2026 average; large-trade mix) |
| Bronx | 120 | 43.38 | 336 | 525 (H1 2026 average) |
| Staten Island | 50 | 38.41 | 383 | 366 (2025 median) |

The modeled sale medians for Brooklyn, Queens, and the Bronx are below their published
transaction averages: the simulation covers ordinary neighborhood storefronts
while those reports include other asset types and stronger trade locations.
These are comparisons, not validation of individual sale prices. The highest
lease rate is $302.69/SF/year and the median is $51.05; the median modeled
sale is $536/SF. SoHo lease scenarios
have a median rate more than twice the Queens-wide median, reflecting the
different neighborhood and corridor contexts.

The validator checks 1,000 distinct IDs and tracts, the 900/100 split, borough
quotas, point-in-tract geography, commercial-tract screening, nonempty fields,
physical combinations, at least 15,000 square feet of tract retail area,
at least 50,000 square feet of retail per square mile, a 110-foot maximum modeled storefront depth,
purchase asset type,
monthly-rent and sale-price arithmetic, borough review envelopes, sale-median
sanity ranges, and the SoHo/Queens contrast. The current report records 44
lower rent-bound corrections, three lower sale-bound corrections, and one upper
sale-bound correction. If more than
80 rents or 10 sale valuations require envelope corrections, generation fails
and the calibration needs review. The manifest records low, median, and high
examples for both leases and purchases in every borough.

## Data Dictionary

| Fields | Meaning |
|---|---|
| `property_id`, `inventory_type`, `generation_seed`, `source_release` | Stable scenario ID, mandatory synthetic marker, deterministic seed, integrated data release. |
| `transaction` | `lease` or `purchase`; determines which financial fields are populated. |
| `geoid`, `borough`, `neighborhood` | 2020 Census tract key and integrated NTA/borough context. |
| `location_label`, `latitude`, `longitude`, `location_precision` | Approximate tract area and point; never a verified address or premise. |
| `corridor_tier`, `corridor_context` | Simulated secondary, neighborhood-main, or prime retail setting. |
| `building_type`, `floor`, `ground_floor`, `corner_position` | Modeled building and visibility configuration, not inspected facts. |
| `available_sqft`, `frontage_ft`, `condition` | Simulated space size, frontage, and fit-out condition. |
| `former_food_use`, `kitchen_status`, `ventilation_status` | Correlated food-use assumptions; actual systems and permission unverified. |
| `step_free_entry`, `outdoor_space_potential`, `restaurant_fit` | Accessibility, outdoor-permit, and restaurant-fit scenarios; not legal or engineering determinations. |
| `annual_rent_psf`, `monthly_rent` | Modeled lease rate and monthly rent; blank for purchases. Monthly = annual rate × area ÷ 12, rounded to cents. |
| `asking_price`, `asking_price_psf` | Modeled purchase valuation and per-SF price; blank for leases. Price = per-SF valuation × area. |
| `estimated_market_rent_psf`, `estimated_cap_rate` | Annual rent-potential scenario for both transactions; the cap rate is populated for purchases only. |
| `reported_occupied_rent_psf`, `rent_context_scope`, `rent_context_year` | Published tract occupied rent when available, benchmark fallback level, and reference year; the year is blank for an unsourced borough fallback. |
| `pricing_adjustment`, `pricing_basis` | Recorded rent/sale guardrail corrections and the assumptions behind pricing. |
| `availability` | Always states that the scenario is not a verified available listing. |

Restaurant suitability, kitchen, ventilation, step-free access, and sidewalk
space remain hypothetical. They must be verified at a real premises before any
commercial decision. Scenario prices must never be described as asking prices
from a landlord or broker.
