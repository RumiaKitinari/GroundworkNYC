# First-Stage Restaurant Survival Readiness

## Decision Target

The Week 6 briefing proposes a general restaurant survival model before the
cuisine-specific Huff/hex demand stage. The first testable target is continued
operation one year after a dated baseline. It is not profit, growth, or the
survival probability of a proposed business. Keep the model offline until
independent outcomes and a genuinely later holdout support calibration.

## What Is Ready

- Four historical tract predictors have three pinned vintages: ACS population
  density and income, LODES workplace job density, and EPA walkability. The
  earliest ACS/LODES tranche was available by April 2023; later vintages
  became available in December 2023 and December 2024. The
  cohort builder selects the latest publisher release available at baseline.
- The first comparator uses prevalence, walkability, density, regularized
  logistic regression, and a shallow histogram gradient booster with fixed
  settings. It reports calibration, neighborhood holdout, and borough results.
- A 100-row current-inventory review queue and a 300-row historical DOT review
  queue are private and explicitly unverified. The DOT queue samples from 1,136
  geocoded, dated outdoor-dining candidates and records match basis and
  selection probability. Its 400 unmatched source records are **not** known
  closures. The expanded queue is at
  `data/evaluation/historical_review_20261013T193016Z.csv`.
- A local evidence-packet tool scans the current DOHMH inspection export for
  exact name/address/borough matches. It identifies possible dated inspection
  pairs but never changes verification or outcome status. That export includes
  active establishments only, so matched cases are survivor-selected and
  unmatched cases are not failures.
- Complete current-active DOHMH exports are now tracked by CAMIS and publisher
  record date in `data/evaluation/permit_presence/`. Repeated disappearances
  are review leads, not closure labels; see `PERMIT_PRESENCE.md`. The first
  local archive spans only September 30-October 16, 2026, so it cannot yet
  supply a one-year permit-persistence target.
- A pinned third-party consolidation of 13 archived DOHMH snapshots plus the
  current 2026 export has been downloaded privately. The reconstructed lifespan
  table has 67,790 CAMIS records and 5,999 strict candidate baselines. A
  5,999-row review queue prioritizes 80 within-year snapshot exits and 1,073
  operational follow-up inspection leads. A 40-case targeted manual pilot is
  also ready. Every row is unresolved and requires independent baseline and
  outcome verification.
- Official active and inactive NYS Liquor Authority datasets are archived
  privately. Exact identity/address matching produces 189 inactive-license
  leads, including 67 with active-license leads too. An inactive or expired
  liquor license does not establish a restaurant closure or its date.
- A complete NYC-area `Dining and Drinking` extract from the Apache-licensed
  February 2025 Foursquare OS Places mirror is archived privately. Matching
  all 5,999 candidates found 31 marked-closed leads without a later DOHMH
  active listing, 26 marked-closed leads with a later DOHMH listing, and 8
  closure marks predating the first cycle inspection. These are not survival
  labels. See `FOURSQUARE_LIFESPAN_SOURCE.md` for coverage, provenance, and
  the current-release access requirement.
- A separate offline archive-reobservation proxy has been trained on all
  2,253 eligible records in the strict candidate cohort with the four dated
  tract predictors. This is **not** a survival model: its positive class means
  the same CAMIS was seen in an archived inspection snapshot at least 365 days
  after the first cycle inspection; its negative class means no such later
  archive observation. Missing archive coverage, changes of identity, and
  unobserved reopenings can all affect that target. Nothing from this proxy
  feeds customer-facing scores.
- The GitHub `ui-concept-polish` branch has no survival-data/model work to
  merge. Its 3D existing-restaurant layer is already present locally. Merging
  the branch wholesale would replace newer backend and data code.

## Label Protocol

Atharv's master-table specification names a `nyc-cuisine-atlas` file called
`restaurant_lifespans.csv`. It was not in the shared data upload, so we
reconstructed an equivalent, more conservative table from the pinned archive.
To reproduce and audit the private candidate table:

