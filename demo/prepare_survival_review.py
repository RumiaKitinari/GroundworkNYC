"""Sample current restaurants for independent outcome review; never assign labels."""

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evaluation import fingerprint
from prepare_historical_cohort import EVIDENCE_FIELDS
from refresh_integrated import CURRENT, BASELINE, ROOT


CONTEXT_FIELDS = ("candidate_name", "candidate_address", "candidate_source_url",
                  "last_inspection_on", "closure_order_seen", "review_note")
REVIEW_FIELDS = EVIDENCE_FIELDS + CONTEXT_FIELDS
WARNING = ("These are current-snapshot inspection records, not historical closure cases. "
           "A DOHMH closure order is not permanent closure. Obtain former-business cases "
           "from independent dated sources; verify both baseline and follow-up evidence.")


def build_review_queue(candidates_path, master_path, per_borough=20, seed=440):
    with Path(master_path).open(newline="", encoding="utf-8-sig") as stream:
        geography = {row["geoid"]: row for row in csv.DictReader(stream)}
    groups = defaultdict(list)
    counts = Counter()
    with Path(candidates_path).open(newline="", encoding="utf-8-sig") as stream:
        for candidate in csv.DictReader(stream):
            counts["source_rows"] += 1
            tract = geography.get(candidate["geoid"])
            if not tract or not tract.get("nta_code") or not tract.get("borough"):
                counts["missing_geography"] += 1
                continue
            groups[tract["borough"]].append((candidate, tract))
    rng = random.Random(seed)
    queue = []
    for borough in sorted(groups):
        for candidate, tract in rng.sample(groups[borough], min(per_borough, len(groups[borough]))):
            row = dict.fromkeys(REVIEW_FIELDS, "")
            row.update(business_id=candidate["business_id"], geoid=candidate["geoid"],
                       nta_code=tract["nta_code"], borough=borough,
                       verification_status="independent_verification_required",
                       outcome_status="unresolved", candidate_name=candidate["name"],
                       candidate_address=candidate["address"],
                       candidate_source_url=candidate["source_url"],
                       last_inspection_on=candidate["last_inspection_on"],
                       closure_order_seen=candidate["closure_order_seen"],
                       review_note="Current-snapshot candidate only; independently verify a historical baseline and later status.")
            queue.append(row)
    return queue, dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, help="Private outcome-candidates CSV")
    parser.add_argument("--per-borough", type=int, default=20)
    parser.add_argument("--output", type=Path, help="Private, new review-queue CSV")
    args = parser.parse_args()
    if args.per_borough < 1:
        parser.error("--per-borough must be positive")
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    candidates = args.candidates or max((ROOT / "data/evaluation").glob("outcome_candidates_*.csv"),
                                       key=lambda path: path.stat().st_mtime)
    master = release / "master_tract_features.csv"
    output = args.output or ROOT / "data/evaluation" / f"survival_review_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Review queue already exists; choose a new output path.")
    queue, counts = build_review_queue(candidates, master, args.per_borough)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(queue)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "review_only",
                "training_eligible": False, "rows": len(queue), "by_borough": dict(Counter(row["borough"] for row in queue)),
                "source_rows": counts, "source_fingerprints": {str(candidates): fingerprint(candidates),
                                                          str(master): fingerprint(master)},
                "warning": WARNING}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, indent=2))


if __name__ == "__main__":
    main()
