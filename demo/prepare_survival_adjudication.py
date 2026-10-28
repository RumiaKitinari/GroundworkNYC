"""Combine restaurant survival leads into a private, unlabeled review packet."""

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address, normalized_name
from prepare_historical_cohort import EVIDENCE_FIELDS
from refresh_integrated import ROOT


ADDED_FIELDS = (
    "review_tier", "identity_review", "current_active_feed_status", "current_names",
    "current_addresses", "current_latest_inspection", "current_record_date",
    "other_current_camis_same_name_address",
    "sla_match_status", "sla_active_ids", "sla_inactive_ids", "sla_active_source_url",
    "sla_inactive_source_url", "fsq_match_status", "fsq_place_ids",
    "fsq_marked_closed_dates", "fsq_place_urls", "reviewer", "reviewed_on",
    "identity_resolution", "review_notes", "sample_probability",
)
WARNING = (
    "All outcomes are unresolved. Current DOHMH data contains active records only; "
    "absence, archive disappearance, an inactive liquor license, or a Foursquare "
    "closure mark is not proof of permanent restaurant closure. Reconcile identity "
    "and obtain dated independent baseline and outcome evidence before training."
)


def read_index(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"business_id", "verification_status", "outcome_status"} <= set(reader.fieldnames or []):
            raise ValueError(f"Invalid review leads: {path}")
        rows = list(reader)
        fields = reader.fieldnames
    index = {}
    for row in rows:
        key = row["business_id"].strip()
        if not key or key in index:
            raise ValueError(f"Missing or duplicate business ID in {path}: {key}")
        if row["verification_status"] != "independent_verification_required" or row["outcome_status"] != "unresolved":
            raise ValueError(f"Expected unresolved, unverified leads in {path}: {key}")
        index[key] = row
    return index, fields


def read_current(path, business_ids):
    current = defaultdict(lambda: {"names": set(), "addresses": set(), "inspections": set(), "record_dates": set()})
    by_identity = defaultdict(set)
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"camis", "dba", "boro", "building", "street", "zipcode", "inspection_date", "record_date"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("Current DOHMH export is missing identity or date fields")
        for row in reader:
            key = row["camis"].strip()
            address = normalized_address(" ".join((row["building"], row["street"])), row["zipcode"], row["boro"])
            identity = (row["boro"].strip().lower(), *address)
            name = normalized_name(row["dba"])
            if key and name and all(address):
                by_identity[(identity, name)].add(key)
            if key not in business_ids:
                continue
            item = current[key]
            item["names"].add(row["dba"].strip())
            item["addresses"].add(identity)
            if row["inspection_date"]:
                item["inspections"].add(row["inspection_date"][:10])
            if row["record_date"]:
                item["record_dates"].add(row["record_date"][:10])
    return current, by_identity


