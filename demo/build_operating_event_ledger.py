"""Preserve original capture-level inspection actions and identity for survival review."""

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address, normalized_name
from verify_archived_operating_pairs import capture_date, capture_url, parse_day, read_queue


ROOT = Path(__file__).resolve().parents[1]
REGULAR_ACTIONS = {"Violations were cited in the following area(s).",
                   "No violations were recorded at the time of this inspection."}


def identity(borough, name, address, zipcode):
    return (borough.strip().lower(), normalized_name(name),
            *normalized_address(address, zipcode, borough))


def classify_event(inspection_type, actions, identity_matches=True, valid_time=True):
    if not valid_time:
        return "invalid_or_placeholder_time"
    if not identity_matches:
        return "identity_conflict"
    actions = set(actions)
    closed = any("closed" in action.lower() for action in actions)
    reopened = "Establishment re-opened by DOHMH." in actions
    if closed and reopened:
        return "conflicting_health_actions"
    if closed:
        return "temporary_health_closure_not_permanent_exit"
    if "Non-operational" in inspection_type:
        return "nonoperational_not_trading_evidence"
    if reopened and actions <= REGULAR_ACTIONS | {"Establishment re-opened by DOHMH."}:
        return "reopening_operation_evidence"
    eligible_type = (inspection_type.startswith("Cycle Inspection /") or
                     inspection_type.startswith("Pre-permit (Operational) /"))
    if eligible_type and actions and actions <= REGULAR_ACTIONS:
        return "dated_operation_evidence"
    return "unclassified_not_operation_evidence"


