"""Audit a reproducible random sample of proxy disappearances without assigning closures."""

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address


def read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def audit(cohort, adjudication, inspections, source_reviews, output, size=12, seed=440):
    frame = sorted((row for row in read(cohort) if row["archive_reobserved_after_365_days"] == "0"),
                   key=lambda row: row["business_id"])
    queue = {row["business_id"]: row for row in read(adjudication)}
    if len({row["business_id"] for row in frame}) != len(frame):
        raise ValueError("Duplicate proxy IDs")
    chosen = {row["business_id"] for row in random.Random(seed).sample(frame, min(size, len(frame)))}
    reviews = json.loads(Path(source_reviews).read_text())
    if not set(reviews) <= chosen:
        raise ValueError("Source review includes cases outside the probability sample")
    keys = {(queue[row["business_id"]]["borough"].lower(),
             *candidate_address(queue[row["business_id"]]["candidate_address"], queue[row["business_id"]]["borough"]))
            for row in frame}
    current = defaultdict(dict)
    with Path(inspections).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            key = (row["boro"].lower(), *normalized_address(row["building"] + " " + row["street"], row["zipcode"], row["boro"]))
            if key in keys:
                current[key][row["camis"]] = row["dba"]
    rows = []
    for item in frame:
        key = item["business_id"]
        candidate = queue[key]
        address_key = (candidate["borough"].lower(), *candidate_address(candidate["candidate_address"], candidate["borough"]))
        review = reviews.get(key, {})
        rows.append({"business_id": key, "candidate_name": candidate["candidate_name"],
                     "candidate_address": candidate["candidate_address"], "borough": candidate["borough"],
                     "updated_identity_review": candidate["identity_review"],
                     "current_same_address_camis_and_names": json.dumps(current.get(address_key, {}), sort_keys=True),
                     "in_probability_sample": key in chosen, "inclusion_probability": len(chosen)/len(frame),
                     "source_review_status": review.get("status", "not_reviewed"),
                     "source_urls": ";".join(review.get("urls", [])), "review_notes": review.get("notes", ""),
                     "outcome_status": "unresolved", "independently_verified": False})
    output = Path(output)
    sample_path = output.with_name(output.stem + "_sample.csv")
    manifest_path = output.with_suffix(".manifest.json")
    if any(path.exists() for path in (output, sample_path, manifest_path)):
        raise FileExistsError("Audit outputs must be new files")
    output.parent.mkdir(parents=True, exist_ok=True)
    for path, subset in ((output, rows), (sample_path, [row for row in rows if row["in_probability_sample"]])):
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(subset)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "frame_rows": len(frame),
               "sample_rows": len(chosen), "seed": seed, "sample_inclusion_probability": len(chosen)/len(frame),
               "source_review_counts": dict(Counter(row["source_review_status"] for row in rows if row["in_probability_sample"])),
               "frame_identity_status": dict(Counter(row["updated_identity_review"] for row in rows)),
               "frame_with_current_same_address_listing": sum(row["current_same_address_camis_and_names"] != "{}" for row in rows),
               "verified_closure_events": 0, "training_eligible": False,
               "warning": "Search and directory listings have uncertain freshness. No dated permanent-closure event was established; no closure rate can be estimated from unresolved cases.",
               "source_sha256": {str(Path(path).name): fingerprint(path) for path in (cohort, adjudication, inspections, source_reviews)},
               "output_sha256": {path.name: fingerprint(path) for path in (output, sample_path)}}
    manifest_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("cohort", "adjudication", "inspections", "source-reviews", "output"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.cohort, args.adjudication, args.inspections, args.source_reviews, args.output), indent=2))


if __name__ == "__main__":
    main()
