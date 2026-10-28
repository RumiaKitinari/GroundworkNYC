"""Track NYC restaurant permit presence across complete, dated DOHMH exports."""

import argparse
import csv
import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from evaluation import fingerprint
from prepare_historical_review import normalized, normalized_address
from refresh_integrated import ROOT


SOURCE_URL = "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j"
SUMMARY_FIELDS = ("camis", "dba", "boro", "building", "street", "zipcode", "nta", "identity_variants")
LEAD_FIELDS = ("camis", "dba", "boro", "building", "street", "zipcode", "nta",
               "last_present_on", "first_absent_on", "confirmed_absent_on",
               "last_present_revision", "possible_replacement_camis", "review_status", "source_url")
MIN_ABSENCE_DAYS = 7
MAX_CITYWIDE_DROP = 0.05


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def summarize_revision(revision, raw_root, output_dir, min_businesses=10000):
    files = revision.get("files") or []
    if len(files) != 1 or files[0].get("file") != "rows.csv":
        raise ValueError("A permit-presence snapshot requires the complete rows.csv export.")
    directory = revision["directory"]
    raw = (raw_root / directory / "rows.csv").resolve()
    if not raw.is_relative_to(raw_root.resolve()) or not raw.is_file():
        raise ValueError(f"Raw restaurant snapshot is missing or outside its source directory: {directory}")
    expected = files[0]
    if raw.stat().st_size != expected["bytes"]:
        raise ValueError(f"Raw restaurant snapshot has the wrong size: {directory}")
    summary = output_dir / "snapshots" / f"{directory}.csv"
    metadata = summary.with_suffix(".json")
    if summary.exists() or metadata.exists():
        if not summary.is_file() or not metadata.is_file():
            raise ValueError(f"Incomplete cached permit snapshot: {directory}")
        details = json.loads(metadata.read_text(encoding="utf-8"))
        if (details.get("raw_sha256") != expected["sha256"] or
                details.get("summary_sha256") != fingerprint(summary)):
            raise ValueError(f"Cached permit snapshot fingerprint mismatch: {directory}")
        rows = read_csv(summary)
        if (len(rows) != details.get("businesses") or len(rows) < min_businesses or
                len({row["camis"] for row in rows}) != len(rows)):
            raise ValueError(f"Cached permit snapshot has incomplete coverage: {directory}")
        return {"revision": directory, "record_date": date.fromisoformat(details["record_date"]),
                "rows": {row["camis"]: row for row in rows}, "metadata": details}

    actual_sha = fingerprint(raw)
    if actual_sha != expected["sha256"]:
        raise ValueError(f"Raw restaurant snapshot fingerprint mismatch: {directory}")
    establishments = defaultdict(Counter)
    record_dates = set()
    raw_rows = 0
    missing_camis = 0
    with raw.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        needed = set(SUMMARY_FIELDS[:-1]) | {"record_date"}
        if not needed <= set(reader.fieldnames or []):
            raise ValueError("DOHMH export lacks columns required to track permit presence.")
        for row in reader:
            raw_rows += 1
            record_dates.add((row["record_date"] or "")[:10])
            camis = row["camis"].strip()
            if not camis:
                missing_camis += 1
                continue
            identity = tuple((row[field] or "").strip() for field in SUMMARY_FIELDS[1:-1])
            establishments[camis][identity] += 1
    if raw_rows != expected["rows"] or raw_rows == 0 or missing_camis / raw_rows > 0.01:
        raise ValueError(f"DOHMH export row count or CAMIS coverage is incomplete: {directory}")
    if len(record_dates) != 1 or not next(iter(record_dates)):
        raise ValueError(f"DOHMH export has mixed or missing record dates: {directory}")
    observed = date.fromisoformat(next(iter(record_dates)))
    if observed > date.fromisoformat(revision["downloaded_at"][:10]):
        raise ValueError(f"DOHMH record date is later than its download: {directory}")
    if len(establishments) < min_businesses:
        raise ValueError(f"DOHMH export has too few unique CAMIS IDs: {directory}")
    rows = []
    for camis, versions in sorted(establishments.items()):
        identity = sorted(versions.items(), key=lambda item: (-item[1], item[0]))[0][0]
        rows.append(dict(zip(SUMMARY_FIELDS, (camis, *identity, str(len(versions))))))
    write_csv(summary, SUMMARY_FIELDS, rows)
    details = {"source": SOURCE_URL, "revision": directory, "record_date": observed.isoformat(),
               "downloaded_at": revision["downloaded_at"], "raw_rows": raw_rows,
               "businesses": len(rows), "missing_camis_rows": missing_camis,
               "raw_sha256": actual_sha, "summary_sha256": fingerprint(summary),
               "training_eligible": False}
    write_json(metadata, details)
    return {"revision": directory, "record_date": observed,
            "rows": {row["camis"]: row for row in rows}, "metadata": details}