def collect_ledger(candidates, captures):
    expected = {r["business_id"]: (r["borough"].lower(), normalized_name(r["candidate_name"]),
                                  *candidate_address(r["candidate_address"], r["borough"])) for r in candidates}
    if len(expected) != len(candidates):
        raise ValueError("Candidate IDs must be unique")
    groups = {}
    coverage, cross_capture_identities = {}, defaultdict(set)
    for path in captures:
        path = Path(path)
        captured = capture_date(path)
        if captured.isoformat() in coverage:
            raise ValueError("Duplicate capture date")
        count = 0
        with path.open("rb") as probe:
            opener = gzip.open if probe.read(2) == b"\x1f\x8b" else open
        with opener(path, "rt", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            required = {"CAMIS", "DBA", "BORO", "BUILDING", "STREET", "ZIPCODE", "INSPECTION DATE",
                        "INSPECTION TYPE", "ACTION", "RECORD DATE"}
            if not required <= set(reader.fieldnames or []):
                raise ValueError(f"Unsupported original capture schema: {path}")
            for number, row in enumerate(reader, start=2):
                count += 1
                camis = row["CAMIS"].strip()
                if camis not in expected:
                    continue
                kind = row["INSPECTION TYPE"].strip()
                date_raw = row["INSPECTION DATE"].strip()
                group_key = camis, captured.isoformat(), date_raw, kind
                event = groups.setdefault(group_key, {"actions": set(), "identities": set(), "record_dates": set(),
                                                      "row_numbers": [], "names": set(), "addresses": set(), "path": str(path)})
                street = " ".join((row["BUILDING"], row["STREET"]))
                who = identity(row["BORO"], row["DBA"], street, row["ZIPCODE"])
                event["identities"].add(who)
                event["names"].add(row["DBA"])
                event["addresses"].add(street.strip() + " " + row["ZIPCODE"])
                event["actions"].add(row["ACTION"].strip())
                event["record_dates"].add(row["RECORD DATE"])
                event["row_numbers"].append(number)
                cross_capture_identities[(camis, date_raw, kind)].add(who)
        coverage[captured.isoformat()] = {"path": str(path), "rows": count, "sha256": fingerprint(path)}
    ledger = []
    for (camis, captured_raw, inspected_raw, kind), event in sorted(groups.items()):
        captured, inspected = parse_day(captured_raw), parse_day(inspected_raw)
        recorded = [parse_day(d) for d in event["record_dates"]]
        valid_time = bool(inspected and recorded and all(r and inspected <= r <= captured for r in recorded))
        match = event["identities"] == {expected[camis]}
        drift = len(cross_capture_identities[(camis, inspected_raw, kind)]) > 1
        role = classify_event(kind, event["actions"], match, valid_time)
        if drift and role in {"dated_operation_evidence", "reopening_operation_evidence"}:
            role = "cross_capture_identity_drift_review"
        ledger.append({"business_id": camis, "inspection_on": inspected.isoformat() if inspected else "",
                       "raw_inspection_date": inspected_raw, "inspection_type": kind,
                       "actions_json": json.dumps(sorted(event["actions"])),
                       "source_names_json": json.dumps(sorted(event["names"])),
                       "source_addresses_json": json.dumps(sorted(event["addresses"])),
                       "identity_matches_candidate": match, "cross_capture_identity_drift": drift,
                       "event_role": role, "capture_on": captured_raw,
                       "record_dates_json": json.dumps(sorted(event["record_dates"])),
                       "capture_url": capture_url(event["path"]), "capture_path": event["path"],
                       "source_csv_record_numbers_json": json.dumps(event["row_numbers"]),
                       "duplicate_violation_rows": len(event["row_numbers"]), "training_eligible": False})
    return ledger, coverage


def summarize(candidates, ledger):
    groups = defaultdict(list)
    for event in ledger:
        groups[event["business_id"]].append(event)
    rows = []
    for case in candidates:
        events = groups[case["business_id"]]
        operations = sorted({r["inspection_on"] for r in events if r["event_role"] in
                             {"dated_operation_evidence", "reopening_operation_evidence"}})
        baseline = case["first_cycle_inspection_lead"]
        baseline_roles = sorted({r["event_role"] for r in events if baseline and r["inspection_on"] == baseline})
        rows.append({"business_id": case["business_id"], "candidate_name": case["candidate_name"],
                     "candidate_address": case["candidate_address"], "borough": case["borough"],
                     "unique_dated_operating_events": len(operations),
                     "earliest_operating_inspection": min(operations, default=""),
                     "latest_operating_inspection": max(operations, default=""),
                     "first_cycle_lead": baseline, "first_cycle_event_roles": ";".join(baseline_roles),
                     "temporary_health_closure_seen": any(r["event_role"] == "temporary_health_closure_not_permanent_exit" for r in events),
                     "identity_conflict_seen": any(r["event_role"] in {"identity_conflict", "cross_capture_identity_drift_review"} for r in events),
                     "latest_capture_seen": max((r["capture_on"] for r in events), default=""),
                     "training_eligible": False,
                     "warning": "Inspection days support dated operation, not actual opening, continuous operation, owner identity, or permanent exit. Latest capture is not last trading day."})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=ROOT / "data/evaluation/lifespans/adjudication_packet_20261020_v5.csv")
    parser.add_argument("--capture", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    candidates, _ = read_queue(args.queue)
    ledger, coverage = collect_ledger(candidates, args.capture)
    summaries = summarize(candidates, ledger)
    if not ledger:
        raise ValueError("No candidate events in the supplied captures")
    output = args.output or ROOT / "data/evaluation/closure_research" / ("operating_ledger_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    for filename, rows in (("events.csv", ledger), ("candidate_summary.csv", summaries)):
        with (output / filename).open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "candidate_rows": len(candidates),
              "capture_event_rows": len(ledger), "capture_coverage": coverage,
              "event_role_counts": dict(Counter(r["event_role"] for r in ledger)),
              "candidates_with_dated_operation": sum(r["unique_dated_operating_events"] > 0 for r in summaries),
              "candidate_cycle_leads_that_are_temporary_health_closures": sum("temporary_health_closure_not_permanent_exit" in r["first_cycle_event_roles"] for r in summaries),
              "queue_sha256": fingerprint(args.queue), "outputs_sha256": {name: fingerprint(output / name) for name in ("events.csv", "candidate_summary.csv")},
              "training_eligible": False, "verified_permanent_exit_labels_created": 0, "output": str(output),
              "warning": "All supplied capture rows scanned, no sampling. Operating evidence is not opening or uninterrupted survival. Event history is not copied from the lossy consolidated table."}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
