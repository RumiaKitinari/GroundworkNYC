# Feature Repairs and Training Readiness

## Completed October 28

Canonical private package: `data/output/feature_repairs/20261028_v3/`.
Validation: `data/output/feature_repairs_validation/20261028_v3.json`.
Earlier v1/v2 directories are intermediate artifacts, not the final package.

The scripts use the existing integrated release, frozen research cohort,
historical snapshot loader, original inspection captures, and existing evidence
ledger. No source dataset, published master, frontend, frozen benchmark, or
live model was overwritten. No files were uploaded or pushed to GitHub.

## Restaurant Review Queue

The full active inventory contains 31,232 restaurants. The review queue has
5,946 unique CAMIS records, including overlapping categories:

- 4,964 labels assigned by uncertain/default rules rather than direct/keyword
  mappings. Not all of these have usable tract assignments.
- 371 records flagged for taxonomy review, such as broad fusion categories
  or mappings that collapse distinct cuisines. A legacy `direct` label does
  not by itself establish that a 50-category mapping is semantically precise.
- 790 records with missing/unusable coordinates or unmatched tract IDs.
  This is broader than the previously reported 788 unmatched-tract records.
- 3,353 queued records lie within a 2,400-meter straight-line review radius of
  at least one of 157 unique top-ranked candidate properties across four
  prospective concepts. This radius orders review effort; it is not a walking
  route, a demand estimate, or a new prediction feature.

`restaurant_repair_queue.csv` includes original labels, label provenance,
taxonomy flags, location quality, candidate proximity, and blank reviewer,
evidence URL, approved-label, and identity-resolution fields. The priority
uses prospective candidate geography, not survival outcomes or assessment
errors. Unlocated records have their own queue because proximity cannot be
estimated safely for them.

Existing local archives supplied 58 same-CAMIS/name/address proposals: 49
coordinate restorations and nine cuisine suggestions. The cuisine suggestions
remain unapproved: old and current cuisine descriptions can conflict, and a
name/address match does not prove that an older label remains correct.

## Coordinate Candidate Dataset

`current_restaurants_coordinate_candidate.csv` preserves the complete current
entity inventory and restores 49 missing coordinates using archived values
under the same CAMIS, normalized name, borough, building, street, and ZIP.
Every restored point lies in one unique NYC tract; tract assignment uses
polygon containment, not nearest-centroid guessing. No valid existing
coordinate was replaced. Other entity attributes, including cuisine, remain
unchanged.

`coordinate_restoration_audit.csv` records each proposal and its tract
assignment. The new column `coordinate_repair_basis` distinguishes original
records from archive-restored records. These are corroborated source-based
repairs, not independently verified current operating locations. The candidate
dataset has **not** been published as a new integrated release or substituted
into live scoring. Rebuild dependent routes and competition summaries before
promoting it; do not copy its new coordinates into old route caches.

## Historical First-Stage Features

`opening_time_core_features.csv` contains all 18,860 cohort identities and
opening-date-selected historical values. The existing loader checks source
hashes, observation dates, publication dates, and tract identifiers. Unknown
historical values remain missing; no current master value is backdated.
`opening_time_feature_provenance.csv` records the source for every value.

| Historical Feature | Cohort Rows With a Dated Value |
| --- | ---: |
| Population density | 14,012 |
| Median household income | 13,832 |
| Job density | 13,138 |
| Walkability | 18,850 |

There are 12,977 rows with all four features and eight with none. These figures
describe predictor availability, **not independently verified survival-label
coverage**. The loader applies fixed log1p transformations; these columns are
not interchangeable with every transform in the 35-feature research model.

`historical_feature_contract.csv` audits all 38 corrected context features.
Four have supported dated alternatives; 34 do not yet have replacements in the
historical allowlist. Historical core variables describe the selected older
measurement vintage, not reconstructed storefront-level conditions. Inverse
walkability, cuisine, synthetic rent, and the current walking graph remain
outside historical survival training.

## Chain and Outcome Evidence

`capture_time_chain_review.csv` reconstructs available capture-time names and
distinct physical addresses from the three original local inspection captures.
Repeated inspection rows and multiple CAMIS IDs at an identical name/address
do not inflate the location count. Conflicting or incomplete identities are
excluded. The latest eligible capture cannot postdate the inferred opening.

For 3,504 cohort records, an identity-stable CAMIS record exists in a prior
capture. Those records receive an observed same-name-location count. This is
**not verified chain ownership or concurrent trading activity**. Presence in a
capture before an inferred pre-permit opening also warrants time-origin review.
Missing earlier records remain unknown, not non-chain. No reconstructed chain
feature has been added to the training allowlist.

`cohort_evidence_crosswalk.csv` joins all 18,860 cohort rows to the existing
adjudication packet and operating-event summary. Of these, 4,686 have dated
operation leads in the inspected evidence ledger. Within the available leads,
the chronology check found zero operation dates before the inferred opening
and zero after a finite proxy-exit upper bound. This does not clear the other
records or establish permanent closures.

The joined evidence contains zero independently verified permanent-exit
records. Archive disappearance, Foursquare matches, liquor-license status,
temporary health closures, and identity conflicts remain explicitly distinct.
No new permanent-closure labels or exact opening dates were invented.

## Next Evaluation Protocol

`next_evaluation_protocol.json` is a written proposal for team agreement before
the next fit. It records the target, historical feature boundary, metric
definitions, temporal/spatial grouping, and promotion requirements.

The 35-feature research candidate is not automatically replaced by the dated
four-feature matrix. A verified historical model still requires suitable
baseline and outcome evidence. If the team proceeds with disappearance labels,
the experiment must remain a separately named archive-proxy analysis, with
matched-target comparisons and closure-rule sensitivity reported explicitly.

The prior reserved assessment has already been inspected and the entire cohort
appeared in earlier research CV. No globally untouched final test can be
created merely by repartitioning those rows. Independent evidence or a genuinely
protected future cohort is required for a stronger final-validation claim.

Priorities for Atharv and the team:

1. Review the dated-feature matrix and agree on the next evaluation protocol.
2. Review the nine cuisine proposals and the highest-impact remaining labels;
   retain source URLs and identity decisions rather than accepting name guesses.
3. Review candidate coordinate repairs, then rebuild spatial derivatives if
   publishing a new integrated release.
4. Reconcile time origins and independently support exit/censoring evidence;
   do not promote temporary health closures or vanished records to verified exits.

## Reproduction

From the repository root, always choose new output names:

```sh
.venv/bin/python codes/prepare_feature_repairs.py --output data/output/feature_repairs/NEW_RUN
.venv/bin/python codes/validate_feature_repairs.py --run data/output/feature_repairs/20261028_v3 --output data/output/feature_repairs_validation/NEW_VALIDATION.json
.venv/bin/python -m pytest codes demo -q
```

Validation checks 20 pinned source files, 16 output artifacts, all 18,860 cohort
identities, 59,832 dated values, and all 49 coordinate restorations. It verifies
that source data remains unchanged and no review-only chain feature or cuisine
proposal has been promoted into training or the master.
