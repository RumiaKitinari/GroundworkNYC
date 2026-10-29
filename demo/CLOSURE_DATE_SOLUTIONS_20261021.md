# Opening and Closure Date Solutions

Research and implementation completed October 21, 2026. This supplements
`CLOSURE_VALIDATION_RESEARCH_20261021.md`. Nothing from this work changes the
active master, frontend, existing outcome labels, or Atharv's model. His label
construction cannot be judged without the actual training file and code.

## Recommended Path

Use the planned restaurant-level gradient-boosting stage to predict continued
operation after a known operating baseline, with source-supported closure
intervals. This is remaining survival for existing restaurants, not lifespan
from an inferred opening or proven success of a new restaurant concept.
The existing survival-readiness protocol already describes a one-year dated
baseline target; no new target is silently substituted here.

Two date questions must remain separate:
- Actual opening age needs a documented opening/operator episode. A first
  inspection, database creation, permit issue, or capture date is not that date.
- Remaining survival can start at a dated, identity-consistent operating event.
  It still needs trustworthy later outcomes and appropriate censoring.

Use intervals when the endpoint is credible but its day is uncertain. An exit
known only to fall across the one-year horizon cannot determine a binary
one-year label. XGBoost AFT is a possible interval-censoring extension, not a
replacement for evidence. See the earlier report for implementation and loader
compatibility constraints.

## Implemented: Full Original-Capture Event Ledger

`build_operating_event_ledger.py` scans all 748,441 rows in the three pinned
original DOHMH captures, restricted to our 5,999-candidate review frame, without
sampling. It writes 26,885 capture-event groups, retaining original names,
addresses, actions, record dates, capture URLs, file hashes and CSV record
numbers. Duplicate violation rows are grouped, not counted as independent
observations. Repeated captures of one inspection are not independent events.

Results:
- 4,686 candidates have at least one qualifying dated operating inspection.
- 44 candidate first-cycle leads are temporary health-department closures.
- 607 capture-event groups are health-closure actions, not permanent exits.
- 427 groups record reopenings; 398 potential operating groups have identity
  drift across captures and are held for review.
- 84 groups have invalid/placeholder timing; three are non-operational
  pre-permit inspections. Neither supplies operating evidence.

Both ordinary cycle and explicitly operational pre-permit inspections can
support dated operation; recognized reopening actions are retained separately.
Blank/unrecognized actions, identity mismatches and non-operational records do
not qualify. Every qualifying event must have inspection <= record <= capture
dates. This preserves evidence discarded by the consolidated inspection table,
which lacks the original action and capture-specific identity context.

These counts concern evidence coverage, not verified survival labels or all NYC
restaurants. The frame's historical selection process still requires review;
very short-lived restaurants absent between captures can be missed.

Private output:
`data/evaluation/closure_research/operating_ledger_20261021T154934609261Z/`

Files: `events.csv`, `candidate_summary.csv`, `report.json`.

Reproduce with explicit original captures, including gzip content stored under
a `.csv` extension:

```sh
.venv/bin/python demo/build_operating_event_ledger.py \
  --capture data/raw_sources/nyc_cuisine_atlas/20db98e6d2a1b2699b7a42c2e90df2edaed154e5/wayback_20231117063638.csv \
  --capture data/raw_sources/nyc_cuisine_atlas/20db98e6d2a1b2699b7a42c2e90df2edaed154e5/wayback_20240928031215.csv \
  --capture data/raw_sources/nyc_cuisine_atlas/20db98e6d2a1b2699b7a42c2e90df2edaed154e5/wayback_20250913150157.csv
```

## Implemented: Source-Attributed Event-Window Audit

`audit_restaurant_event_dates.py` joins a separately curated source registry to
the actual candidate identities. It validates date ordering and attribution,
compares reported opening windows with permit leads and Foursquare marks, and
performs conditional horizon arithmetic. It never imputes a midpoint, marks
operator identity verified, changes labels, or enables training.

Five additional targeted cases were researched. Three have reported site exits
within 365 days even under the broad opening windows, conditional on accepting
the reports and the site/concept identity. This is not a random audit, a model
performance result, or five newly adjudicated operator outcomes.

| Candidate | Published opening evidence | Closed-by evidence | Main issue |
| --- | --- | --- | --- |
| Well Well Well, 141 Nassau | June 2023 | April 29, 2024 | Candidate permit follows opening; later capture repeats old inspection |
| El Condor, 95 Greenwich | Owner reports February 14, 2022 | June 30, 2023 | Survived opening anniversary but exited soon after 2023 operating baseline |
| Balkan StrEAT, 353 Sixth | January 2023 | October 20, 2023 | Same owners later changed concept to Burgerhead |
| Essex Squeeze, 300 East Fifth | March 2022 | January 30, 2023 | Site exit is not closure of every brand location |
| Bronson's Burgers, 250 Mulberry | Operating visit in July 2021; opening unspecified | February 23, 2024 | Do not infer opening from a food visit or later permit |

Source details, dates and short paraphrases:
`data/evaluation/closure_research/event_bounds_sources_20261021.json`

