"""Archive complete scoped official references and attach lifecycle review leads."""

import argparse
import csv
import json
import shutil
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from download_sources import request
from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address, normalized_name


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "sbs_openings": {"id": "9b9u-8989", "where": "", "minimum_rows": 1000},
    "outdoor_applications": {"id": "pitm-atqc", "where": "", "minimum_rows": 10000},
    "commercial_evictions": {"id": "6z8x-wfk4", "where": "residential_commercial_ind='Commercial'", "minimum_rows": 1000},
}
REQUIRED_FIELDS = {
    "sbs_openings": {"establishment_record_dba", "establishment_record_establishment_street",
                     "establishment_record_establishment_zip", "establishment_record_establishment_borough",
                     "establishment_record_actual_opening_date"},
    "outdoor_applications": {"food_service_establishment", "bulding_number", "street", "zip", "borough", "legal_business_name"},
    "commercial_evictions": {"eviction_address", "eviction_zip", "borough", "residential_commercial_ind", "executed_date"},
}


def json_get(url):
    with request(url, attempts=2) as response:
        return json.load(response)


def fetch_source(spec, stage, name):
    identifier = spec["id"]
    base = f"https://data.cityofnewyork.us/resource/{identifier}"
    metadata_url = f"https://data.cityofnewyork.us/api/views/{identifier}.json"
    before = json_get(metadata_url)
    revision = before.get("rowsUpdatedAt")
    if not revision:
        raise ValueError("Publisher revision is missing")
    count_query = {"$select": "count(*) as n"}
    if spec["where"]:
        count_query["$where"] = spec["where"]
    count_url = base + ".json?" + urlencode(count_query)
    expected = int(json_get(count_url)[0]["n"])
    if not spec["minimum_rows"] <= expected < 100000:
        raise ValueError(f"Unexpected scoped size for {name}: {expected}; no truncated export will be accepted")
    query = {"$order": ":id", "$limit": 100000}
    if spec["where"]:
        query["$where"] = spec["where"]
    url = base + ".csv?" + urlencode(query)
    target = stage / (name + ".csv")
    with request(url, attempts=2) as response, target.open("xb") as stream:
        shutil.copyfileobj(response, stream)
    with target.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        count = sum(1 for _ in reader)
    if not fields or count != expected:
        raise ValueError(f"Incomplete {name}: {count} downloaded versus {expected} publisher rows")
    if not REQUIRED_FIELDS[name] <= set(fields):
        raise ValueError(f"Unsupported publisher schema for {name}")
    after = json_get(metadata_url)
    after_count = int(json_get(count_url)[0]["n"])
    if after.get("rowsUpdatedAt") != revision or after_count != expected:
        raise ValueError(f"Publisher changed during {name} extraction")
    (stage / (name + ".metadata.json")).write_text(json.dumps(before, indent=2) + "\n")
    return {"dataset_id": identifier, "dataset_title": before.get("name"), "dataset_url": f"https://data.cityofnewyork.us/d/{identifier}",
            "download_url": url, "rows": count, "publisher_revision": revision, "where": spec["where"],
            "scope": "Full publisher table" if not spec["where"] else "All NYC commercial execution rows; residential rows intentionally excluded",
            "sha256": fingerprint(target), "sampling": False}


def download(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stage = directory / (".staging-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        files = {name: fetch_source(spec, stage, name) for name, spec in SOURCES.items()}
        manifest = {"downloaded_at": datetime.now(timezone.utc).isoformat(), "files": files,
                    "status": "private_lifecycle_reference_not_training_labels", "training_eligible": False,
                    "warning": "Agency-reported opening dates require operator checks; outdoor application is not operation; address-only eviction is not proof of restaurant exit or last trading day."}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        output = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8])
        stage.rename(output)
        return output, manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def borough(value):
    return {"new york": "manhattan"}.get((value or "").strip().lower(), (value or "").strip().lower())


def address(street, zipcode, boro):
    return borough(boro), *normalized_address(street, zipcode, borough(boro))


