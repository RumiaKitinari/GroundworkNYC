"""Download full official 2023 ACS and 2022 LODES data for historical tract features."""

import csv
import gzip
import hashlib
import json
import os
import shutil
import uuid
from collections import defaultdict
from pathlib import Path

from download_sources import request
from evaluation import fingerprint
from refresh_integrated import BASELINE, CURRENT, ROOT


COUNTIES = {"005", "047", "061", "081", "085"}
ACS_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/"
LODES_URL = "https://lehd.ces.census.gov/data/lodes/LODES8/ny/wac/ny_wac_S000_JT00_2022.csv.gz"
SOURCES = {
    "acs_population": (ACS_BASE + "acsdt5y2023-b01003.dat", 10_000_000),
    "acs_income": (ACS_BASE + "acsdt5y2023-b19013.dat", 10_000_000),
    "lodes_jobs": (LODES_URL, 1_000_000),
}
SNAPSHOT_DIR = ROOT / "data" / "evaluation" / "snapshots" / "2024-12-v2"
ARCHIVE_DIR = ROOT / "data" / "evaluation" / "source_archives"
ACS_RELEASE = "2024-12-12"
LODES_RELEASE = "2024-11-19"
EPA_RELEASE = "2021-06-08"
EPA_URL = "https://edg.epa.gov/data/public/OLEM/SLD/SmartLocationDatabaseV3.zip"
EPA_SHA256 = "81cdb3f692e4c282273b0791e1d2d9c0082c6e3f722a714932a985a24eba4fa0"


def download_archive(path, url, minimum_bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.stat().st_size < minimum_bytes:
            raise ValueError(f"Existing archive is incomplete: {path}")
        return fingerprint(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with request(url) as response, temporary.open("xb") as output:
            length = response.headers.get("Content-Length")
            shutil.copyfileobj(response, output, 1024 * 1024)
        if temporary.stat().st_size < minimum_bytes or (length and temporary.stat().st_size != int(length)):
            raise ValueError(f"Incomplete publisher download: {url}")
        if path.exists():
            raise FileExistsError(f"Archive appeared during download: {path}")
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return fingerprint(path)


def load_master(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    areas = {}
    for row in rows:
        geoid = row["geoid"]
        if len(geoid) != 11 or geoid in areas:
            raise ValueError("Master geography has invalid or duplicate tract IDs.")
        areas[geoid] = float(row["land_area_sq_miles"] or 0)
    if len(areas) < 2200:
        raise ValueError("Master geography is incomplete.")
    return areas


def read_acs_table(path, field, minimum_tracts=2200):
    values = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream, delimiter="|")
        if not {"GEO_ID", field} <= set(reader.fieldnames or []):
            raise ValueError(f"Unexpected ACS table schema: {path}")
        for row in reader:
            geo_id = row["GEO_ID"]
            if not geo_id.startswith("1400000US36"):
                continue
            geoid = geo_id[9:]
            if len(geoid) != 11 or geoid[2:5] not in COUNTIES:
                continue
            if geoid in values:
                raise ValueError(f"Duplicate ACS tract: {geoid}")
            raw = row[field]
            number = int(raw) if raw else -1
            values[geoid] = number if number >= 0 else None
    if len(values) < minimum_tracts:
        raise ValueError(f"Incomplete NYC ACS tract coverage: {len(values)}")
    return values


def read_lodes_jobs(path, known_tracts):
    totals = defaultdict(int)
    blocks = 0
    with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"w_geocode", "C000"} <= set(reader.fieldnames or []):
            raise ValueError("Unexpected LODES workplace schema.")
        for row in reader:
            block = row["w_geocode"]
            geoid = block[:11]
            if len(block) != 15 or geoid not in known_tracts:
                continue
            jobs = int(row["C000"])
            if jobs < 0:
                raise ValueError("Negative LODES job count.")
            totals[geoid] += jobs
            blocks += 1
    if blocks < 10000:
        raise ValueError(f"Incomplete NYC LODES block coverage: {blocks}")
    return totals, blocks


def write_immutable_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open(newline="", encoding="utf-8") as stream:
            old = list(csv.DictReader(stream))
        expected = [{field: str(row[field]) if row[field] is not None else "" for field in fields} for row in rows]
        if old != expected:
            raise ValueError(f"Existing snapshot differs; use a new release directory: {path}")
        return fingerprint(path)
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return fingerprint(path)


def build_snapshots(areas, population, income, jobs):
    acs = []
    workers = []
    for geoid, area in sorted(areas.items()):
        people = population.get(geoid)
        household_income = income.get(geoid)
        acs.append({"geoid": geoid,
                    "population_density_per_sq_mile": round(people / area, 6) if people is not None and area > 0 else "",
                    "median_household_income": household_income if household_income is not None else ""})
        count = jobs.get(geoid, 0)
        workers.append({"geoid": geoid, "job_density_per_sq_mile": round(count / area, 6) if area > 0 else "",
                        "total_jobs": count})
    return acs, workers


def load_epa_snapshot(path, known_tracts):
    values = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"geoid", "national_walkability_index"} <= set(reader.fieldnames or []):
            raise ValueError("Unexpected EPA tract crosswalk schema.")
        for row in reader:
            geoid = row["geoid"]
            if geoid not in known_tracts or geoid in values:
                raise ValueError(f"Unknown or duplicate EPA tract: {geoid}")
            value = row["national_walkability_index"]
            if value and not 1 <= float(value) <= 20:
                raise ValueError(f"Invalid EPA walkability value: {geoid}")
            values[geoid] = value
    if len(values) != len(known_tracts):
        raise ValueError("EPA tract crosswalk coverage does not match the master geography.")
    return [{"geoid": geoid, "national_walkability_index": values[geoid]} for geoid in sorted(known_tracts)]


