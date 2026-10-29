"""Audit published restaurant event bounds without generating training labels."""

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_name


ROOT = Path(__file__).resolve().parents[1]


def day(value):
    return date.fromisoformat(value) if value else None


def audit_cases(registry, candidates, horizon=365):
    if horizon <= 0:
        raise ValueError("The horizon must be positive")
    index = {}
    for case in candidates:
        identifier = case["business_id"]
        if not identifier or identifier in index:
            raise ValueError("Missing or duplicate candidate ID")
        index[identifier] = case
    sources = registry["sources"]
    seen, rows = set(), []
    for evidence in registry["cases"]:
        identifier = evidence["business_id"]
        if identifier in seen or identifier not in index:
            raise ValueError("Duplicate evidence case or missing cohort candidate")
        seen.add(identifier)
        case = index[identifier]
        if normalized_name(evidence["candidate_name"]) != normalized_name(case["candidate_name"]):
            raise ValueError("Evidence name does not match the candidate")
        if candidate_address(evidence["candidate_address"], case["borough"]) != candidate_address(case["candidate_address"], case["borough"]):
            raise ValueError("Evidence address does not match the candidate")
        bounds = evidence.get("opening_bounds", {})
        opening_lower, opening_upper = day(bounds.get("lower")), day(bounds.get("upper"))
        closed_by = day(evidence.get("reported_closed_by"))
        if bool(opening_lower) != bool(opening_upper):
            raise ValueError("Opening bounds require both endpoints or neither")
        if opening_lower and (opening_lower > opening_upper or (closed_by and opening_upper > closed_by)):
            raise ValueError("Inconsistent event bounds")
        refs = evidence["source_ids"]
        if not refs or any(ref not in sources or not sources[ref]["url"].startswith("https://") for ref in refs):
            raise ValueError("Every event requires registered source URLs")
        if bounds and not set(bounds.get("source_ids", [])) <= set(refs):
            raise ValueError("Opening sources must belong to the case")
        if opening_lower and not bounds.get("source_ids"):
            raise ValueError("Opening bounds require explicit source attribution")
        if closed_by and not evidence.get("closure_source_ids"):
            raise ValueError("Closure bounds require explicit source attribution")
        if not set(evidence.get("closure_source_ids", [])) <= set(refs):
            raise ValueError("Closure sources must belong to the case")
        prepermit = day(case.get("first_operational_prepermit"))
        fsq_dates = [day(d) for d in case.get("fsq_marked_closed_dates", "").split(";") if d]
        maximum = (closed_by - opening_lower).days if closed_by and opening_lower else None
        # This is conditional calendar arithmetic, not an adjudicated event or outcome.
        conditional = "unresolved"
        if maximum is not None and maximum <= horizon:
            conditional = "reported_site_exit_by_horizon_if_identity_and_event_are_accepted"
        elif maximum is not None:
            conditional = "bounds_alone_do_not_determine_first_exit_by_horizon"
        rows.append({
            "business_id": identifier, "candidate_name": case["candidate_name"],
            "candidate_address": case["candidate_address"], "borough": case["borough"],
            "event_unit": evidence["event_unit"],
            "reported_opening_lower": opening_lower.isoformat() if opening_lower else "",
            "reported_opening_upper": opening_upper.isoformat() if opening_upper else "",
            "reported_closed_by": closed_by.isoformat() if closed_by else "",
            "maximum_opening_to_closed_by_days": maximum if maximum is not None else "",
            "conditional_horizon_result": conditional,
            "candidate_prepermit": case.get("first_operational_prepermit", ""),
            "candidate_cycle_baseline": case.get("first_cycle_inspection_lead", ""),
            "prepermit_after_reported_opening_window": bool(prepermit and opening_upper and prepermit > opening_upper),
            "minimum_prepermit_delay_days": (prepermit - opening_upper).days if prepermit and opening_upper and prepermit > opening_upper else "",
            "fsq_marked_closed_dates": case.get("fsq_marked_closed_dates", ""),
            "minimum_fsq_mark_delay_after_closed_by_days": min((d - closed_by).days for d in fsq_dates) if fsq_dates and closed_by else "",
            "identity_review": case.get("identity_review", ""),
            "same_camis_active_feed_match": case.get("identity_review") == "same_name_and_address",
            "operator_identity_verified": False, "training_eligible": False,
            "review_status": "published_evidence_requires_episode_and_target_adjudication",
            "source_urls": ";".join(sources[ref]["url"] for ref in refs),
            "source_ids": ";".join(refs), "review_notes": evidence["review_notes"],
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "data/evaluation/closure_research/event_bounds_sources_20261021.json")
    parser.add_argument("--queue", type=Path, default=ROOT / "data/evaluation/lifespans/adjudication_packet_20261020_v5.csv")
    parser.add_argument("--horizon", type=int, default=365)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text())
    with args.queue.open(newline="", encoding="utf-8-sig") as stream:
        candidates = list(csv.DictReader(stream))
    rows = audit_cases(registry, candidates, args.horizon)
    if not rows:
        raise ValueError("Empty evidence registry")
    output = args.output or ROOT / "data/evaluation/closure_research" / ("event_dates_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    with (output / "event_date_audit.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "reviewed_cases": len(rows),
              "candidate_frame_rows": len(candidates), "sampling": "targeted research, not a random validation sample",
              "horizon_days": args.horizon, "conditional_results": dict(Counter(r["conditional_horizon_result"] for r in rows)),
              "prepermit_after_reported_opening_window": sum(r["prepermit_after_reported_opening_window"] for r in rows),
              "verified_training_labels_created": 0, "training_eligible": False,
              "inputs_sha256": {"registry": fingerprint(args.registry), "queue": fingerprint(args.queue)},
              "audit_sha256": fingerprint(output / "event_date_audit.csv"), "output": str(output),
              "warning": "Calendar bounds are conditional on reported events and unresolved CAMIS/operator identity. No actual opening or closure day is imputed; no outcomes are written to the master."}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