def build_packet(queue_path, sla_path, foursquare_path, inspections_path, sample_size=600, seed=440,
                 today=None):
    if sample_size < 1:
        raise ValueError("sample_size must be positive")
    queue, fields = read_index(queue_path)
    sla, _ = read_index(sla_path)
    fsq, _ = read_index(foursquare_path)
    if set(queue) != set(sla) or set(queue) != set(fsq):
        raise ValueError("Lead files must contain exactly the same business IDs")
    if not set(EVIDENCE_FIELDS) <= set(fields) or set(ADDED_FIELDS) & set(fields):
        raise ValueError("Expected an untouched lifespan review queue")
    current, by_identity = read_current(inspections_path, queue)
    rows = []
    for key, source in queue.items():
        row = source.copy()
        row.update(dict.fromkeys(ADDED_FIELDS, ""))
        s, f = sla[key], fsq[key]
        identity_fields = ("candidate_name", "candidate_address", "borough",
                           "first_snapshot", "first_operational_prepermit")
        if any(source.get(field) != lead.get(field)
               for lead in (s, f) for field in identity_fields):
            raise ValueError(f"Lead identity differs from the source queue: {key}")
        for prefix, lead in (("sla_", s), ("fsq_", f)):
            for field in ADDED_FIELDS:
                if field.startswith(prefix) and field in lead:
                    row[field] = lead[field]
        item = current.get(key)
        candidate = (source["borough"].strip().lower(), *candidate_address(source["candidate_address"], source["borough"]))
        name = normalized_name(source["candidate_name"])
        other_camis = by_identity.get((candidate, name), set()) - {key}
        row["other_current_camis_same_name_address"] = ";".join(sorted(other_camis))
        if item:
            address_match = candidate in item["addresses"]
            name_match = name in {normalized_name(value) for value in item["names"]}
            row["identity_review"] = "same_name_and_address" if address_match and name_match else "name_or_address_changed"
            row["current_active_feed_status"] = "present_identity_review_required"
            row["current_names"] = ";".join(sorted(item["names"]))
            row["current_addresses"] = ";".join(sorted(" ".join(identity) for identity in item["addresses"]))
            row["current_latest_inspection"] = max(item["inspections"], default="")
            row["current_record_date"] = max(item["record_dates"], default="")
        else:
            row["identity_review"] = "possible_camis_change" if other_camis else "no_current_camis_record"
            row["current_active_feed_status"] = "absent_not_closure_evidence"
        if row["identity_review"] in {"name_or_address_changed", "possible_camis_change"} or f["fsq_match_status"] in {
                "marked_closed_but_later_dohmh_listing_review",
                "marked_closed_before_cycle_baseline_review"}:
            row["review_tier"] = "identity_or_date_conflict"
        elif f["fsq_marked_closed_dates"]:
            row["review_tier"] = "external_closure_lead"
        elif s["sla_inactive_ids"] and not s["sla_active_ids"]:
            row["review_tier"] = "inactive_license_lead"
        elif source["observation_status"] == "disappeared_between_snapshots":
            row["review_tier"] = "archive_exit_lead"
        elif source["followup_inspection_365_455"]:
            row["review_tier"] = "followup_inspection_lead"
        else:
            row["review_tier"] = "baseline_and_outcome_review"
        rows.append(row)
    # The sample is drawn before outcome review from the dated, follow-up-mature
    # archive frame. First observation is a lead, not a verified baseline.
    today = today or date.today()
    latest_eligible = today - timedelta(days=455)
    frame = [row["business_id"] for row in rows
             if row["first_snapshot"] and row["first_operational_prepermit"]
             and date.fromisoformat(row["first_snapshot"]) >= date(2023, 4, 1)
             and date.fromisoformat(row["first_snapshot"]) <= latest_eligible
             and date.fromisoformat(row["first_operational_prepermit"]) <= latest_eligible]
    rng = random.Random(seed)
    chosen = set(rng.sample(frame, min(sample_size, len(frame))))
    probability = min(sample_size, len(frame)) / len(frame) if frame else 0
    for row in rows:
        if row["business_id"] in chosen:
            row["sample_probability"] = f"{probability:.8f}"
    sample = [row for row in rows if row["business_id"] in chosen]
    summary = {"candidate_rows": len(rows), "sample_frame_rows": len(frame),
               "sample_frame_first_observation_from": "2023-04-01",
               "sample_frame_first_observation_through": latest_eligible.isoformat(),
               "sample_rows": len(sample), "seed": seed,
               "sample_inclusion_probability": probability,
               "review_tiers": dict(Counter(row["review_tier"] for row in rows)),
               "current_active_feed_status": dict(Counter(row["current_active_feed_status"] for row in rows)),
               "identity_review": dict(Counter(row["identity_review"] for row in rows)),
               "sample_years": dict(Counter(row["first_operational_prepermit"][:4] for row in sample)),
               "sample_boroughs": dict(Counter(row["borough"] for row in sample))}
    return rows, sample, fields + list(ADDED_FIELDS), summary


def write_packet(queue_path, sla_path, foursquare_path, inspections_path, output_path,
                 sample_size=600, seed=440):
    output_path = Path(output_path)
    sample_path = output_path.with_name(output_path.stem + "_probability_sample.csv")
    manifest_path = output_path.with_suffix(".manifest.json")
    if any(path.exists() for path in (output_path, sample_path, manifest_path)):
        raise FileExistsError("Packet, sample, or manifest already exists")
    rows, sample, fields, summary = build_packet(queue_path, sla_path, foursquare_path,
                                                 inspections_path, sample_size, seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for path, data in ((output_path, rows), (sample_path, sample)):
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), **summary,
                "training_eligible": False, "warning": WARNING,
                "source_sha256": {name: fingerprint(path) for name, path in (
                    ("queue", queue_path), ("sla_leads", sla_path),
                    ("foursquare_leads", foursquare_path), ("current_inspections", inspections_path))},
                "output_sha256": {output_path.name: fingerprint(output_path),
                                  sample_path.name: fingerprint(sample_path)}}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--sla-leads", type=Path, required=True)
    parser.add_argument("--foursquare-leads", type=Path, required=True)
    parser.add_argument("--inspections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=600)
    parser.add_argument("--seed", type=int, default=440)
    args = parser.parse_args()
    try:
        result = write_packet(args.queue, args.sla_leads, args.foursquare_leads,
                              args.inspections, args.output, args.sample_size, args.seed)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Survival adjudication failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
