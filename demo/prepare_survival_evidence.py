"""Attach dated inspection leads to the historical survival review queue."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from evaluation import fingerprint
from prepare_historical_review import normalized, normalized_address
from refresh_integrated import ROOT


SOURCE_URL = "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j"
EXTRA_FIELDS = ("inspection_match_status", "inspection_camis", "inspection_baseline_lead",
                "inspection_followup_lead", "inspection_record_date", "inspection_source_url")
WARNING = ("This export contains only establishments active on its record date. Inspection matches are "
           "review leads, not verified operating or closure outcomes. Unmatched businesses are not failures.")


def day(value):
    try:
        parsed = date.fromisoformat((value or "")[:10])
    except ValueError:
        return None
    return parsed if parsed.year >= 2000 else None


def key(borough, name, address):
    return normalized(borough), normalized(name), normalized_address(address)


def build_packet(review_path, inspection_path):
    with Path(review_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = {"business_id", "borough", "candidate_name", "candidate_address",
                    "candidate_baseline_on", "verification_status", "outcome_status"}
        if not required <= set(fields):
            raise ValueError("Review queue is missing: " + ", ".join(sorted(required - set(fields))))
        if set(EXTRA_FIELDS) & set(fields):
            raise ValueError("Review queue already contains evidence-packet fields.")
        rows = list(reader)
    if len({row["business_id"] for row in rows}) != len(rows):
        raise ValueError("Review queue contains duplicate business IDs.")

    candidates = defaultdict(list)
    for index, row in enumerate(rows):
        if (row["verification_status"] != "independent_verification_required"
                or row["outcome_status"] != "unresolved"):
            raise ValueError("Use an untouched unresolved review queue; this tool must not alter adjudicated cases.")
        if not day(row["candidate_baseline_on"]):
            raise ValueError(f"Invalid candidate date for {row['business_id']}.")
        names = {row["candidate_name"]}
        if row.get("current_inventory_match_basis") == "exact_name_address" and row.get("candidate_match_name"):
            names.add(row["candidate_match_name"])
        for name in names:
            candidates[key(row["borough"], name, row["candidate_address"])].append(index)

    # Keep only exact name/address/borough matches; violation rows at one inspection collapse to one event.
    inspections = defaultdict(lambda: defaultdict(dict))
    record_dates = defaultdict(set)
    with Path(inspection_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"camis", "dba", "boro", "building", "street", "inspection_date", "action", "record_date"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("Inspection export is missing: " + ", ".join(sorted(required - set(reader.fieldnames or []))))
        for row in reader:
            match = candidates.get(key(row["boro"], row["dba"], f"{row['building']} {row['street']}"))
            if not match or not row["camis"].strip():
                continue
            inspected = day(row["inspection_date"])
            if not inspected:
                continue
            for index in match:
                record_dates[index].add((row["record_date"] or "")[:10])
                event = inspections[index][row["camis"].strip()].setdefault(inspected, set())
                event.add((row["action"] or "").strip())

    counts = Counter()
    for index, row in enumerate(rows):
        matches = inspections[index]
        row.update(dict.fromkeys(EXTRA_FIELDS, ""))
        row["inspection_source_url"] = SOURCE_URL
        row["inspection_record_date"] = max(record_dates[index], default="")
        if not matches:
            row["inspection_match_status"] = "no_exact_match"
            counts["no_exact_match"] += 1
            continue
        if len(matches) != 1:
            row["inspection_match_status"] = "ambiguous_multiple_camis"
            row["inspection_camis"] = ";".join(sorted(matches))
            counts["ambiguous_multiple_camis"] += 1
            continue
        camis, events = next(iter(matches.items()))
        row["inspection_camis"] = camis
        row["inspection_source_url"] = "https://data.cityofnewyork.us/resource/43nn-pn8j.json?" + urlencode({"camis": camis})
        eligible = sorted(when for when, actions in events.items()
                          if any(actions) and not any("closed" in action.lower() for action in actions))
        target = day(row["candidate_baseline_on"])
        baselines = [when for when in eligible if abs((when - target).days) <= 90]
        if not baselines:
            row["inspection_match_status"] = "exact_match_no_baseline_inspection"
            counts["exact_match_no_baseline_inspection"] += 1
            continue
        baseline = min(baselines, key=lambda when: (abs((when - target).days), when))
        row["inspection_baseline_lead"] = baseline.isoformat()
        followups = [when for when in eligible
                     if baseline + timedelta(days=365) <= when <= baseline + timedelta(days=455)]
        if followups:
            row["inspection_followup_lead"] = min(followups).isoformat()
            row["inspection_match_status"] = "exact_match_possible_operating_pair"
        else:
            row["inspection_match_status"] = "exact_match_baseline_only"
        counts[row["inspection_match_status"]] += 1
    return rows, fields + list(EXTRA_FIELDS), dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--inspections", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "data/evaluation" / f"historical_evidence_packet_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    manifest_path = output.with_suffix(".json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("Evidence packet already exists; choose a new output path.")
    rows, fields, counts = build_packet(args.review, args.inspections)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "review_only",
                "training_eligible": False, "rows": len(rows), "match_counts": counts,
                "source_url": SOURCE_URL, "warning": WARNING,
                "source_sha256": {"review": fingerprint(args.review), "inspections": fingerprint(args.inspections)},
                "packet_sha256": fingerprint(output)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, indent=2))


if __name__ == "__main__":
    main()