```bash
.venv/bin/python demo/download_lifespan_archive.py
.venv/bin/python demo/build_restaurant_lifespans.py --output data/evaluation/lifespans/new_lifespans.csv
.venv/bin/python demo/audit_lifespan_source.py data/evaluation/lifespans/new_lifespans.csv
.venv/bin/python demo/prepare_lifespan_review.py \
  --lifespans data/evaluation/lifespans/new_lifespans.csv \
  --output data/evaluation/lifespans/new_review_queue.csv
.venv/bin/python demo/download_sla_licenses.py
.venv/bin/python demo/match_sla_lifespan_leads.py \
  --queue data/evaluation/lifespans/new_review_queue.csv \
  --output data/evaluation/lifespans/new_sla_leads.csv
.venv/bin/python demo/prepare_manual_lifespan_pilot.py \
  --queue data/evaluation/lifespans/new_review_queue.csv \
  --sla-leads data/evaluation/lifespans/new_sla_leads.csv \
  --output data/evaluation/lifespans/new_manual_pilot.csv
```

Its `clean_cohort` flag is a dataset filter, **not** independent outcome
verification. Its `open_date` column is a first pre-permit inspection;
its upper survival bound is inferred from inspection snapshots. Neither
establishes an opening or permanent closure by itself. The audit never writes
labels or marks the archive training-eligible. Keep the archive under private
`data/evaluation/` until provenance and permissions are reviewed.
The current tables are
`data/evaluation/lifespans/restaurant_lifespans_20261020_v4.csv` and
`data/evaluation/lifespans/review_queue_20261020_v4.csv`; see
`NYC_LIFESPAN_SOURCE.md` for source and cohort details.

The separate proxy can be reproduced without treating nonappearance as
closure:

```bash
.venv/bin/python demo/train_archive_reobservation.py \
  --output data/evaluation/proxy_runs/new_archive_reobservation_run
```

The October 20 offline run uses 2,253 eligible records (2,086 reobserved,
167 not reobserved). The neighborhood-disjoint holdout has 511 records across
49 neighborhoods; the shallow gradient booster reaches ROC AUC 0.548 and
Brier score 0.08547 versus prevalence baseline Brier 0.08577. The comparator
does **not** show clear improvement over baseline. The private run is saved at
`data/evaluation/proxy_runs/archive_reobservation_20261020_v1/` with its full
cohort, audit, metrics, and fitted estimators. These are pipeline-test results,
not evidence of calibrated survival prediction or a deployable model.

An opt-in **strict disappearance sensitivity run** now uses the v4 adjudication
packet and pinned lifespan manifest. A negative requires at least two archived
capture dates after the 365-day horizon and after the last observation, no
current record under the candidate CAMIS, and no exact name/address current
successor CAMIS. Suspected CAMIS changes and name/address conflicts are
censored. Positives remain later archive reobservations, not verified
continuous operation. Reproduce it privately with:

```bash
.venv/bin/python demo/train_archive_reobservation.py \
  --adjudication data/evaluation/lifespans/adjudication_packet_20261020_v4.csv \
  --lifespan-manifest data/evaluation/lifespans/restaurant_lifespans_20261020_v4.manifest.json \
  --output data/evaluation/proxy_runs/new_strict_archive_proxy
```

The October 20 sensitivity run at
`data/evaluation/proxy_runs/archive_reobservation_strict_20261020_v2/`
retains 2,172 records: 2,050 reobserved and 122 sustained non-reobservations.
Its neighborhood-disjoint test has 492 records in 49 neighborhoods. The
gradient booster reaches ROC AUC 0.543 and Brier score 0.06807 versus a
prevalence baseline Brier score of 0.06830. This tiny Brier improvement is not
evidence of reliable closure prediction. The output is marked
`not_deployable_not_business_survival`; it does not feed dashboard scores.
Without a checked sample of the negative class, the fraction that truly
closed is unknown. The split is geographic only, not prospective temporal
validation, and the candidate frame may underrepresent short-lived firms.

## Dated Closure Evidence Still Needed

### Disappearance sample and identity cleaning

