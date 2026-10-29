"""Turn interval-censored lifespan candidates into a human outcome-review queue."""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_restaurant_lifespans import SOURCE_URL
from evaluation import fingerprint
from prepare_historical_cohort import EVIDENCE_FIELDS


EXTRA_FIELDS = ("candidate_name", "candidate_address", "first_snapshot", "last_snapshot",
                "next_snapshot", "candidate_cuisine", "first_operational_prepermit",
                "first_cycle_inspection_lead", "followup_inspection_365_455",
                "snapshot_interval_lower_years", "snapshot_interval_upper_years",
                "observation_status", "review_priority", "archive_source_reference")


def make_review_queue(lifespans_path):
    with Path(lifespans_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        needed = {"camis", "dba", "address", "geoid", "nta_code", "borough", "open_date",
                  "clean_cohort", "survival_lower_years", "survival_upper_years",
                  "first_snapshot", "last_snapshot", "next_snapshot", "first_operational_prepermit",
                  "first_cycle_inspection", "cuisine",
                  "followup_inspection_365_455", "observation_status"}
        if not needed <= set(reader.fieldnames or []):
            raise ValueError("Lifespan table is missing: " + ", ".join(sorted(needed - set(reader.fieldnames or []))))
        source_rows = list(reader)
    queue, counts = [], Counter()
    for row in source_rows:
        if row["clean_cohort"] != "true":
            continue
        upper = row["survival_upper_years"]
        if upper not in {"", "inf"} and float(upper) <= 1:
            priority = "snapshot_exit_within_year_review"
        elif row["followup_inspection_365_455"]:
            priority = "operational_inspection_followup_review"
        elif row["survival_lower_years"] and float(row["survival_lower_years"]) >= 1:
            priority = "listed_one_year_later_review"
        else:
            priority = "censored_or_indeterminate"
        counts[priority] += 1
        candidate = dict.fromkeys(EVIDENCE_FIELDS, "")
        candidate.update({"business_id": row["camis"], "geoid": row["geoid"],
                          "nta_code": row["nta_code"], "borough": row["borough"],
                          "verification_status": "independent_verification_required",
                          "outcome_status": "unresolved",
                          "candidate_name": row["dba"], "candidate_address": row["address"],
                          "candidate_cuisine": row["cuisine"],
                          "first_snapshot": row["first_snapshot"], "last_snapshot": row["last_snapshot"],
                          "next_snapshot": row["next_snapshot"],
                          "first_operational_prepermit": row["first_operational_prepermit"],
                          "first_cycle_inspection_lead": row["first_cycle_inspection"],
                          "followup_inspection_365_455": row["followup_inspection_365_455"],
                          "snapshot_interval_lower_years": row["survival_lower_years"],
                          "snapshot_interval_upper_years": upper,
                          "observation_status": row["observation_status"], "review_priority": priority,
                          "archive_source_reference": f"{SOURCE_URL} CAMIS {row['camis']}"})
        queue.append(candidate)
    order = {name: index for index, name in enumerate(("snapshot_exit_within_year_review",
                                                       "operational_inspection_followup_review",
                                                       "listed_one_year_later_review",
                                                       "censored_or_indeterminate"))}
    queue.sort(key=lambda row: (order[row["review_priority"]],
                                row["first_operational_prepermit"], row["business_id"]))
    return queue, dict(counts)


def write_review_queue(lifespans_path, output_path):
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("Review queue or manifest already exists.")
    rows, counts = make_review_queue(lifespans_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=(*EVIDENCE_FIELDS, *EXTRA_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "rows": len(rows),
                "priority_counts": counts, "source_sha256": fingerprint(lifespans_path),
                "output_sha256": fingerprint(output_path), "training_eligible": False,
                "warning": "Candidates are unverified. Pre-operational inspection is not a verified operating baseline. Snapshot exit is not permanent closure; follow-up inspection is only a review lead."}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifespans", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = write_review_queue(args.lifespans, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Lifespan review preparation failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
