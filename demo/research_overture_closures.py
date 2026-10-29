"""Download complete NYC-area Overture evidence and conservatively match review cases.

Operating status and provider update times are evidence leads, not verified
restaurant closure dates. This tool never changes outcome labels or the master.
"""

import argparse
import csv
import json
import re
import shutil
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

from evaluation import fingerprint
from match_sla_lifespan_leads import candidate_address, normalized_address, normalized_name


BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com/"
BBOX = (-74.27, 40.47, -73.68, 40.93)
GUIDE = "https://docs.overturemaps.org/guides/places/"
STATUS_DOC = "https://docs.overturemaps.org/schema/reference/places/types/operating_status/"


def listing(prefix, delimiter=None):
    args = {"list-type": "2", "prefix": prefix}
    if delimiter:
        args["delimiter"] = delimiter
    objects, prefixes = [], []
    while True:
        with urlopen(BUCKET + "?" + urlencode(args), timeout=60) as response:
            root = ElementTree.fromstring(response.read())
        prefixes.extend(n.text for n in root.findall(".//{*}CommonPrefixes/{*}Prefix"))
        objects.extend({"key": n.find("{*}Key").text, "etag": n.find("{*}ETag").text,
                        "bytes": int(n.find("{*}Size").text)} for n in root.findall("{*}Contents"))
        token = root.find("{*}NextContinuationToken")
        if token is None:
            return objects, prefixes
        args["continuation-token"] = token.text


def extract(data, release=None):
    if release is None:
        _, prefixes = listing("release/", "/")
        releases = [p.split("/")[1] for p in prefixes if re.fullmatch(r"release/\d{4}-\d{2}-\d{2}\.\d+/", p)]
        if not releases:
            raise ValueError("No official public Overture releases found")
        release = max(releases)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise ValueError("Invalid dated Overture release")
    home = data / "raw_sources/overture_places" / release
    output = home / "nyc_area_places.csv"
    manifest_path = home / "manifest.json"
    if output.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["output_sha256"] != fingerprint(output):
            raise ValueError("Existing Overture evidence checksum changed")
        return output, manifest
    if home.exists():
        raise FileExistsError("Incomplete release directory exists; inspect it before retrying")
    objects, _ = listing(f"release/{release}/theme=places/type=place/")
    objects = sorted((obj for obj in objects if obj["key"].endswith(".parquet")), key=lambda obj: obj["key"])
    if not objects:
        raise ValueError("Release has no public place partitions")
    import duckdb
    connection = duckdb.connect()
    stage = home.parent / (".staging-" + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    try:
        urls = [BUCKET + obj["key"] for obj in objects]
        connection.execute("SET threads=4")
        connection.execute("SET memory_limit='1GB'")
        connection.execute("SET enable_progress_bar=false")
        columns = {row[0] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [urls[0]]).fetchall()}
        required = {"id", "names", "bbox", "operating_status", "sources", "addresses", "confidence", "websites", "phones"}
        if not required <= columns:
            raise ValueError("Unsupported Overture source schema; no statuses will be guessed")
        category = "to_json(taxonomy)" if "taxonomy" in columns else "to_json(categories)" if "categories" in columns else "NULL"
        target = str(stage / output.name).replace("'", "''")
        print(f"Querying all {len(urls)} official place partitions for the entire NYC-area bbox; no status/confidence filter", flush=True)
        connection.execute(f"""COPY (
            SELECT id AS overture_id, names.primary AS name, bbox.ymin AS latitude, bbox.xmin AS longitude,
                   operating_status, confidence, version, to_json(addresses) AS addresses_json,
                   to_json(sources) AS sources_json, to_json(websites) AS websites_json,
                   to_json(phones) AS phones_json, {category} AS category_json
            FROM read_parquet(?)
            WHERE bbox.xmin BETWEEN ? AND ? AND bbox.ymin BETWEEN ? AND ?
            ORDER BY id
        ) TO '{target}' (HEADER, DELIMITER ',')""", [urls, BBOX[0], BBOX[2], BBOX[1], BBOX[3]])
        seen, counts = set(), Counter()
        with (stage / output.name).open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                if not row["overture_id"] or row["overture_id"] in seen:
                    raise ValueError("Missing or duplicate GERS ID in extracted release")
                seen.add(row["overture_id"])
                counts[row["operating_status"] or "unspecified"] += 1
        if len(seen) < 10000:
            raise ValueError("Unexpectedly low NYC-area place coverage")
        after, _ = listing(f"release/{release}/theme=places/type=place/")
        after = sorted((obj for obj in after if obj["key"].endswith(".parquet")), key=lambda obj: obj["key"])
        if after != objects:
            raise ValueError("Overture source objects changed during extraction")
        manifest = {"downloaded_at": datetime.now(timezone.utc).isoformat(), "release": release,
                    "bbox": BBOX, "geography": "NYC-area bounding box, not exact NYC administrative boundary",
                    "rows": len(seen), "operating_status_counts": dict(counts), "official_source_objects": objects,
                    "source_docs": [GUIDE, STATUS_DOC], "source_object_verification": "S3 object size/ETag stable; not a claim that all global source bytes were downloaded",
                    "filter": "All place categories and operating statuses; no confidence threshold; no LIMIT or sampling",
                    "license": "Provider-specific CDLA-Permissive-2.0 or Apache-2.0; preserve per-record provenance",
                    "output_sha256": fingerprint(stage / output.name), "training_eligible": False,
                    "warning": "Source status and source update_time are not actual closure event dates. Overture and Foursquare may share provider lineage."}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        stage.rename(home)
        return output, manifest
    finally:
        connection.close()
        if stage.exists():
            shutil.rmtree(stage)


