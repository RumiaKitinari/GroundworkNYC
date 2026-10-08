"""Check publisher cadences, publish validated releases, and audit training inputs."""

import argparse
import csv
import fcntl
import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from download_sources import DESTINATION, SOURCES, download_source, load_manifest, resolve
from refresh_integrated import BASELINE, CURRENT, INTEGRATED_ROOT, ROOT, SUPPORTED, run, sha256


DATA = ROOT / "data"
STATE = DATA / "update_state.json"
INVENTORY = DATA / "training_inventory.json"
RUNS = DATA / "update_runs"

# Every publisher is checked at least monthly. Fixed 2020 geography is checked
# for file integrity but never treated as a newly observed tract definition.
FREQUENCY = {name: "monthly" for name in SOURCES}
FREQUENCY.update({"restaurants": "daily", "events": "daily", "weather": "daily",
                  "osm": "weekly", "mta_subway": "weekly"})

SOURCE_ROLE = {
    "acs_demographics": ("tract", "baseline transform pending"),
    "acs_income": ("tract", "baseline transform pending"),
    "lodes": ("census block to tract", "baseline transform pending"),
    "osm": ("OSM object and tract", "integrated"),
    "restaurants": ("establishment and tract", "integrated"),
    "mta_subway": ("station and tract", "integrated"),
    "citibike": ("trip, station, and tract", "integrated"),
    "pedestrians": ("monitor and nearest tract", "baseline transform pending"),
    "tlc_hvfhv": ("taxi zone inherited by tract", "integrated"),
    "pluto": ("tax lot and tract", "integrated"),
    "storefronts": ("property and tract", "integrated"),
    "storefront_rent_stats": ("published tract median", "integrated"),
    "epa_walkability": ("block-group polygon to 2020 tract", "integrated with area-weighted crosswalk"),
    "events": ("community district inherited by tract", "integrated"),
    "weather": ("citywide day; never copied to every tract", "integrated separately"),
    "business_patterns": ("ZIP; not a tract feature", "baseline transform pending"),
    "tract_geography_2020": ("fixed 2020 tract boundaries", "fixed geography"),
    "mobile_food_vending": ("violation record; not current vendor inventory", "reference only"),
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_json(path, default):
    return json.loads(path.read_text()) if path.is_file() else default


def period(today, frequency):
    if frequency == "daily":
        return today.isoformat()
    if frequency == "weekly":
        iso = today.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return today.strftime("%Y-%m")


def due_sources(today, state, selected=None, force=False):
    selected = selected or tuple(SOURCES)
    return [name for name in selected if force or state.get("sources", {}).get(name, {}).get("period") !=
            period(today, FREQUENCY[name])]


def release_lineage(current=CURRENT, integrated_root=INTEGRATED_ROOT):
    release = current.resolve() if current.is_dir() else BASELINE
    versions = {}
    visited = set()
    while release.is_dir() and release not in visited:
        visited.add(release)
        manifest = release / "refresh_manifest.json"
        if not manifest.is_file():
            break
        details = json.loads(manifest.read_text())
        for name, revision in details.get("raw_revisions", {}).items():
            versions.setdefault(name, {"revision": revision, "as_of": details.get("as_of"),
                                       "release": release.name})
        parent = details.get("base_release", "")
        if parent == BASELINE.name:
            break
        release = integrated_root / "releases" / parent
    return versions


def raw_latest(name):
    manifest = load_manifest(SOURCES[name])
    return manifest["revisions"][-1] if manifest["revisions"] else None


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def training_inventory(now=None):
    now = now or datetime.now(timezone.utc)
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    master_path = release / "master_tract_features.csv"
    dictionary_path = release / "data_dictionary.csv"
    geography_path = release / "geography" / "nyc_2020_census_tracts.geojson"
    master = read_csv(master_path)
    dictionary = read_csv(dictionary_path)
    geometry = json.loads(geography_path.read_text())
    ids = [row["geoid"] for row in master]
    polygons = [feature["properties"]["geoid"] for feature in geometry["features"]]
    fields = set(master[0])
    documented = {row["column"] for row in dictionary if row["file"] == "master_tract_features.csv"}
    issues = []
    if len(ids) != len(set(ids)) or len(polygons) != len(set(polygons)) or set(ids) != set(polygons):
        issues.append("Master GEOIDs do not exactly match unique 2020 tract polygons.")
    if fields != documented:
        issues.append("Master columns and data dictionary differ: " + ", ".join(sorted(fields ^ documented)))
    for path in sorted((release / "features").glob("tract_*.csv")):
        rows = read_csv(path)
        if not rows:
            issues.append(f"Empty tract feature table: {path.name}")
            continue
        feature_ids = [row["geoid"] for row in rows]
        if len(feature_ids) != len(set(feature_ids)) or not set(feature_ids) <= set(ids):
            issues.append(f"Invalid or duplicate tract GEOIDs in {path.name}")
        missing_fields = set(rows[0]) - fields - {"location_id"}
        if missing_fields:
            issues.append(f"Feature columns absent from master in {path.name}: {sorted(missing_fields)}")
    lineage = release_lineage()
    sources = {}
    for name, source in SOURCES.items():
        revision = raw_latest(name)
        file_records = revision.get("files", []) if revision else []
        paths = [DESTINATION / name / revision["directory"] / item["file"] for item in file_records] if revision else []
        if any("sample" in path.name.lower() for path in paths):
            issues.append(f"Sample file entered raw source manifest: {name}")
        for path, item in zip(paths, file_records):
            if not path.is_file() or path.stat().st_size != item["bytes"]:
                issues.append(f"Raw source file missing or wrong size: {name} / {path.name}")
        integrated = lineage.get(name, {})
        if name in SUPPORTED:
            status = "integrated_current" if revision and integrated.get("revision") == revision["directory"] else "integration_pending"
        elif revision:
            status = SOURCE_ROLE[name][1].replace(" ", "_")
        else:
            status = "raw_missing"
        sources[name] = {
            "label": source.label, "check_frequency": FREQUENCY[name], "grain": SOURCE_ROLE[name][0],
            "role": SOURCE_ROLE[name][1], "status": status,
            "raw_version": revision.get("publisher_version") if revision else None,
            "raw_revision": revision.get("directory") if revision else None,
            "raw_rows": sum(item.get("rows", 0) for item in file_records) or None,
            "raw_bytes": sum(item.get("bytes", 0) for item in file_records) or None,
            "raw_files": [str(path) for path in paths],
            "integrated_revision": integrated.get("revision"),
        }
    samples = sorted(str(path) for path in (DATA / "cleaned_sources").rglob("*SAMPLE*") if path.is_file())
    if any("sample" in part.lower() for part in release.parts):
        issues.append("Active integrated release path contains SAMPLE.")
    return {
        "generated_at": now.isoformat(), "active_release": str(release),
        "feature_matrix": str(master_path), "feature_matrix_sha256": sha256(master_path),
        "tract_rows": len(master), "master_columns": len(fields), "documented_columns": len(documented),
        "geography_rows": len(polygons), "sample_files_reference_only": samples,
        "sources": sources, "structural_issues": issues,
        "feature_matrix_structurally_valid": not issues,
        "success_model_training_ready": False,
        "success_model_limitation": "Verified longitudinal business outcomes and leakage-safe historical feature snapshots are not yet available.",
    }


def pending_integrations(today, lineage=None):
    lineage = lineage or release_lineage()
    pending = []
    for name in SUPPORTED:
        revision = raw_latest(name)
        if not revision:
            continue
        if lineage.get(name, {}).get("revision") != revision["directory"]:
            pending.append(name)
        elif name == "events" and lineage[name].get("as_of") != today.isoformat():
            pending.append(name)
    return pending


def check_and_refresh(today, selected=None, force=False, publish=True):
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / ".maintenance.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_json(STATE, {"sources": {}})
        checked, downloaded, blocked, failed = [], [], {}, {}
        for name in due_sources(today, state, selected, force):
            source = SOURCES[name]
            try:
                info = resolve(source, today)
                checked.append(name)
                record = {"period": period(today, FREQUENCY[name]), "publisher_version": info["version"],
                          "checked_at": datetime.now(timezone.utc).isoformat()}
                if info.get("credentials_required"):
                    record["status"] = "credentials_required"
                    blocked[name] = "Set CENSUS_API_KEY to download the full ACS tract source."
                else:
                    result = download_source(source, info)
                    record["status"] = result
                    if result == "downloaded":
                        downloaded.append(name)
                state["sources"][name] = record
            except Exception as error:
                secret = os.environ.get("CENSUS_API_KEY", "")
                message = f"{type(error).__name__}: {error}"
                failed[name] = message.replace(secret, "[REDACTED]") if secret else message
        write_json(STATE, state)

        refresh = None
        pending = pending_integrations(today)
        if pending and publish:
            tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "demo",
                                    "-p", "test_*.py", "-q"], cwd=ROOT, capture_output=True, text=True,
                                   timeout=300, check=False)
            if tests.returncode:
                failed["tests"] = tests.stderr[-2000:]
            else:
                try:
                    preview = run(tuple(pending), today, publish=False)
                    flags = (preview.get("score_audit") or {}).get("review_flags", [])
                    if flags:
                        blocked["score_audit"] = flags
                    else:
                        refresh = run(tuple(pending), today, publish=True)
                except Exception as error:
                    failed["integrated_refresh"] = f"{type(error).__name__}: {error}"
        inventory = training_inventory()
        write_json(INVENTORY, inventory)
        raw_only_changes = [name for name in downloaded if name not in SUPPORTED]
        status = "failed" if failed or inventory["structural_issues"] else "attention" if blocked or raw_only_changes else "ok"
        report = {"run_at": datetime.now(timezone.utc).isoformat(), "status": status,
                  "checked": checked, "downloaded": downloaded, "blocked": blocked, "failed": failed,
                  "pending_integrations": pending_integrations(today),
                  "published_release": refresh.get("published_release") if refresh else None,
                  "raw_only_changes": raw_only_changes,
                  "inventory": str(INVENTORY)}
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8] + ".json"
        write_json(RUNS / name, report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true", help="Audit active data without contacting publishers")
    parser.add_argument("--check-only", action="store_true", help="Check/download due sources without publishing")
    parser.add_argument("--force", action="store_true", help="Check selected publishers regardless of cadence")
    parser.add_argument("--source", action="append", choices=tuple(SOURCES), help="Limit to named sources")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    try:
        if args.audit:
            result = training_inventory()
            write_json(INVENTORY, result)
        else:
            result = check_and_refresh(date.fromisoformat(args.as_of), args.source, args.force,
                                       not args.check_only)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        parser.exit(2, f"Data maintenance failed: {error}\n")
    print(json.dumps(result, indent=2))
    if args.audit and result["structural_issues"]:
        return 1
    return 1 if not args.audit and result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
