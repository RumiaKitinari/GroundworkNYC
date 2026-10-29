"""Join independently verified outcomes to dated, tract-level feature snapshots."""

import argparse
import csv
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from evaluation import FEATURES, HISTORICAL_CORE_FEATURES, OUTCOME_METADATA, fingerprint, outcome_cohort


EVIDENCE_FIELDS = ("business_id", "geoid", "nta_code", "borough", "as_of_date",
                   "baseline_operating", "baseline_source_reference", "verification_status",
                   "outcome_status", "outcome_observed_on", "outcome_recorded_on",
                   "outcome_source_reference")


def read_snapshots(manifest_path, data_dir, features=FEATURES, today=None):
    today = today or date.today()
    data_dir = Path(data_dir).resolve()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("snapshots"), list):
        raise ValueError("The manifest must contain a snapshots list.")
    snapshots = {feature: [] for feature in features}
    for entry in manifest["snapshots"]:
        if not isinstance(entry, dict) or entry.get("feature") not in FEATURES:
            raise ValueError("Every snapshot needs a supported feature name.")
        if entry["feature"] not in snapshots:
            continue
        if entry.get("historical_reconstruction_verified") is not True or not entry.get("source_url"):
            raise ValueError("A snapshot needs verified historical provenance and a source URL.")
        path = (data_dir / entry.get("path", "")).resolve()
        if not path.is_relative_to(data_dir) or not path.is_file() or "sample" in str(path).lower():
            raise ValueError(f"Snapshot path is missing, outside private data, or a SAMPLE: {path}")
        observed = date.fromisoformat(entry["observed_through"])
        available = date.fromisoformat(entry["available_on"])
        if observed > available or available > today:
            raise ValueError(f"Invalid observation/release dates for {path}")
        digest = fingerprint(path)
        if digest != entry.get("sha256"):
            raise ValueError(f"Snapshot fingerprint mismatch for {path}")
        column = entry.get("column", entry["feature"])
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not {"geoid", column} <= set(reader.fieldnames or []):
                raise ValueError(f"Snapshot needs geoid and {column}: {path}")
            values = {}
            for row in reader:
                geoid = row["geoid"].strip()
                if not geoid or geoid in values:
                    raise ValueError(f"Missing or duplicate tract ID in {path}")
                value = row[column].strip()
                if value:
                    parsed = float(value)
                    if not math.isfinite(parsed) or parsed < 0:
                        raise ValueError(f"Invalid {column} value in {path}")
                values[geoid] = value
        snapshots[entry["feature"]].append({"path": str(path.relative_to(data_dir)),
                                              "observed": observed, "available": available,
                                              "values": values, "sha256": digest,
                                              "source_url": entry["source_url"]})
    for entries in snapshots.values():
        entries.sort(key=lambda item: (item["available"], item["observed"]), reverse=True)
    return snapshots


def select_snapshot(entries, geoid, as_of):
    """Latest usable vintage that was public by the prediction date.

    Selection is independent of outcomes and other cohort rows. Publication
    dates, not just observation years, determine eligibility.
    """
    return next((item for item in entries
                 if item["observed"] <= item["available"] <= as_of
                 and item["values"].get(geoid, "") != ""), None)


