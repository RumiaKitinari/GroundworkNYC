# NYC Restaurant Permit-Presence Tracking

## Target and source

This is a research-only precursor to the general restaurant survival model.
The [NYC DOHMH inspection export](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j)
contains restaurants with an active permit on its `RECORD DATE`; `CAMIS` is the
permit identifier. It includes restaurants with violations, restaurants with
no violations, and permit applicants not yet inspected. Passing an inspection
is **not** the inclusion criterion. The export is a rolling current-active
table, not a historical list of permanent closures.

The eventual one-year proxy is **same-CAMIS presence in a complete export
365-455 days after a dated baseline**. It measures permit persistence, not
restaurant survival, success, or profitability. A missing CAMIS may indicate
deactivation, ownership/permit change, a source problem, or another event.
Temporary DOHMH closure actions must not be used as business failures.

No verified official full 2023-25 snapshot archive has been identified. NYC's
[2020 Open Data report](https://opendata.cityofnewyork.us/wp-content/uploads/2020/09/2020_OpenDataForAllReport_Full.pdf)
states that its proposed restaurant historical dataset was incomplete and
would not be released. Its description concerns pre-letter-grade inspections,
not a saved sequence of full active-permit exports. Third-party copies need
independent date, completeness, and provenance checks before inclusion.

## Local process

The existing daily `restaurants` download keeps immutable, complete raw
revisions in `data/raw_sources/restaurants/`. It checks the publisher row count
and version during download. After a new revision, `demo/maintain_data.py`
runs `demo/permit_presence.py` automatically. To rebuild or inspect it manually:

```bash
.venv/bin/python demo/permit_presence.py
```

The tracker verifies each raw file against its manifest, collapses repeated
violation rows to one CAMIS per publisher `RECORD DATE`, rejects incomplete or
citywide-coverage-drop snapshots, and preserves fingerprinted per-revision
summaries. Its private outputs are:

- `data/evaluation/permit_presence/status.json`: observation span, counts,
  source fingerprints, one-year readiness, and limitations.
- `data/evaluation/permit_presence/generated_review_leads.csv`: CAMIS IDs
  missing from at least two later full snapshots at least seven days apart.
- `data/evaluation/permit_presence/review_sample.csv`: deterministic sample
  of up to ten leads per borough for manual verification.

The generated files can be rebuilt and must not be used for handwritten
adjudication. Keep reviewer decisions in a separate, dated evidence file.
Never call a review lead a verified closure. The tracker flags exact
name/address matches under another CAMIS as possible permit replacements.
Reappearance removes a CAMIS from the current disappearance queue. Missing
records caused by an incomplete publisher download must stop the pipeline.

## Before modeling

1. Obtain at least one full baseline and full follow-up export 365-455 days
   apart. Confirm that the same CAMIS was present or repeatedly absent near
   follow-up; resolve replacements and ambiguous identities.
2. Manually review a borough-stratified sample of both present and absent
   cases. Record source links, dates, reviewer decisions, and error rates.
3. Freeze predictor vintages available **before** each baseline. No current
   inspection status, later restaurant inventory, or follow-up facts may enter
   features. Use a later temporal and neighborhood-disjoint holdout.
4. Label any resulting model `permit persistence`, report calibration and
   uncertainty, and keep it offline. Separately verified operating and
   permanent-closure outcomes are required for a restaurant survival claim.

The `/api/evaluation` backend endpoint exposes tracking readiness,
but no permit-persistence model or customer-facing probability is published.
