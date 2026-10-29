"""Build official 2023-available tract features alongside the later 2024 tranche."""

import json
from pathlib import Path

from build_historical_snapshots import (ARCHIVE_DIR, build_snapshots, download_archive,
                                        load_master, read_acs_table, read_lodes_jobs,
                                        write_immutable_csv)
from evaluation import HISTORICAL_CORE_FEATURES, fingerprint
from prepare_historical_cohort import read_snapshots
from refresh_integrated import BASELINE, CURRENT, ROOT


ACS_BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/data/5YRData/"
LODES_URL = "https://lehd.ces.census.gov/data/lodes/LODES8/ny/wac/ny_wac_S000_JT00_2021.csv.gz"
ACS_RELEASE = "2023-12-07"
LODES_RELEASE = "2023-11-15"
SNAPSHOT_DIR = ROOT / "data/evaluation/snapshots/2023-12-v1"
LATER_MANIFEST = ROOT / "data/evaluation/snapshots/2024-12-v2/partial_historical_snapshots.json"


def main():
    release = CURRENT.resolve() if CURRENT.is_dir() else BASELINE
    areas = load_master(release / "master_tract_features.csv")
    sources = {
        "acs_population_2022": (ACS_BASE + "acsdt5y2022-b01003.dat", 10_000_000, ".dat"),
        "acs_income_2022": (ACS_BASE + "acsdt5y2022-b19013.dat", 10_000_000, ".dat"),
        "lodes_jobs_2021": (LODES_URL, 1_000_000, ".csv.gz"),
    }
    archives = {}
    for name, (url, minimum_bytes, extension) in sources.items():
        path = ARCHIVE_DIR / name / f"source{extension}"
        print(f"Checking {name}...", flush=True)
        archives[name] = {"path": path, "url": url, "sha256": download_archive(path, url, minimum_bytes)}
    population = read_acs_table(archives["acs_population_2022"]["path"], "B01003_E001")
    income = read_acs_table(archives["acs_income_2022"]["path"], "B19013_E001")
    jobs, blocks = read_lodes_jobs(archives["lodes_jobs_2021"]["path"], areas)
    acs, workers = build_snapshots(areas, population, income, jobs)
    acs_path = SNAPSHOT_DIR / "tract_acs_2022.csv"
    jobs_path = SNAPSHOT_DIR / "tract_lodes_2021.csv"
    acs_hash = write_immutable_csv(acs_path, acs, ["geoid", "population_density_per_sq_mile",
                                                    "median_household_income"])
    jobs_hash = write_immutable_csv(jobs_path, workers, ["geoid", "job_density_per_sq_mile", "total_jobs"])
    entries = []
    for feature, path, observed, available, digest, url in (
        ("population_density_per_sq_mile", acs_path, "2022-12-31", ACS_RELEASE, acs_hash,
         archives["acs_population_2022"]["url"]),
        ("median_household_income", acs_path, "2022-12-31", ACS_RELEASE, acs_hash,
         archives["acs_income_2022"]["url"]),
        ("job_density_per_sq_mile", jobs_path, "2021-06-30", LODES_RELEASE, jobs_hash, LODES_URL),
    ):
        entries.append({"feature": feature, "path": str(path.relative_to(ROOT / "data")),
                        "column": feature, "observed_through": observed, "available_on": available,
                        "sha256": digest, "source_url": url, "historical_reconstruction_verified": True})
    later = json.loads(LATER_MANIFEST.read_text(encoding="utf-8"))
    entries.extend(later["snapshots"])
    manifest = {"status": "historical_core_two_vintages", "features": list(HISTORICAL_CORE_FEATURES),
                "snapshots": entries,
                "release_dates": {
                    "acs_2022": "https://www.census.gov/programs-surveys/acs/news/data-releases/2022/release.html",
                    "lodes_2021": "https://lehd.ces.census.gov/announcements.html"},
                "publisher_file_last_modified": {
                    "acs_population_2022": "2023-10-30T16:34:11Z",
                    "acs_income_2022": "2023-10-30T16:36:01Z",
                    "lodes_jobs_2021": "2023-11-09T14:20:18Z"},
                "source_archives": {name: {"path": str(value["path"].relative_to(ROOT / "data")),
                                           "url": value["url"], "sha256": value["sha256"]}
                                    for name, value in archives.items()},
                "later_manifest_sha256": fingerprint(LATER_MANIFEST),
                "coverage": {"tracts": len(areas),
                             "acs_population_2022": sum(row["population_density_per_sq_mile"] != "" for row in acs),
                             "acs_income_2022": sum(row["median_household_income"] != "" for row in acs),
                             "lodes_blocks_2021": blocks,
                             "lodes_tracts_with_jobs_2021": sum(row["total_jobs"] > 0 for row in workers)},
                "caution": "Official dated feature vintages; business outcomes still require independent verification."}
    destination = SNAPSHOT_DIR / "historical_core_snapshots.json"
    if destination.exists():
        if json.loads(destination.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Existing historical manifest differs; use a new release directory.")
    else:
        destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    read_snapshots(destination, ROOT / "data", HISTORICAL_CORE_FEATURES)
    print(json.dumps({"manifest": str(destination), "status": manifest["status"],
                      "coverage": manifest["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
