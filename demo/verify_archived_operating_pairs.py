"""Find dated, identity-consistent operation leads in original DOHMH captures."""

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address, normalized_name
from refresh_integrated import ROOT


SOURCE = "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j"
EXTRA = ("archive_pair_status", "baseline_inspection_on", "baseline_capture_on",
         "baseline_capture_url", "followup_inspection_on", "followup_capture_on",
         "followup_capture_url")
WARNING = ("Original captures provide dated routine-inspection and active-listing leads, "
           "not permanent-closure labels. Exact CAMIS/name/address matching cannot rule "
           "out ownership changes. All outcomes remain unresolved pending adjudication.")


def parse_day(value):
    value = (value or "").strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value[:10], pattern).date()
            return parsed if parsed.year >= 2000 else None
        except ValueError:
            continue
    return None


def capture_date(path):
    stamp = Path(path).stem.removeprefix("wayback_")
    if len(stamp) != 14 or not stamp.isdigit():
        raise ValueError(f"Capture filename needs a 14-digit Wayback timestamp: {path}")
    return date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")


def capture_url(path):
    stamp = Path(path).stem.removeprefix("wayback_")
    return (f"https://web.archive.org/web/{stamp}id_/"
            "https://data.cityofnewyork.us/api/views/43nn-pn8j/rows.csv?accessType=DOWNLOAD")


def read_queue(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = {"business_id", "candidate_name", "candidate_address", "borough",
                    "first_cycle_inspection_lead", "verification_status", "outcome_status"}
        if not required <= set(fields) or set(EXTRA) & set(fields):
            raise ValueError("Expected an untouched lifespan review or adjudication packet")
        rows = list(reader)
    if len({row["business_id"] for row in rows}) != len(rows):
        raise ValueError("Candidate business IDs must be unique")
    for row in rows:
        if (row["verification_status"] != "independent_verification_required"
                or row["outcome_status"] != "unresolved"):
            raise ValueError("Only unverified and unresolved candidates may be audited")
    return rows, fields


def collect_events(captures, candidate_ids):
    events = defaultdict(lambda: defaultdict(lambda: {"identities": set(), "closed": False}))
    coverage = {}
    for path in captures:
        path = Path(path)
        captured = capture_date(path)
        if captured in coverage:
            raise ValueError("Duplicate capture dates")
        coverage[captured] = {"path": path, "url": capture_url(path), "rows": 0}
        with path.open("rb") as probe:
            compressed = probe.read(2) == b"\x1f\x8b"
        opener = gzip.open if compressed else open
        with opener(path, "rt", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            needed = {"CAMIS", "DBA", "BORO", "BUILDING", "STREET", "ZIPCODE",
                      "INSPECTION DATE", "INSPECTION TYPE", "ACTION", "RECORD DATE"}
            if not needed <= set(reader.fieldnames or []):
                raise ValueError(f"Incomplete DOHMH capture: {path}")
            for row in reader:
                coverage[captured]["rows"] += 1
                camis = row["CAMIS"].strip()
                if camis not in candidate_ids or not row["INSPECTION TYPE"].startswith("Cycle Inspection"):
                    continue
                inspected = parse_day(row["INSPECTION DATE"])
                recorded = parse_day(row["RECORD DATE"])
                if not inspected or inspected > captured or not recorded or recorded > captured:
                    continue
                identity = (row["BORO"].strip().lower(), normalized_name(row["DBA"]),
                            *normalized_address(" ".join((row["BUILDING"], row["STREET"])), row["ZIPCODE"]))
                event = events[camis][(captured, inspected)]
                event["identities"].add(identity)
                if "closed" in row["ACTION"].lower():
                    event["closed"] = True
    return events, coverage


def build_packet(queue_path, captures):
    rows, fields = read_queue(queue_path)
    events, coverage = collect_events(captures, {row["business_id"] for row in rows})
    counts = Counter()
    for row in rows:
        row.update(dict.fromkeys(EXTRA, ""))
        target = parse_day(row["first_cycle_inspection_lead"])
        if not target:
            status = "no_cycle_baseline_lead"
        else:
            identity = (row["borough"].strip().lower(), normalized_name(row["candidate_name"]),
                        *candidate_address(row["candidate_address"]))
            matching = [(capture, inspected) for (capture, inspected), event in events[row["business_id"]].items()
                        if inspected == target and event["identities"] == {identity} and not event["closed"]]
            if not matching:
                status = "baseline_not_in_original_capture_or_identity_conflict"
            else:
                baseline_capture, baseline = min(matching)
                row["baseline_inspection_on"] = baseline.isoformat()
                row["baseline_capture_on"] = baseline_capture.isoformat()
                row["baseline_capture_url"] = coverage[baseline_capture]["url"]
                followups = [(capture, inspected) for (capture, inspected), event in events[row["business_id"]].items()
                             if capture > baseline_capture and event["identities"] == {identity} and not event["closed"]
                             and baseline + timedelta(days=365) <= inspected <= baseline + timedelta(days=455)]
                if followups:
                    followup_capture, followup = min(followups, key=lambda pair: (pair[1], pair[0]))
                    row["followup_inspection_on"] = followup.isoformat()
                    row["followup_capture_on"] = followup_capture.isoformat()
                    row["followup_capture_url"] = coverage[followup_capture]["url"]
                    status = ("original_capture_operating_pair_identity_conflict"
                              if row.get("identity_review") and row["identity_review"] != "same_name_and_address"
                              else "original_capture_operating_pair_review")
                else:
                    status = "original_capture_baseline_only"
        row["archive_pair_status"] = status
        counts[status] += 1
    return rows, fields + list(EXTRA), counts, coverage


def write_packet(queue_path, captures, output_path):
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("Output and manifest must be new files")
    rows, fields, counts, coverage = build_packet(queue_path, captures)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "rows": len(rows),
                "source": SOURCE, "capture_rows": {day.isoformat(): item["rows"] for day, item in coverage.items()},
                "status_counts": dict(counts), "training_eligible": False, "warning": WARNING,
                "source_sha256": {"queue": fingerprint(queue_path),
                                  **{Path(path).name: fingerprint(path) for path in captures}},
                "output_sha256": fingerprint(output_path)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--capture", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(write_packet(args.queue, args.capture, args.output), indent=2))


if __name__ == "__main__":
    main()