The private `disappearance_audit_20261020_v1_sample.csv` records source review
of 12 cases sampled with seed 440 from the 122 strict proxy negatives. Search
results had identity and freshness conflicts; no dated permanent-closure
event was established, so no closure rate is estimated. The companion full
audit finds other current restaurant listings at 91 of those 122 normalized
addresses. A new tenant may follow a closure, but it does not by itself date
the event or prove that the same restaurant continued.

Queens-specific building-number normalization now detects 127 possible CAMIS
transitions across the 5,999-case frame, compared with 104 in v4. The v5
adjudication packet preserves all outcomes as unresolved; two of the earlier
122 strict negatives now have exact same-name/address successor-CAMIS leads.
Use `adjudication_packet_20261020_v5.csv` for future review and sensitivity
runs. Earlier model artifacts are retained as frozen exploratory runs rather
than silently relabeled. See `DATA_EXTENSION_20261020.md` for the updated
current-context data and audit outputs.

### Original DOHMH capture verification, October 20

The original November 2023, September 2024, and September 2025 DOHMH CSV
captures are now stored privately under `data/raw_sources/nyc_cuisine_atlas/`.
`verify_archived_operating_pairs.py` reads both plain and gzip-compressed
captures, deduplicates violation rows into inspections, and requires an exact
CAMIS, normalized name, borough, and address match. It accepts only distinct
non-closure **cycle inspections** 365-455 days apart, with the first cycle date
equal to the candidate's archived first-cycle lead. Each event must be present
in an original capture with a plausible `RECORD DATE`. The v3 review packet is
`data/evaluation/lifespans/original_capture_operating_pairs_20261020_v3.csv`;
its manifest records all source hashes and capture dates.

Of 5,999 candidates, 116 have such a pair and still match the October 2026
active-feed identity; 32 have a pair but need current identity reconciliation;
1,844 have a captured baseline cycle inspection without an eligible captured
follow-up; 1,985 have a first-cycle lead that is absent from these three
original captures or conflicts on identity; and 2,022 have no first-cycle lead.
These are **positive operating-evidence leads**, not adjudicated survival
labels. In particular, a missing follow-up is not a failure. Only 24 of the
116 clean pairs have both an April-2023-or-later baseline (when the earliest
historical predictors were available) and an outcome captured before the
predeclared January 2025 cutoff. That is not enough to train a two-class model.

Reproduce the private audit by passing the v4 adjudication packet as `--queue`,
each original `wayback_<timestamp>.csv` as a separate `--capture`, and a new
private path as `--output`. The script never sets `baseline_operating`,
`outcome_status`, or `verification_status`, and never writes a training cohort.
Reviewers must still determine whether each CAMIS/name/address refers to the
same continuously operating business. A second reviewer should check both
outcome classes and all identity conflicts.

There are currently **zero verified permanent-closure outcomes**. The public
DOHMH feed reports active establishments only; temporary health closure,
inactive liquor license, Foursquare closure flag, and absence from a capture
cannot establish permanent restaurant closure or its date. The unsent FOIL
draft below requests the missing full permit lifecycle and status-code history.
Without it, the honest fallback is a separately named permit/listing-
persistence study with censoring, not a restaurant-survival model.

### October 20 adjudication packet

The private `data/evaluation/lifespans/adjudication_packet_20261020_v4.csv`
joins all 5,999 unresolved archive candidates to the exact-address SLA and
conservative Foursquare leads, then checks CAMIS, name, and address against the
current DOHMH active feed. Its SHA-256 manifest records every input and output.
The companion `_probability_sample.csv` contains 600 cases drawn with seed 440
from 4,030 candidates first observed between April 2023 and July 22, 2025,
with a recorded inclusion probability of 600/4,030. This is an **unlabeled
review sample**, not a training cohort or a representative sample of all NYC
restaurants. The candidate frame itself may omit former businesses.

