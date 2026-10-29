"""Create review candidates from inspection history without inventing business outcomes."""

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

from refresh_integrated import CURRENT, BASELINE, ROOT, raw_revision, sha256


FIELDS = ("business_id", "geoid", "name", "address", "first_inspection_on",
          "last_inspection_on", "inspection_records", "latest_action",
          "closure_order_seen", "verification_status", "source_url")
SOURCE_URL = "https://data.cityofnewyork.us/d/43nn-pn8j"


def build_candidates(raw_path, current_path):
    with current_path.open(newline="", encoding="utf-8-sig") as stream:
        current = {row["camis"]: row for row in csv.DictReader(stream) if row.get("camis")}
    history = {}
    with raw_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            camis = row.get("camis", "").strip()
            if not camis:
                continue
            group = history.setdefault(camis, {"dates": [], "count": 0, "latest": "", "action": "", "closure": False})
            group["count"] += 1
            day = row.get("inspection_date", "")[:10]
            try:
                if date(2000, 1, 1) <= date.fromisoformat(day) <= date.today():
                    group["dates"].append(day)
            except ValueError:
                pass
            action = row.get("action", "")
            if action.startswith(("Establishment Closed by DOHMH", "Establishment re-closed by DOHMH")):
                group["closure"] = True
            if day >= group["latest"]:
                group["latest"], group["action"] = day, action
    candidates = []
    for camis, group in sorted(history.items()):
        restaurant = current.get(camis, {})
        candidates.append({"business_id": camis, "geoid": restaurant.get("geoid", ""),
                           "name": restaurant.get("dba", ""), "address": restaurant.get("building", "") + " " + restaurant.get("street", ""),
                           "first_inspection_on": min(group["dates"]) if group["dates"] else "",
                           "last_inspection_on": max(group["dates"]) if group["dates"] else "",
                           "inspection_records": group["count"], "latest_action": group["action"],
                           "closure_order_seen": group["closure"],
                           "verification_status": "independent_verification_required", "source_url": SOURCE_URL})
    return candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Private candidate CSV destination")
    args = parser.parse_args()
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    raw, revision = raw_revision("restaurants")
    output = args.output or ROOT / "data" / "evaluation" / f"outcome_candidates_{revision['directory']}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = build_candidates(raw, release / "entities" / "current_restaurants.csv")
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(candidates)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "rows": len(candidates),
                "source_revision": revision["directory"], "source_sha256": sha256(raw),
                "integrated_release": release.name, "status": "review_candidates_only",
                "warning": "Inspection activity and DOHMH closure orders are not verified permanent closure or survival labels."}
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), **manifest}, indent=2))


if __name__ == "__main__":
    main()