def build_cohort(evidence_path, manifest_path, data_dir, today=None, features=FEATURES):
    today = today or date.today()
    snapshots = read_snapshots(manifest_path, data_dir, features, today=today)
    with Path(evidence_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = set(EVIDENCE_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Evidence file is missing: " + ", ".join(sorted(missing)))
        evidence = list(reader)
    rows, excluded, seen, used = [], Counter(), set(), {}
    for line, case in enumerate(evidence, 2):
        business_id = case["business_id"].strip()
        if not business_id or business_id in seen:
            raise ValueError(f"Line {line}: business IDs must be unique and nonempty.")
        seen.add(business_id)
        if case["verification_status"] != "independently_verified":
            excluded["unverified_evidence"] += 1
            continue
        if case["outcome_status"] == "unresolved":
            excluded["censored_unresolved"] += 1
            continue
        if case["outcome_status"] not in {"verified_operating", "verified_permanent_closure"}:
            raise ValueError(f"Line {line}: unsupported outcome status.")
        if (case["baseline_operating"].strip().lower() != "true" or not case["geoid"].strip()
                or not case["nta_code"].strip() or not case["baseline_source_reference"].strip()
                or not case["outcome_source_reference"].strip()
                or case["baseline_source_reference"].strip() == case["outcome_source_reference"].strip()):
            raise ValueError(f"Line {line}: baseline operation, geography, and independent evidence are required.")
        start = date.fromisoformat(case["as_of_date"])
        observed = date.fromisoformat(case["outcome_observed_on"])
        recorded = date.fromisoformat(case["outcome_recorded_on"])
        if not start < observed <= recorded <= today:
            raise ValueError(f"Line {line}: outcome chronology is invalid.")
        horizon = (observed - start).days
        if not ((case["outcome_status"] == "verified_operating" and 365 <= horizon <= 455)
                or (case["outcome_status"] == "verified_permanent_closure" and horizon <= 365)):
            excluded["outside_outcome_window"] += 1
            continue
        selected = {}
        for feature in features:
            match = select_snapshot(snapshots[feature], case["geoid"], start)
            if match is None:
                excluded[f"missing_historical_{feature}"] += 1
                break
            selected[feature] = match
        if len(selected) != len(features):
            continue
        for item in selected.values():
            used[item["path"]] = item["sha256"]
        row = {"business_id": business_id, "nta_code": case["nta_code"].strip(),
               "borough": case["borough"].strip(), "as_of_date": start.isoformat(),
               "features_observed_through": max(item["observed"] for item in selected.values()).isoformat(),
               "features_available_on": max(item["available"] for item in selected.values()).isoformat(),
               "baseline_operating": "true", "outcome_status": case["outcome_status"],
               "outcome_observed_on": observed.isoformat(), "outcome_recorded_on": recorded.isoformat(),
               "source_reference": f"Baseline: {case['baseline_source_reference']}; outcome: {case['outcome_source_reference']}"}
        row.update({feature: selected[feature]["values"][case["geoid"]] for feature in features})
        rows.append(row)
    if rows:
        # Reuse the evaluator's chronology and label checks before any training file is written.
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            temporary = Path(folder) / "cohort.csv"
            write_cohort(temporary, rows, features)
            checked, rejected, _ = outcome_cohort(temporary, today.isoformat(), today=today, features=features)
            if len(checked) != len(rows) or rejected:
                raise ValueError("A generated row did not pass the evaluation cohort validator.")
    missing_features = [feature for feature in features if not snapshots[feature]]
    audit = {"created_at": datetime.now(timezone.utc).isoformat(), "evidence_records": len(evidence),
             "verified_rows": len(rows), "excluded": dict(excluded), "used_snapshot_sha256": used,
             "evidence_sha256": fingerprint(evidence_path), "manifest_sha256": fingerprint(manifest_path),
             "features": list(features),
             "missing_snapshot_features": missing_features,
             "status": "ready_for_review" if rows else ("needs_historical_snapshots" if missing_features
                       else "needs_verified_outcomes"),
             "warning": "Evidence and historical vintages still require human provenance review before training."}
    return rows, audit


def write_cohort(path, rows, features=FEATURES):
    with Path(path).open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(OUTCOME_METADATA + tuple(features)) + ["borough"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--feature-set", choices=["full", "historical_core"], default="full")
    parser.add_argument("--output", type=Path, help="Private, new CSV path; never overwrites an existing cohort")
    args = parser.parse_args()
    features = FEATURES if args.feature_set == "full" else HISTORICAL_CORE_FEATURES
    rows, audit = build_cohort(args.evidence, args.snapshots, args.data_dir, features=features)
    if rows and args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        audit_path = args.output.with_suffix(".audit.json")
        if args.output.exists() or audit_path.exists():
            raise FileExistsError("The cohort or its audit already exists; choose a new output path.")
        write_cohort(args.output, rows, features)
        audit["output"] = str(args.output)
        audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
