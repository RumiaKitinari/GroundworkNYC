"""Archive official NYC active and inactive State Liquor Authority license rows."""

import argparse
import csv
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from download_sources import request
from evaluation import fingerprint
from refresh_integrated import ROOT


DATASETS = {"inactive": ("6dg3-2z7i", "premises_county"),
            "active": ("9s3h-dpkz", "premisescounty")}
COUNTIES = ("New York", "Kings", "Queens", "Bronx", "Richmond")
FIELDS = {
    "inactive": ("license_permit_id", "premises_county", "description", "legalname", "dba",
                 "actual_address_of_premises", "zip_code", "original_issue_date", "last_issue_date",
                 "effective_date", "expiration_date"),
    "active": ("licensepermitid", "premisescounty", "description", "legalname", "dba",
               "actualaddressofpremises", "zipcode", "originalissuedate", "lastissuedate",
               "effectivedate", "expirationdate"),
}


def publisher_metadata(identifier):
    with request(f"https://data.ny.gov/api/views/{identifier}.json") as response:
        meta = json.load(response)
    if not meta.get("rowsUpdatedAt"):
        raise ValueError(f"SLA dataset {identifier} has no publisher revision timestamp.")
    return meta["rowsUpdatedAt"]


def fetch_dataset(status, target):
    identifier, county_field = DATASETS[status]
    base = f"https://data.ny.gov/resource/{identifier}"
    where = county_field + " in (" + ",".join(f"'{county}'" for county in COUNTIES) + ")"
    with request(base + ".json?" + urlencode({"$select": "count(*) as n", "$where": where})) as response:
        expected = int(json.load(response)[0]["n"])
    if not 1000 < expected < 100000:
        raise ValueError(f"Unexpected NYC SLA {status} count: {expected}")
    query = {"$select": ",".join(FIELDS[status]), "$where": where,
             "$order": ":id", "$limit": 100000}
    url = base + ".csv?" + urlencode(query)
    with request(url) as response, target.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    with target.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELDS[status]:
            raise ValueError(f"SLA {status} schema changed during download.")
        count = sum(1 for _ in reader)
    if count != expected:
        raise ValueError(f"SLA {status} row count changed during download: {count} != {expected}")
    return {"rows": count, "sha256": fingerprint(target), "source_url": url,
            "dataset_url": f"https://data.ny.gov/d/{identifier}"}


def download(directory):
    directory = Path(directory)
    revisions = {status: publisher_metadata(identifier)
                 for status, (identifier, _) in DATASETS.items()}
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("publisher_revisions") == revisions:
            paths = [directory / old["revision"] / f"{status}.csv" for status in DATASETS]
            if all(path.is_file() and fingerprint(path) == old["files"][status]["sha256"]
                   for status, path in zip(DATASETS, paths)):
                return {**old, "status": "already_verified"}
    directory.mkdir(parents=True, exist_ok=True)
    stage = directory / (".staging-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        files = {status: fetch_dataset(status, stage / f"{status}.csv") for status in DATASETS}
        after = {status: publisher_metadata(identifier)
                 for status, (identifier, _) in DATASETS.items()}
        if after != revisions:
            raise ValueError("SLA publisher changed during download; staged files were not published.")
        revision = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        manifest = {"revision": revision, "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    "publisher_revisions": revisions, "files": files,
                    "status": "private_research_source", "training_eligible": False,
                    "warning": "Inactive liquor license is not proof of permanent restaurant closure."}
        stage.rename(directory / revision)
        temporary = directory / (".manifest-" + uuid.uuid4().hex + ".json")
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data/raw_sources/sla_licenses")
    args = parser.parse_args()
    try:
        print(json.dumps(download(args.directory), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f"SLA download failed: {error}\n")


if __name__ == "__main__":
    main()