The current-feed check found 4,481 same-name/address CAMIS matches, 21 CAMIS
records needing name/address reconciliation, and 1,497 absent CAMIS records.
Among those 1,497, another 104 have an exact same-name/address current record
under a *different* CAMIS. This is a possible permit/identity change, not proof
of business continuity; the remaining 1,393 are also not closure evidence.
Review tiers include 158 identity/date conflicts and 37 additional external
closure leads; none establishes a
permanent closure date. Reproduce the packet privately with:

```bash
.venv/bin/python demo/prepare_survival_adjudication.py \
  --queue data/evaluation/lifespans/review_queue_20261020_v4.csv \
  --sla-leads data/evaluation/lifespans/sla_review_leads_20261020_v2.csv \
  --foursquare-leads data/evaluation/lifespans/foursquare_review_leads_20261020_v2.csv \
  --inspections data/raw_sources/restaurants/20261020T140647Z_509a8026/rows.csv \
  --output data/evaluation/lifespans/new_adjudication_packet.csv
```

For the first temporal-spatial research run, freeze the cutoff at
`2025-01-01` before adjudicating outcomes. The existing evaluator requires
training outcomes recorded before that date and later-baseline test cases in
different NTA neighborhoods. The 600-case sample alone is not guaranteed to
meet the minimum class counts or test size; expand verification from the full
packet if needed, without selecting test cases by observed outcome.

Review each case's actual operating baseline and stable identity, including
rebrands, ownership changes, moves, and CAMIS changes. A pre-permit inspection
or archive listing is only a lead. Record the date and separate source for a
same-business follow-up at 365-455 days or for a confirmed permanent closure
within 365 days. Mark ambiguous, temporary, missing, or insufficiently mature
cases as censored/unresolved. Have a second reviewer check both classes and
all identity conflicts. Only then create the separate verified evidence file.

The guarded command was run against the v4 packet with that cutoff: it returned
`needs_verified_outcomes` for all 5,999 records, wrote no cohort or model,
and found no missing historical-core snapshot feature. This is the correct
state until independent outcome evidence is obtained.

An editable, unsent FOIL request for the missing permit lifecycle records is
at `demo/DOHMH_PERMIT_HISTORY_FOIL_DRAFT.md`. It asks for a full historical
frame and identifier crosswalk so the team can distinguish permanent exits
from rebrands, moves, ownership transfers, temporary suspensions, and gaps.

The NYS Food Service Establishment inactive inspection table excludes New York
City, so it cannot supply labels for this cohort. DCWP license surrenders and
inactive SLA licenses can occur after ownership, name, location, or license
changes and are only corroboration leads. A bot may gather and rank such
official-source leads across the full queue, but it must not turn their absence
or inactive status into a permanent-closure label.

Request a bulk machine-readable DOHMH food-service permit lifecycle extract,
keyed by CAMIS, through the agency's FOIL channel. Ask for issue and effective
dates, status changes, surrender/cancellation/expiration dates and reason
codes, plus any fields distinguishing permanent closure, ownership transfer,
relocation, administrative inactivity, and reopening. Specify the 2022-2026
period and ask for the complete historical cohort, not only the current active
feed. DOHMH may not hold every requested field; inspect its actual schema and
definitions before labeling. Official request instructions are at
https://www.nyc.gov/site/doh/about/ogc-foil.page.

After adjudication, populate the evidence fields described below. The guarded
one-command research run builds the historical cohort, enforces date and
provenance checks, applies a predeclared neighborhood-disjoint temporal split,
and saves a private audit, metrics, and fitted logistic/gradient-boosting
estimators only when the minimum evidence gate passes:

```bash
.venv/bin/python demo/run_survival_training.py \
  --evidence data/evaluation/verified_survival_evidence.csv \
  --cutoff YYYY-MM-DD
```

If evidence remains unverified, it reports `needs_verified_outcomes` and writes
no cohort or model. A valid but undersized cohort reports
`insufficient_evidence`; its report is not a successful model result. Each
successful run gets a new directory under `data/evaluation/runs/`. The saved
estimators expect `log1p`-transformed inputs in the recorded feature order and
are research artifacts, not deployed dashboard predictors. Use
`--validation-mode spatial_exploratory` without a cutoff only to debug when a
later temporal test frame is not yet available; it is not prospective validation.