def pinned_epa_archive():
    directory = ROOT / "data" / "raw_sources" / "epa_walkability"
    manifest = json.loads((directory / "manifest.json").read_text())
    for revision in manifest["revisions"]:
        if revision.get("source_url") != EPA_URL:
            continue
        for item in revision.get("files", []):
            if item.get("sha256") == EPA_SHA256:
                path = directory / revision["directory"] / item["file"]
                if path.is_file() and fingerprint(path) == EPA_SHA256:
                    return path
    raise ValueError("Pinned EPA v3 raw source is unavailable or has changed.")


def main():
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    areas = load_master(release / "master_tract_features.csv")
    raw = {}
    for name, (url, minimum_bytes) in SOURCES.items():
        suffix = ".csv.gz" if name == "lodes_jobs" else ".dat"
        path = ARCHIVE_DIR / f"{name}_2022" / f"source{suffix}" if name == "lodes_jobs" else ARCHIVE_DIR / f"{name}_2023" / f"source{suffix}"
        print(f"Checking {name}...", flush=True)
        raw[name] = {"path": path, "url": url, "sha256": download_archive(path, url, minimum_bytes)}
    population = read_acs_table(raw["acs_population"]["path"], "B01003_E001")
    income = read_acs_table(raw["acs_income"]["path"], "B19013_E001")
    jobs, blocks = read_lodes_jobs(raw["lodes_jobs"]["path"], areas)
    acs, workers = build_snapshots(areas, population, income, jobs)
    epa_source = release / "features" / "tract_walkability.csv"
    epa_raw = pinned_epa_archive()
    epa = load_epa_snapshot(epa_source, areas)
    acs_path = SNAPSHOT_DIR / "tract_acs_2023.csv"
    workers_path = SNAPSHOT_DIR / "tract_lodes_2022.csv"
    epa_path = SNAPSHOT_DIR / "tract_walkability_2021.csv"
    acs_hash = write_immutable_csv(acs_path, acs, ["geoid", "population_density_per_sq_mile", "median_household_income"])
    workers_hash = write_immutable_csv(workers_path, workers, ["geoid", "job_density_per_sq_mile", "total_jobs"])
    epa_hash = write_immutable_csv(epa_path, epa, ["geoid", "national_walkability_index"])
    entries = []
    for feature, path, observed, available, digest, source_url in (
        ("population_density_per_sq_mile", acs_path, "2023-12-31", ACS_RELEASE, acs_hash, raw["acs_population"]["url"]),
        ("median_household_income", acs_path, "2023-12-31", ACS_RELEASE, acs_hash, raw["acs_income"]["url"]),
        ("job_density_per_sq_mile", workers_path, "2022-06-30", LODES_RELEASE, workers_hash, LODES_URL),
        ("national_walkability_index", epa_path, "2020-12-31", EPA_RELEASE, epa_hash, EPA_URL),
    ):
        entries.append({"feature": feature, "path": str(path.relative_to(ROOT / "data")), "column": feature,
                        "observed_through": observed, "available_on": available, "sha256": digest,
                        "source_url": source_url, "historical_reconstruction_verified": True})
    manifest = {"status": "partial_historical_feature_set", "snapshots": entries,
                "release_dates": {
                    "acs_2023": "https://www.census.gov/programs-surveys/acs/news/data-releases/2023/release-schedule.html",
                    "lodes_2022": "https://lehd.ces.census.gov/announcements.html",
                    "epa_v3": "https://edg.epa.gov/data/public/OLEM/SLD/"},
                "source_archives": {name: {"path": str(value["path"].relative_to(ROOT / "data")),
                                           "url": value["url"], "sha256": value["sha256"]} for name, value in raw.items()},
                "coverage": {"tracts": len(areas), "acs_population": sum(row["population_density_per_sq_mile"] != "" for row in acs),
                             "acs_income": sum(row["median_household_income"] != "" for row in acs),
                             "lodes_blocks": blocks, "lodes_tracts_with_jobs": sum(row["total_jobs"] > 0 for row in workers),
                             "epa_walkability": sum(row["national_walkability_index"] != "" for row in epa)},
                "epa_source": {"raw_path": str(epa_raw.relative_to(ROOT / "data")), "raw_sha256": fingerprint(epa_raw),
                               "tract_crosswalk_path": str(epa_source.relative_to(ROOT / "data")),
                               "tract_crosswalk_sha256": fingerprint(epa_source),
                               "observation_note": "2020-12-31 is a conservative upper bound for the source's older built-environment inputs."},
                "caution": "Only four of eight evaluation features are present; no training cohort can be built yet."}
    manifest_path = SNAPSHOT_DIR / "partial_historical_snapshots.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Existing historical manifest differs; do not overwrite it.")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), **manifest["coverage"], "status": manifest["status"]}, indent=2))


if __name__ == "__main__":
    main()