Audit output:
`data/evaluation/closure_research/event_dates_20261021T154656828733Z/`

```sh
.venv/bin/python demo/audit_restaurant_event_dates.py
```

### Concrete Corrections From Original Rows

**Well Well Well:** the August 9, 2023 operational inspection recurs in the
September 2024 capture without a later inspection. That capture's presence does
not establish operation after the reported April 2024 site exit.

**El Condor:** the original March 24, 2023 routine inspection supplies a dated
operating observation after the owner-reported first anniversary. Closure by
June 30 fits within a year of that landmark, but calling it first-year failure
from its reported February 2022 opening would be wrong. Opening-age and remaining
survival are different questions; continuity/episode review remains necessary.

**Lords Bakery:** April 11, 2023 was a DOHMH shutdown. April 14 records reopening,
and October 4 a routine inspection. The March 2024 site-exit reports must not be
conflated with the earlier temporary shutdown. Earlier CAMIS `40423399` also
identifies the same bakery/address; the 2022 permit is not its original opening.

**Balkan:** archived Burgerhead CAMIS `50149948` at the same property and the
published same-owner conversion support a concept transition. The correct
label depends on whether the declared endpoint is concept exit, operator exit,
or physical vacancy. Do not call a rebrand insolvency or profit failure.

**Anella:** predecessor CAMIS `41410058` and different SLA legal entities point
to operator/permit episodes at one long-running site. Successor CAMIS `50135640`
changes DBA across captures (MITICA, MYSTICA, MARISCOS EL SUBMARINO), showing why
newest-name consolidation can misattribute older inspections. License expiry
does not date closure; no direct legal-entity/CAMIS crosswalk is established.

## Alternatives Tested and Limits

| Route | Useful contribution | Limitation or access result |
| --- | --- | --- |
| Original DOHMH capture rows | Dated operating/reopening events; administrative actions | Active-feed snapshots can retain stale inspections; cannot label permanent exits alone |
| Operator announcements and dated local reporting | Opening windows, closure-by bounds, site/brand distinctions | Coverage favors publicized businesses; copied announcements are not independent corroboration |
| Overture and Foursquare | Scalable status and identity review leads | Shared providers, latency and conflicts; marks are not actual trading dates |
| SLA history / community-board records | Legal entity and site history | Alcohol-license lifecycle is not restaurant lifecycle |
| Google Places API | Current business status and moved-place links | Not a historical lifecycle source; key alone does not authorize ML training/validation |
| NYU paper's public dataset link | Accessible academic metadata and codebook | Linked files are healthcare egress observations, not the restaurant closure outcome table |
| NYS inactive food-establishment table | Explicit inactive records elsewhere in NY | Published series excludes NYC |
| Historical operator websites | Dated announcements where captures exist | Archive coverage varies; a retained menu or domain alone does not prove trading |
| Human/owner verification | Can resolve dates and identity for selected cases | No calls, messages or records requests were submitted; requires a planned review process |

## Additional Official Tables Downloaded and Matched

The follow-up search found three useful official sources, now downloaded in
full within their stated scopes, with publisher row counts/revisions checked
before and after extraction. Raw files, full publisher metadata and SHA-256
checksums are stored privately at:

`data/raw_sources/closure_lifecycle_references/20261021T155629654315Z_065f910c/`

| Official source | Downloaded rows | Matches in the 5,999-candidate frame |
| --- | ---: | --- |
| SBS Business Acceleration | 5,226, entire historical table | 53 candidates with exact normalized name/address/ZIP/borough and an agency-reported opening date |
| Historical Open Restaurant Applications | 14,428, entire table | 214 CAMIS matches; 198 also match normalized site address |
| Executed evictions | 11,845, all commercial executions | 336 candidate addresses with one or more commercial execution records |

These are program-reference and address-event counts, NOT newly verified
opening/closure labels. SBS covers businesses assisted by its program, not all
NYC openings, and its publisher revision is from 2019. Its dates can expose
earlier operation or older site episodes; they should not be applied to newer
CAMIS records as owner birth dates. For example, Bien Cuit at 120 Smith Street
has an SBS opening date of July 13, 2011 despite a much later permit-era
candidate. Some candidate identities recur under multiple CAMIS IDs; the output
retains those IDs and the SBS business category for review. A hotel's opening
date is not automatically the opening of its restaurant.

The outdoor applications retain legal-business names, permit identifiers and
SLA references. They are useful for operator reconciliation, but an application
neither confirms trading nor fixes an opening day. Mismatched addresses remain
flagged rather than being silently accepted.

The eviction table supplies unusually strong corroboration for Lords Bakery:
2135 Nostrand Avenue has a commercial **Possession** event executed on
**March 25, 2024**, court index **K333536/23**, consistent with the dated notice
described in the reporting. The official table contains no tenant name: a match
requires the article/operator identity evidence as well. Execution does not by
itself prove the exact last service, permanent brand closure or financial failure.
Other address matches can belong to unrelated units or earlier/later tenants;
do not automatically turn the 336 matches into closure outcomes.

Latest matched output:
`data/evaluation/closure_research/official_references_20261021T155717118214Z/`

