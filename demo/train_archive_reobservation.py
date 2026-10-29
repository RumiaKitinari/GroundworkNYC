"""Train an offline archive-reobservation proxy, never a restaurant survival model."""

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from evaluation import HISTORICAL_CORE_FEATURES, feature_vector, fingerprint, train_benchmark
from prepare_historical_cohort import read_snapshots
from refresh_integrated import ROOT


LIFESPANS = ROOT / "data/evaluation/lifespans/restaurant_lifespans_20261020_v4.csv"
SNAPSHOTS = ROOT / "data/evaluation/snapshots/2023-04-v0/historical_core_snapshots.json"
SOURCE_URL = "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j"
MATRIX_FIELDS = ("business_id", "geoid", "nta_code", "borough", "as_of_date",
                 "last_snapshot", "archive_observed_through", "archive_reobserved_after_365_days",
                 "features_available_on", "proxy_label_basis", "posthorizon_absent_captures",
                 *HISTORICAL_CORE_FEATURES)


def strict_evidence(adjudication_path, lifespan_manifest_path, lifespans_path):
    manifest = json.loads(Path(lifespan_manifest_path).read_text(encoding="utf-8"))
    if manifest.get("output_sha256") != fingerprint(lifespans_path):
        raise ValueError("Lifespan manifest does not match the candidate table")
    captures = sorted({date.fromisoformat(value) for value in manifest.get("snapshot_dates", [])})
    if len(captures) < 3:
        raise ValueError("Strict proxy requires at least three dated captures")
    with Path(adjudication_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        needed = {"business_id", "identity_review", "current_active_feed_status",
                  "other_current_camis_same_name_address", "verification_status", "outcome_status",
                  "first_cycle_inspection_lead", "geoid", "borough"}
        if not needed <= set(reader.fieldnames or []):
            raise ValueError("Strict proxy requires the full unresolved adjudication packet")
        cases = list(reader)
    indexed = {row["business_id"]: row for row in cases}
    if len(indexed) != len(cases) or not all(row["business_id"] for row in cases):
        raise ValueError("Adjudication packet has duplicate or empty business IDs")
    if any(row["verification_status"] != "independent_verification_required"
           or row["outcome_status"] != "unresolved" for row in cases):
        raise ValueError("Strict proxy must not consume verified survival labels")
    return indexed, captures


def build_proxy_cohort(lifespans_path, manifest_path, data_dir, today=None,
                       adjudication_path=None, lifespan_manifest_path=None):
    today = today or date.today()
    if bool(adjudication_path) != bool(lifespan_manifest_path):
        raise ValueError("Strict proxy needs both adjudication and lifespan manifests")
    strict = bool(adjudication_path)
    adjudication, captures = (strict_evidence(adjudication_path, lifespan_manifest_path, lifespans_path)
                              if strict else ({}, []))
    snapshots = read_snapshots(manifest_path, data_dir, HISTORICAL_CORE_FEATURES)
    with Path(lifespans_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"camis", "geoid", "nta_code", "borough", "clean_cohort",
                    "first_cycle_inspection", "last_snapshot", "next_snapshot"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("Lifespan table is missing required fields.")
        source = list(reader)
    if not source or len({row["camis"] for row in source}) != len(source):
        raise ValueError("The full lifespan table must have unique, nonempty CAMIS identifiers.")
    observed_through = max(date.fromisoformat(row[key]) for row in source
                           for key in ("last_snapshot", "next_snapshot") if row[key])
    if observed_through > today:
        raise ValueError("Archive observation date is in the future.")
    if strict and captures[-1] != observed_through:
        raise ValueError("Lifespan manifest capture dates disagree with candidate observations")
    rows, matrix, excluded, used = [], [], Counter(), {}
    for case in source:
        if case["clean_cohort"] != "true":
            excluded["outside_strict_candidate_cohort"] += 1
            continue
        if not case["first_cycle_inspection"]:
            excluded["no_cycle_inspection_baseline"] += 1
            continue
        if not case["geoid"] or not case["nta_code"]:
            excluded["missing_geography"] += 1
            continue
        start = date.fromisoformat(case["first_cycle_inspection"])
        last = date.fromisoformat(case["last_snapshot"])
        if start > last:
            excluded["baseline_after_last_snapshot"] += 1
            continue
        if start + timedelta(days=365) > observed_through:
            excluded["immature_followup"] += 1
            continue
        label = int(last >= start + timedelta(days=365))
        absent_captures = sum(capture >= start + timedelta(days=365) and capture > last
                              for capture in captures)
        if strict:
            lead = adjudication.get(case["camis"])
            if lead is None:
                raise ValueError(f"No adjudication record for candidate {case['camis']}")
            if (lead["first_cycle_inspection_lead"] != case["first_cycle_inspection"]
                    or lead["geoid"] != case["geoid"] or lead["borough"] != case["borough"]):
                raise ValueError(f"Adjudication identity/geography differs for {case['camis']}")
            if lead["identity_review"] in {"possible_camis_change", "name_or_address_changed"}:
                excluded["identity_conflict_censored"] += 1
                continue
            if label == 0 and (absent_captures < 2
                               or lead["identity_review"] != "no_current_camis_record"
                               or lead["current_active_feed_status"] != "absent_not_closure_evidence"
                               or lead["other_current_camis_same_name_address"]):
                excluded["insufficient_disappearance_evidence_censored"] += 1
                continue
        selected = {}
        for feature in HISTORICAL_CORE_FEATURES:
            match = next((item for item in snapshots[feature]
                          if item["available"] <= start and item["values"].get(case["geoid"])), None)
            if match is None:
                excluded[f"missing_historical_{feature}"] += 1
                break
            selected[feature] = match
        if len(selected) != len(HISTORICAL_CORE_FEATURES):
            continue
        for item in selected.values():
            used[item["path"]] = item["sha256"]
        record = {"business_id": case["camis"], "geoid": case["geoid"],
                  "nta_code": case["nta_code"], "borough": case["borough"],
                  "as_of_date": start.isoformat(), "last_snapshot": last.isoformat(),
                  "archive_observed_through": observed_through.isoformat(),
                  "archive_reobserved_after_365_days": label,
                  "features_available_on": max(item["available"] for item in selected.values()).isoformat(),
                  "proxy_label_basis": ("later_archive_reobservation" if label else
                                        "two_posthorizon_absences_no_known_successor" if strict else
                                        "no_later_archive_reobservation"),
                  "posthorizon_absent_captures": absent_captures if strict else ""}
        record.update({feature: selected[feature]["values"][case["geoid"]]
                       for feature in HISTORICAL_CORE_FEATURES})
        matrix.append(record)
        rows.append({"id": case["camis"], "group": case["nta_code"],
                     "borough": case["borough"], "x": feature_vector(record, HISTORICAL_CORE_FEATURES,
                                                                       allow_current_income=False),
                     "y": label, "as_of": start, "recorded": observed_through})
    audit = {"created_at": datetime.now(timezone.utc).isoformat(),
             "source_rows": len(source), "eligible_records": len(rows),
             "excluded": dict(excluded), "class_counts": dict(Counter(row["y"] for row in rows)),
             "archive_observed_through": observed_through.isoformat(),
             "lifespans_sha256": fingerprint(lifespans_path),
             "snapshot_manifest_sha256": fingerprint(manifest_path),
             "strict_disappearance_rule": strict,
             "adjudication_sha256": fingerprint(adjudication_path) if strict else None,
             "lifespan_manifest_sha256": fingerprint(lifespan_manifest_path) if strict else None,
             "used_snapshot_sha256": used, "inspection_source": SOURCE_URL,
             "target": "archive_reobserved_after_365_days",
             "training_eligible_for_business_survival": False,
             "warning": "Archive reobservation and sustained disappearance are not verified permanent closure, continuous operation, or profitability."}
    return rows, matrix, audit


def run(lifespans_path, manifest_path, data_dir, output_dir,
        adjudication_path=None, lifespan_manifest_path=None):
    output_dir = Path(output_dir)
    if not output_dir.resolve().is_relative_to(Path(data_dir).resolve()):
        raise ValueError("Proxy models and cohorts must remain under private data")
    if output_dir.exists():
        raise FileExistsError("Proxy run already exists; choose a new directory.")
    rows, matrix, audit = build_proxy_cohort(
        lifespans_path, manifest_path, data_dir,
        adjudication_path=adjudication_path, lifespan_manifest_path=lifespan_manifest_path)
    report, estimators = train_benchmark(rows, "archive_reobservation", audit["excluded"],
                                         features=HISTORICAL_CORE_FEATURES, capture_estimators=True)
    if report["status"] != "evaluated":
        return {"status": report["status"], "reason": report.get("reason"), "audit": audit}
    import joblib
    output_dir.mkdir(parents=True)
    with (output_dir / "cohort.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=MATRIX_FIELDS)
        writer.writeheader()
        writer.writerows(matrix)
    audit["cohort_sha256"] = fingerprint(output_dir / "cohort.csv")
    audit["deployment_status"] = report["deployment_status"]
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    (output_dir / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, estimator in estimators.items():
        joblib.dump(estimator, output_dir / f"{name}.joblib")
    return {"status": report["status"], "output": str(output_dir),
            "eligible_records": len(rows), "class_counts": audit["class_counts"],
            "deployment_status": report["deployment_status"],
            "gradient_boosting": report["metrics"]["hist_gradient_boosting"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifespans", type=Path, default=LIFESPANS)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, help="Unresolved packet for strict disappearance rule")
    parser.add_argument("--lifespan-manifest", type=Path, help="Matching source snapshot manifest")
    args = parser.parse_args()
    print(json.dumps(run(args.lifespans, args.snapshots, args.data_dir, args.output,
                         args.adjudication, args.lifespan_manifest), indent=2))


if __name__ == "__main__":
    main()