1. Establish a restaurant's identity, location, and operation at the baseline
   with dated evidence. A permit application or setup inspection is a lead, not
   proof of operation. Resolve changes of owner, name, address, or CAMIS before
   assigning a stable business ID.
2. For continued operation, obtain a distinct dated source showing the same
   business operating 365-455 days after baseline. For failure, verify
   permanent closure within 365 days; record when it happened and when the
   evidence became available. Treat a temporary health closure, inspection
   gap, absent listing, expired outdoor license, or ambiguous rebrand as
   unresolved.
3. Preserve references, dates, reviewer notes, and any disagreement. Review a
   sample of both classes with a second reviewer before finalizing the cohort.
   Do not train from either review queue as-is. The current inventory is
   survivor-selected; DOT outdoor-dining participants are a selected subset.
4. Define a source frame that includes former as well as currently operating
   restaurants. Use a probability-sampled, separately adjudicated test cohort
   if the goal is a calibrated citywide probability. Known sampling weights
   can adjust review strata, but cannot fix missing restaurant types in the
   original frame.

Prepare an inspection evidence packet for reviewers with:

```bash
.venv/bin/python demo/prepare_survival_evidence.py \
  --review data/evaluation/historical_review_20261013T193016Z.csv \
  --inspections data/raw_sources/restaurants/<current-revision>/rows.csv
```

The new private CSV retains the review fields and adds CAMIS, dated inspection
leads, match status, and a record-specific source link. Reviewers must verify
identity, confirm operation at baseline, obtain independent outcome evidence,
and then fill the original evidence fields. A follow-up inspection can support
continued operation, but cannot establish permanent closure. Set `as_of_date`
to the verified baseline date, not automatically to the DOT setup-inspection
date. The packet and its SHA-256 manifest are not training inputs as-is.

## Go/No-Go For The First Run

- Freeze the label definition, feature list, model settings, and cutoff before
  opening test results. Train on earlier outcomes recorded before that cutoff;
  test on later baselines in different NTA neighborhoods.
- Require at least 60 train and 30 test cases, ten verified examples of each
  outcome in both partitions, and eight neighborhoods overall. Report the
  actual class balance, geography coverage, exclusions, and confidence limits.
- Compare against prevalence and simple location baselines. Brier loss and
  calibration matter because ranking alone does not validate probabilities.
  Do not select the best of XGBoost, LightGBM, and CatBoost on the final test
  set; use development folds for any later tuning and keep one untouched test.
- Keep all current dashboard scores separate from this evaluation. Do not use
  current restaurant counts, cuisine inventory, inspection actions, or
  post-baseline data as predictors of the one-year outcome.

If verified 2023-24 cases arrive before a later baseline frame, run the
explicit `spatial_exploratory` mode to debug the pipeline with disjoint
neighborhoods. It cannot establish a future-year forecast or calibrated
citywide survival probability. The temporal-spatial mode remains the required
test before any deployment claim.

## Remaining Gaps

There is no independently verified outcome file yet, so the real survival
model has **not** been trained. The official Dining Out NYC locations feed
has 2025 license issue dates but lists only currently issued licenses; it is
not a balanced 2025 baseline or closure source. The archived DOHMH snapshots
now provide an earlier candidate baseline frame, but reviewers must still
verify baseline operation and follow-up outcomes before a temporal holdout.
The current
four-feature model omits briefing variables that lack defensible historical
values for these businesses: price tier, store size, site-level pedestrians,
and a complete age profile. Those can be added only after their earlier
publisher vintages or verified business records are available.

The next methodological extension is a censored time-to-event model, which
could use different follow-up lengths without inventing binary failures. It
still requires reliable closure dates and a representative baseline frame.
Only after the general model is evaluated should its location prior be tested
alongside the briefing's cuisine-specific Huff/hex demand model. Neither model
should be described as measuring profitability without sales or financial
outcomes.

Implementation and commands: [EVALUATION.md](EVALUATION.md).