```sh
.venv/bin/python demo/research_official_lifecycle_sources.py
# Reuse a checksum-validated local snapshot without re-downloading:
.venv/bin/python demo/research_official_lifecycle_sources.py \
  --source-dir data/raw_sources/closure_lifecycle_references/20261021T155629654315Z_065f910c
```

All rows are preserved in each requested scope, not a sample. The CSV request
limit is above the checked full row count; a partial export or changed publisher
revision causes failure, not acceptance. Residential executions are intentionally
excluded. Each run publishes a new private reference/review directory.

- [Official SBS data/API](https://data.cityofnewyork.us/resource/9b9u-8989.json)
- [Official historical applications](https://data.cityofnewyork.us/Transportation/Open-Restaurant-Applications-Historical-/pitm-atqc)
- [Official execution data/API](https://data.cityofnewyork.us/resource/6z8x-wfk4.json)

Community-board minutes and NYS corporate filing/status histories remain useful
targeted operator-history routes, not automated restaurant outcome labels.
For example, CB3's January 2018 minutes contain retrospective site-closure
statements and relocation context. Corporate formation/dissolution can be
separated from site opening/exit; process-agent addresses are not restaurant
premises. These larger histories were not added to the master or downloaded
wholesale as purported restaurant lifespans.

- [CB3 primary minutes](https://www.nyc.gov/assets/manhattancb3/downloads/minutes/minutes2018-01.pdf)
- [NYS filing history](https://data.ny.gov/resource/63wc-4exh.json)
- [NYS status history](https://data.ny.gov/resource/3gg2-jgnp.json)

### Google Is Not a Ready-Made Date Solution

The current Places resource's `openingDate` is populated only for
`FUTURE_OPENING`, not past first trading dates. Moved-place links help distinguish
relocation from disappearance, but a closed status alone does not establish the
historical exit day. Standard Maps terms section 3.2.3(c)(vii) restrict using
Maps content to train, test, validate or fine-tune ML/AI models. Do not ingest
these results into training or validation under ordinary API access; any
different permitted use needs appropriate authorization/terms review first.

- [Current Places resource](https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places)
- [Relocated-place behavior](https://developers.google.com/maps/documentation/places/web-service/place-details)
- [Standard Maps terms](https://cloud.google.com/maps-platform/terms)
- [Foursquare field definitions](https://docs.foursquare.com/data-products/docs/places-os-data-schema)

### Academic Dataset Lead Checked, Not Assumed

Wang and Laefer's NYC business-closure study is relevant methodological work,
but the repository linked in its availability statement is titled *Egress
Behavior from Select NYC COVID-19 Exposed Health Facilities March-May 2020*.
The public API exposes four files: egress CSV, GIS ZIP, codebook and README,
under CC BY 4.0. Its 118-row codebook describes observational travel/health
variables, not a restaurant opening/closure label table. These metadata and the
codebook were inspected; no unrelated 12.6 MB package was integrated. A paper
link is not evidence that its proprietary-input outcome table is downloadable.
Even a licensed pandemic-era outcome table would be a differently scoped
benchmark, not proof of our current cohort's outcomes.

- [Primary paper](https://doi.org/10.1177/23998083241254573)
- [NYU record API and file inventory](https://ultraviolet.library.nyu.edu/api/records/tn478-2kc30)
- [NYU codebook](https://ultraviolet.library.nyu.edu/api/records/tn478-2kc30/files/2020_NYU_egress_covid19_codebook_v3.csv/content)

## Next Adjudication and Training Gates

1. Agree on one endpoint with Atharv: named restaurant at a site versus operator
   survival. Mark rebrand, relocation, temporary shutdown and unknown separately.
2. Reconcile the researched episodes against the original events and their
   predecessor/successor identities. Review both probable survivors and exits,
   not just the newsworthy cases. Keep unresolved records and selection weights.
3. Replace invalid baseline proposals only through a documented cohort revision;
   use a confirmed operating event and predictors published by that baseline.
   Do not use knowledge of a later exit to select the most favorable landmark.
4. Derive closure intervals only after accepting dated site-exit evidence and
   identity. A confirmed later routine inspection supports follow-up, but does
   not by itself prove no interim exit/reopening. Inspect those histories too.
5. Freeze an independently adjudicated temporal/geographic evaluation set before
   tuning. Repeated restaurants and related operator/site episodes must not
   leak between train and test. Audit coverage and outcome uncertainty alongside
   model discrimination and calibration.

Weak/noisy labels or positive-unlabeled methods can support sensitivity work,
but cannot establish the missing truth. Publicized closures are not plausibly a
random selection of all closures. Do not claim calibrated probabilities from
these methods without a defensible observation model and independent evidence.

The immediate blocker is not an inability to know every exact day. It is enough
dated, identity-consistent outcomes and historically valid predictors to support
training and evaluation. The work above reduces that problem without inventing
dates or overwriting exploratory artifacts.

The bounded El Condor Wayback CDX probe timed out after 25 seconds in this
environment. Other historical captures already stored locally were usable.
Archive accessibility varies; no absence-of-capture labels or access-control
workarounds were used.