def read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def index_places(places):
    index = defaultdict(list)
    for place in places:
        for address in json.loads(place["addresses_json"] or "[]"):
            for mode in ("exact", "queens"):
                street, zipcode = normalized_address(address.get("freeform"), address.get("postcode"),
                                                      "queens" if mode == "queens" else "")
                if street and zipcode:
                    index[(mode, street, zipcode)].append(place)
    return index


def match_cases(cases, places, release, fsq=None):
    index = index_places(places)
    seen, rows = set(), []
    for case in cases:
        key = case["business_id"]
        if not key or key in seen:
            raise ValueError("Missing or duplicate business ID in review frame")
        seen.add(key)
        address = candidate_address(case["candidate_address"], case["borough"])
        mode = "queens" if case["borough"].lower() == "queens" else "exact"
        matches = {}
        for place in index.get((mode, *address), []):
            name = normalized_name(place["name"])
            reference = normalized_name(case["candidate_name"])
            similarity = SequenceMatcher(None, reference, name).ratio()
            if reference and name and (reference == name or similarity >= .92):
                matches[place["overture_id"]] = (place, similarity)
        status = "no_conservative_match" if not matches else "ambiguous_multiple_places" if len(matches) > 1 else "matched_" + (next(iter(matches.values()))[0]["operating_status"] or "status_unspecified")
        sources = [s for place, _ in matches.values() for s in json.loads(place["sources_json"] or "[]")]
        datasets = sorted({s.get("dataset", "") for s in sources if s.get("dataset")})
        shared = any("foursquare" in d.lower() or "fsq" in d.lower() for d in datasets)
        rows.append({"business_id": key, "candidate_name": case["candidate_name"],
                     "candidate_address": case["candidate_address"], "borough": case["borough"],
                     "dohmh_identity_review": case.get("identity_review", ""),
                     "candidate_cycle_baseline": case.get("first_cycle_inspection_lead", ""),
                     "overture_match_status": status, "overture_release": release,
                     "overture_ids": ";".join(sorted(matches)), "provider_datasets": ";".join(datasets),
                     "foursquare_lineage_present": shared, "independent_confirmation": False,
                     "match_evidence_json": json.dumps([{**p, "name_similarity": similarity} for p, similarity in matches.values()]),
                     "prior_fsq_match_status": (fsq or {}).get(key, {}).get("fsq_match_status", ""),
                     "outcome_status": "unresolved", "training_eligible": False,
                     "actual_closure_date": "", "review_requirement": "Confirm site identity, date bounds, provider independence, and reopening/relocation; no automatic outcome labels"})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    data_default = Path(__file__).resolve().parents[1] / "data"
    parser.add_argument("--data-dir", type=Path, default=data_default)
    parser.add_argument("--release")
    parser.add_argument("--queue", type=Path, default=data_default / "evaluation/lifespans/adjudication_packet_20261020_v5.csv")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    places, manifest = extract(data, args.release)
    fsq_path = data / "evaluation/lifespans/foursquare_review_leads_20261020_v2.csv"
    fsq = {r["business_id"]: r for r in read(fsq_path)}
    rows = match_cases(read(args.queue), read(places), manifest["release"], fsq)
    out = data / "evaluation/closure_research" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True, exist_ok=False)
    with (out / "overture_review.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "rows": len(rows), "source_release": manifest["release"],
              "source_counts": manifest["operating_status_counts"], "match_counts": dict(Counter(r["overture_match_status"] for r in rows)),
              "closed_matches_with_foursquare_lineage": sum(r["overture_match_status"] == "matched_permanently_closed" and r["foursquare_lineage_present"] for r in rows),
              "verified_outcomes_created": 0, "training_eligible": False,
              "matching_version": "exact-postal-address-queens-only-number-collapse-1",
              "source_sha256": {"queue": fingerprint(args.queue), "overture_extract": fingerprint(places), "foursquare_leads": fingerprint(fsq_path)},
              "output_sha256": fingerprint(out / "overture_review.csv"), "output": str(out),
              "warning": "Status evidence only. Do not equate release date or provider update_time with actual closure date. Provider agreement may not be independent."}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
