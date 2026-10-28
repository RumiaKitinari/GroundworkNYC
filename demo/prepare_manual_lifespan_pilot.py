"""Select an explicitly targeted, private manual-verification pilot."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

from evaluation import fingerprint
from refresh_integrated import ROOT


FIELDS = ("business_id", "candidate_name", "candidate_address", "candidate_cuisine",
          "borough", "geoid", "nta_code", "selection_stratum", "first_operational_prepermit",
          "first_cycle_inspection_lead", "first_snapshot", "last_snapshot", "next_snapshot",
          "followup_inspection_365_455", "observation_status", "dohmh_current_record_url",
          "manual_web_search_url", "reviewer", "reviewed_on", "restaurant_eligibility",
          "identity_status", "baseline_operating", "as_of_date", "baseline_source_reference",
          "outcome_status", "outcome_observed_on", "outcome_recorded_on",
          "outcome_source_reference", "review_notes")
SLA_FIELDS = ("sla_match_status", "sla_active_ids", "sla_inactive_ids",
              "sla_inactive_expiration_dates", "sla_license_descriptions",
              "sla_active_source_url", "sla_inactive_source_url")


def _rank(row, seed):
    return hashlib.sha256(f"{seed}:{row['business_id']}".encode("utf-8")).hexdigest()


def _stratified_exits(rows, count, seed):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["borough"], row["first_operational_prepermit"][:4])].append(row)
    for group in groups.values():
        group.sort(key=lambda row: _rank(row, seed))
    selected = []
    while len(selected) < count and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and len(selected) < count:
                selected.append(groups[key].pop(0))
    return selected


def select_pilot(queue_path, as_of, exit_count=20, comparison_count=20, seed=440):
    if exit_count < 0 or comparison_count < 0:
        raise ValueError("Pilot counts must be nonnegative.")
    with Path(queue_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        needed = {"business_id", "candidate_name", "candidate_address", "candidate_cuisine",
                  "borough", "geoid", "nta_code", "first_operational_prepermit",
                  "first_cycle_inspection_lead", "first_snapshot", "last_snapshot", "next_snapshot",
                  "followup_inspection_365_455", "observation_status", "review_priority",
                  "verification_status", "outcome_status"}
        if not needed <= set(reader.fieldnames or []):
            raise ValueError("Review queue is missing: " + ", ".join(sorted(needed - set(reader.fieldnames or []))))
        rows = list(reader)
    if len({row["business_id"] for row in rows}) != len(rows):
        raise ValueError("Review queue has duplicate business IDs.")
    if any(row["verification_status"] != "independent_verification_required"
           or row["outcome_status"] != "unresolved" for row in rows):
        raise ValueError("Pilot selection requires an untouched, unresolved review queue.")
    earliest_features = date(2023, 4, 4)
    latest_prepermit = as_of - timedelta(days=365)
    eligible = [row for row in rows if earliest_features <= date.fromisoformat(
        row["first_operational_prepermit"]) <= latest_prepermit]
    exits = _stratified_exits([row for row in eligible if row["review_priority"] ==
                               "snapshot_exit_within_year_review"], exit_count, seed)
    if len(exits) < exit_count:
        raise ValueError(f"Only {len(exits)} suspected exits meet the dated pilot criteria.")
    controls = [row for row in eligible if row["review_priority"] ==
                "operational_inspection_followup_review"]
    controls.sort(key=lambda row: _rank(row, seed))
    selected_controls, used = [], set()
    for exit_row in exits[:comparison_count]:
        same = next((row for row in controls if row["business_id"] not in used and
                     row["borough"] == exit_row["borough"] and
                     row["first_operational_prepermit"][:4] ==
                     exit_row["first_operational_prepermit"][:4]), None)
        if same is not None:
            selected_controls.append(same)
            used.add(same["business_id"])
    for row in controls:
        if len(selected_controls) >= comparison_count:
            break
        if row["business_id"] not in used:
            selected_controls.append(row)
            used.add(row["business_id"])
    if len(selected_controls) < comparison_count:
        raise ValueError(f"Only {len(selected_controls)} comparison cases meet the dated pilot criteria.")

    output = []
    for stratum, selected in (("snapshot_exit_review", exits),
                              ("inspection_followup_review", selected_controls)):
        for row in selected:
            item = dict.fromkeys(FIELDS, "")
            item.update({key: row[key] for key in (
                "business_id", "candidate_name", "candidate_address", "candidate_cuisine",
                "borough", "geoid", "nta_code", "first_operational_prepermit",
                "first_cycle_inspection_lead", "first_snapshot", "last_snapshot", "next_snapshot",
                "followup_inspection_365_455", "observation_status")})
            item["selection_stratum"] = stratum
            item["dohmh_current_record_url"] = (
                "https://data.cityofnewyork.us/resource/43nn-pn8j.json?" +
                urlencode({"camis": row["business_id"]}))
            query = f"{row['candidate_name']} {row['candidate_address']} NYC restaurant"
            item["manual_web_search_url"] = "https://www.google.com/search?q=" + quote(query)
            item["outcome_status"] = "unresolved"
            output.append(item)
    return output, {"eligible_queue_rows": len(eligible),
                    "selected_by_stratum": dict(Counter(row["selection_stratum"] for row in output)),
                    "selection_method": "targeted_case_comparison_not_a_probability_sample"}


def enrich_sla(rows, leads_path):
    with Path(leads_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"business_id", *SLA_FIELDS} <= set(reader.fieldnames or []):
            raise ValueError("SLA leads file is missing review fields.")
        leads = {row["business_id"]: row for row in reader}
    if any(row["business_id"] not in leads for row in rows):
        raise ValueError("An SLA leads row is missing for a selected pilot case.")
    for row in rows:
        row.update({field: leads[row["business_id"]][field] for field in SLA_FIELDS})
    return rows


def write_pilot(queue_path, output_path, as_of, exit_count=20, comparison_count=20,
                seed=440, sla_leads=None):
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("Pilot output or manifest already exists.")
    rows, summary = select_pilot(queue_path, as_of, exit_count, comparison_count, seed)
    if sla_leads is not None:
        enrich_sla(rows, sla_leads)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=(*FIELDS, *SLA_FIELDS) if sla_leads else FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "as_of": as_of.isoformat(),
                "seed": seed, "rows": len(rows), **summary,
                "source_sha256": {"queue": fingerprint(queue_path),
                                  "sla_leads": fingerprint(sla_leads) if sla_leads else None},
                "output_sha256": fingerprint(output_path),
                "training_eligible": False,
                "warning": "This is an enriched manual-review pilot, not a representative sample or verified survival cohort. The pre-permit date is not an operating baseline; all outcomes remain unresolved."}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--exit-count", type=int, default=20)
    parser.add_argument("--comparison-count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=440)
    parser.add_argument("--sla-leads", type=Path, help="Optional official SLA review-leads CSV")
    args = parser.parse_args()
    try:
        print(json.dumps(write_pilot(args.queue, args.output, args.as_of,
                                     args.exit_count, args.comparison_count, args.seed,
                                     args.sla_leads), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Manual pilot preparation failed: {error}\n")


if __name__ == "__main__":
    main()
