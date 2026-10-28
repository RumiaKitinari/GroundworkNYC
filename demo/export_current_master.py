"""Export a small, checksummed current-context handoff without raw-data duplication."""

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from audit_training_data import run as audit
from evaluation import fingerprint


def export(data, destination):
    data, destination = Path(data).resolve(), Path(destination).resolve()
    archive_path = Path(str(destination) + ".zip")
    if destination.exists() or archive_path.exists():
        raise FileExistsError("Choose a new handoff directory; existing team files are preserved")
    release = (data / "integrated/current").resolve()
    audit_dir = data / "evaluation/cleaning" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = audit(data, audit_dir)
    if report["quality_issue_count"] or report["rent"]["source_or_unit_mismatches"]:
        raise ValueError("Master quality or rent reconciliation checks failed")
    destination.mkdir(parents=True, exist_ok=False)
    for name in ("master_tract_features.csv", "data_dictionary.csv", "source_catalog.csv", "feature_readiness.csv",
                 "refresh_manifest.json", "master_completion_validation.json", "master_feature_quality.csv"):
        source = release / name
        if source.exists():
            shutil.copy2(source, destination / name)
    for name in ("report.json", "rent_coverage.csv", "feature_quality.csv", "quality_issues.csv", "training_feature_policy.csv"):
        shutil.copy2(audit_dir / name, destination / ("cleaning_report.json" if name == "report.json" else name))
    observed = report["rent"]["reasons"].get("reported", 0)
    body = f"""# Groundwork NYC: Current Master Handoff

Active release: `{release.name}`. Rows: **{report['master_rows']:,}** unique 2020 tracts.
Columns: **{report['master_columns']}**, all documented. No SAMPLE inputs are used.

## Which File to Use

Use `master_tract_features.csv` as the single CURRENT-CONTEXT master. Read
`data_dictionary.csv` for exact units and `source_catalog.csv` for vintages.
This is suitable for current location screening and feature exploration.
It is NOT a labeled historical restaurant-survival training matrix.

## Rent and Missing Values

`reported_median_monthly_rent_psf` retains the actual DOF tract medians:
{observed:,} reported values, 93 publisher star markers and 904 tracts without
a latest-year source row. Missing reported values remain blank, never zero.

`commercial_rent_context_monthly_psf` supplies published rent when present,
otherwise an explicitly estimated current area rent. Always keep
`commercial_rent_context_status` and `commercial_rent_reported_missing` alongside it.
`commercial_rent_monthly_psf_estimate` contains estimates only, not observed rents.
None is the asking rent of a specific property. Units are dollars per square foot
per MONTH; the reported annual field is monthly times 12.

The selected estimator was checked with five NTA-disjoint folds on observed
tracts. See `master_completion_validation.json` for errors and limitations.
This is method-selection validation, not an untouched final accuracy test,
and the missing tracts may differ systematically from the observed ones.

`income_context_2024` similarly retains published income where present and
otherwise uses the separately labeled neighbor estimate. Original ACS income
and margins remain intact. Empty or suppressed data never becomes a zero.

## Correct Analytical Fields

- Use `rideshare_dropoffs_per_sq_mile` and `rideshare_*_dropoff_share` for
  area-allocated tract proxies. Older `dropoffs_*` values are whole-zone context
  repeated across tracts and must NOT be summed as tract trips. Allocation is
  uniform by projected overlap area; it does not locate individual trips.
- Use `subway_weekly_ridership_within_400m` for nearby station-complex activity.
  It counts complexes once, not each entrance. This is straight-line proximity,
  not a walking-network catchment or unique visitors.
- `dominant_property_zipcode` is derived from PLUTO tax lots, NOT a centroid ZIP
  or an official tract-ZIP polygon crosswalk. Its property-share column records
  how dominant it is. ZIP business totals remain ZIP context, not tract counts.
- ZIP growth compares published NAICS-722 totals only; nested industry codes
  are not summed. Postal and classification changes limit interpretation.
- `matched_restaurant_hospitality_sla_*` fields have partial exact-address
  coverage. Zero matched licenses does NOT establish that no license exists.
- `registered_properties_with_vacancy_share` describes registered BBL properties
  with reported vacancies, NOT the share of individual storefronts vacant.
  `reported_storefront_vacancy_share` intentionally remains unavailable.
- EPA intersection/transit fields are source-era built-environment context,
  not fresh intersection surveys or live transit schedules.
- Historic permitted-event fields describe whole community districts and permit
  duration, NOT observed tract attendance or pedestrian counts. Upcoming events
  remain separate. Never sum repeated district totals across its tracts.
- Percentages use 0-100, shares use 0-1. Use dictionary units, not `pct_` alone.
  Neighbor measures are area-weighted, boundary-sharing-tract means.

## Remaining Scientific Limits

1. True historical restaurant opening and permanent-closure outcomes are still
   unverified. Disappearance, a changed CAMIS, inactive liquor licenses and
   Foursquare closure marks are leads, not verified closure dates.
2. Only four predictors have verified historical release-date snapshots so far.
   Do not join the current master to old restaurant openings and report that as
   a prospective survival evaluation. The guarded trainer enforces this policy.
3. Actual storefront vacancy rates and live property asking rents require better
   source coverage or licensed listings. Property-level proxies and rent estimates
   do not erase these gaps.
4. Daytime population cannot be inferred as residents + all jobs - home-area jobs:
   those job counts are not counts of unique employed residents. No such false
   population denominator is manufactured here.
5. Opening-time competitors, turnover, chain status, sampling weights and any
   outcome-derived neighbor values must be computed as-of-date and within training
   folds, not from today's survivor inventory.

Current verified training rows: **{report['verified_training_rows']}**. Historical
predictor-complete candidates: **{report['complete_historical_core_candidates']:,}**
of **{report['historical_candidates']:,}**; these remain explicitly unlabeled.

## Reproduce and Check

Run `.venv/bin/python demo/download_sources.py --source acs_context` for the
13-table ACS bundle, and use `demo/refresh_integrated.py` for atomic releases.
Historical events, 2015 business patterns and active SLA licenses are registered repeatable sources.
The completion transform also uses pinned full TLC, EPA, PLUTO and SLA files.
Active SLA context is checked monthly through `sla_active_context`. The separate
active/inactive research archive can still be refreshed with `demo/download_sla_licenses.py`;
inactive licenses remain review evidence, never automatic closure labels.

The publication validator checks tract uniqueness, geometry coverage, every
documented column, rebuilt feature consistency and numeric quality checks.
`FILE_CHECKSUMS.json` fingerprints every handoff file. Raw source data remains
in the local GroundWork data folder and is not duplicated into this small handoff.
"""
    (destination / "READ_ME_FIRST.md").write_text(body, encoding="utf-8")
    checksums = {p.name: fingerprint(p) for p in destination.iterdir() if p.is_file()}
    (destination / "FILE_CHECKSUMS.json").write_text(json.dumps(checksums, indent=2) + "\n")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(destination.iterdir()):
            if path.is_file():
                archive.write(path, arcname=destination.name + "/" + path.name)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Handoff ZIP integrity check failed")
    return {"destination": str(destination), "master_rows": report["master_rows"],
            "master_columns": report["master_columns"], "master_sha256": fingerprint(destination / "master_tract_features.csv"),
            "quality_issues": report["quality_issue_count"], "archive": str(archive_path),
            "verified_survival_training_rows": report["verified_training_rows"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.data_dir, args.destination), indent=2))


if __name__ == "__main__":
    main()