def attach_references(candidates, openings, outdoor, evictions):
    sbs, dot, executions = defaultdict(list), defaultdict(list), defaultdict(list)
    candidate_identities = defaultdict(set)
    for candidate in candidates:
        key = ((borough(candidate["borough"]), *candidate_address(candidate["candidate_address"], candidate["borough"])),
               normalized_name(candidate["candidate_name"]))
        candidate_identities[key].add(candidate["business_id"])
    for source in openings:
        boro = source.get("establishment_record_establishment_borough", "")
        key = address(source.get("establishment_record_establishment_street"), source.get("establishment_record_establishment_zip"), boro)
        sbs[(key, normalized_name(source.get("establishment_record_dba")))].append(source)
    for source in outdoor:
        dot[source.get("food_service_establishment", "").strip()].append(source)
    for source in evictions:
        if source.get("residential_commercial_ind") != "Commercial":
            raise ValueError("Only scoped commercial execution rows may be matched")
        key = address(source.get("eviction_address"), source.get("eviction_zip"), source.get("borough"))
        executions[key].append(source)
    seen, rows = set(), []
    for candidate in candidates:
        identifier = candidate["business_id"]
        if not identifier or identifier in seen:
            raise ValueError("Missing or duplicate candidate ID")
        seen.add(identifier)
        key = (borough(candidate["borough"]), *candidate_address(candidate["candidate_address"], candidate["borough"]))
        opening_hits = sbs.get((key, normalized_name(candidate["candidate_name"])), []) if all(key) else []
        opening_dates = sorted({r.get("establishment_record_actual_opening_date", "")[:10] for r in opening_hits} - {""})
        dot_hits = dot.get(identifier, [])
        dot_exact = [r for r in dot_hits if address(" ".join((r.get("bulding_number", ""), r.get("street", ""))), r.get("zip"), r.get("borough")) == key]
        eviction_hits = executions.get(key, []) if all(key) else []
        rows.append({"business_id": identifier, "candidate_name": candidate["candidate_name"],
                     "candidate_address": candidate["candidate_address"], "borough": candidate["borough"],
                     "candidate_camis_ids_same_identity": ";".join(sorted(candidate_identities[(key, normalized_name(candidate["candidate_name"]))])),
                     "sbs_exact_identity_rows": len(opening_hits), "sbs_reported_opening_dates": ";".join(opening_dates),
                     "sbs_conflicting_opening_dates": len(opening_dates) > 1,
                     "sbs_business_categories": ";".join(sorted({r.get("establishment_record_establishment_category", "") for r in opening_hits} - {""})),
                     "sbs_evidence_json": json.dumps(opening_hits),
                     "outdoor_same_camis_rows": len(dot_hits), "outdoor_same_camis_address_rows": len(dot_exact),
                     "outdoor_reported_legal_names": ";".join(sorted({r.get("legal_business_name", "") for r in dot_exact} - {""})),
                     "outdoor_evidence_json": json.dumps(dot_hits),
                     "commercial_executions_at_address": len(eviction_hits), "commercial_execution_evidence_json": json.dumps(eviction_hits),
                     "training_eligible": False, "verification_status": "official_reference_leads_not_outcome_adjudication",
                     "warning": "SBS does not identify CAMIS/operator episode; DOT is an application; executions have no tenant identity. No event date is promoted to an outcome."})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Reuse a complete checksum-valid reference snapshot")
    parser.add_argument("--queue", type=Path, default=ROOT / "data/evaluation/lifespans/adjudication_packet_20261020_v5.csv")
    args = parser.parse_args()
    if args.source_dir:
        source_dir = args.source_dir
        manifest = json.loads((source_dir / "manifest.json").read_text())
        for name in SOURCES:
            if fingerprint(source_dir / (name + ".csv")) != manifest["files"][name]["sha256"]:
                raise ValueError("Cached source checksum mismatch")
    else:
        source_dir, manifest = download(ROOT / "data/raw_sources/closure_lifecycle_references")
    rows = attach_references(read(args.queue), *(read(source_dir / (name + ".csv")) for name in SOURCES))
    if not rows:
        raise ValueError("Empty candidate queue")
    output = ROOT / "data/evaluation/closure_research" / ("official_references_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True, exist_ok=False)
    with (output / "review.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "candidate_rows": len(rows),
              "sources": manifest["files"], "source_directory": str(source_dir),
              "candidates_with_sbs_opening_date": sum(bool(r["sbs_reported_opening_dates"]) for r in rows),
              "candidates_with_conflicting_sbs_dates": sum(r["sbs_conflicting_opening_dates"] for r in rows),
              "candidates_with_outdoor_camis_crosswalk": sum(r["outdoor_same_camis_rows"] > 0 for r in rows),
              "candidates_with_outdoor_camis_and_address_crosswalk": sum(r["outdoor_same_camis_address_rows"] > 0 for r in rows),
              "candidates_with_commercial_execution_at_address": sum(r["commercial_executions_at_address"] > 0 for r in rows),
              "verified_outcomes_created": 0, "training_eligible": False,
              "queue_sha256": fingerprint(args.queue), "review_sha256": fingerprint(output / "review.csv"), "output": str(output)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