def review_leads(snapshots):
    if len(snapshots) < 2:
        return []
    latest = snapshots[-1]
    identities = defaultdict(set)
    for camis, row in latest["rows"].items():
        identity = (normalized(row["boro"]), normalized(row["dba"]),
                    normalized_address(f"{row['building']} {row['street']}"))
        identities[identity].add(camis)
    positions = defaultdict(list)
    for index, snapshot in enumerate(snapshots):
        for camis in snapshot["rows"]:
            positions[camis].append(index)
    leads = []
    for camis, seen in positions.items():
        last_index = seen[-1]
        if last_index == len(snapshots) - 1:
            continue
        absent = snapshots[last_index + 1:]
        if len(absent) < 2 or (absent[-1]["record_date"] - absent[0]["record_date"]).days < MIN_ABSENCE_DAYS:
            continue
        last = snapshots[last_index]
        row = last["rows"][camis]
        identity = (normalized(row["boro"]), normalized(row["dba"]),
                    normalized_address(f"{row['building']} {row['street']}"))
        replacements = sorted(identities.get(identity, set()) - {camis})
        leads.append({"camis": camis, **{field: row[field] for field in SUMMARY_FIELDS[1:-1]},
                      "last_present_on": last["record_date"].isoformat(),
                      "first_absent_on": absent[0]["record_date"].isoformat(),
                      "confirmed_absent_on": absent[-1]["record_date"].isoformat(),
                      "last_present_revision": last["revision"],
                      "possible_replacement_camis": ";".join(replacements),
                      "review_status": "possible_permit_replacement" if replacements else "repeated_absence_review_lead",
                      "source_url": SOURCE_URL})
    return sorted(leads, key=lambda row: (row["boro"], row["camis"]))


def refresh(raw_root=None, output_dir=None, min_businesses=10000):
    raw_root = Path(raw_root or ROOT / "data/raw_sources/restaurants")
    output_dir = Path(output_dir or ROOT / "data/evaluation/permit_presence")
    manifest = json.loads((raw_root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source") != "restaurants" or not manifest.get("revisions"):
        raise ValueError("The restaurant raw-source manifest is missing or empty.")
    revisions = [summarize_revision(revision, raw_root, output_dir, min_businesses)
                 for revision in manifest["revisions"]]
    by_date = {}
    for snapshot in revisions:
        by_date[snapshot["record_date"]] = snapshot
    snapshots = [by_date[when] for when in sorted(by_date)]
    for older, newer in zip(snapshots, snapshots[1:]):
        drop = 1 - len(newer["rows"]) / len(older["rows"])
        if drop > MAX_CITYWIDE_DROP:
            raise ValueError(f"Citywide CAMIS coverage dropped {drop:.1%} between "
                             f"{older['record_date']} and {newer['record_date']}; review the export.")
    leads = review_leads(snapshots)
    write_csv(output_dir / "generated_review_leads.csv", LEAD_FIELDS, leads)
    sample = []
    by_borough = defaultdict(list)
    for lead in leads:
        by_borough[lead["boro"]].append(lead)
    for borough in sorted(by_borough):
        sample.extend(sorted(by_borough[borough],
                             key=lambda row: hashlib.sha256(row["camis"].encode()).hexdigest())[:10])
    write_csv(output_dir / "review_sample.csv", LEAD_FIELDS, sample)
    span = (snapshots[-1]["record_date"] - snapshots[0]["record_date"]).days
    eligible_baselines = sum(any(365 <= (later["record_date"] - baseline["record_date"]).days <= 455
                                 for later in snapshots[index + 1:])
                             for index, baseline in enumerate(snapshots[:-1]))
    status = {"updated_at": datetime.now(timezone.utc).isoformat(), "source_url": SOURCE_URL,
              "target": "one_year_permit_presence_not_restaurant_survival",
              "status": ("followup_snapshots_available_review_required" if eligible_baselines
                         else "collecting_history"),
              "one_year_training_ready": False, "dashboard_score_unchanged": True,
              "first_record_date": snapshots[0]["record_date"].isoformat(),
              "latest_record_date": snapshots[-1]["record_date"].isoformat(),
              "observation_span_days": span, "distinct_snapshot_dates": len(snapshots),
              "baseline_dates_with_one_year_followup": eligible_baselines,
              "latest_permits": len(snapshots[-1]["rows"]),
              "review_leads": len(leads), "review_sample": len(sample),
              "possible_replacements": sum(bool(row["possible_replacement_camis"]) for row in leads),
              "snapshots": [{key: snap["metadata"][key] for key in
                             ("revision", "record_date", "businesses", "raw_sha256", "summary_sha256")}
                            for snap in snapshots],
              "limitations": ["Absence is a review lead, not proof of permanent restaurant closure.",
                              "A CAMIS identifies a permit, not necessarily a continuous business.",
                              "A one-year target needs full snapshots at least 365 days apart and as-of predictors.",
                              "No permit-presence label or model is published by this tracker."]}
    write_json(output_dir / "status.json", status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(refresh(args.raw_root, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
