"""Add conservative SLA license-history leads to the DOHMH lifespan review queue."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from evaluation import fingerprint
from refresh_integrated import ROOT


COUNTY_TO_BOROUGH = {"new york": "manhattan", "kings": "brooklyn", "queens": "queens",
                     "bronx": "bronx", "richmond": "staten island"}
STREET_ALIASES = {"STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD",
                  "PLACE": "PL", "DRIVE": "DR", "PARKWAY": "PKWY", "COURT": "CT",
                  "LANE": "LN", "TERRACE": "TER", "EAST": "E", "WEST": "W",
                  "NORTH": "N", "SOUTH": "S"}
EXTRA_FIELDS = ("sla_match_status", "sla_active_ids", "sla_inactive_ids",
                "sla_active_original_issues", "sla_inactive_original_issues",
                "sla_inactive_expiration_dates", "sla_license_descriptions",
                "sla_other_name_same_address_count", "sla_active_source_url",
                "sla_inactive_source_url")


def normalized_name(value):
    return " ".join(re.findall(r"[A-Z0-9]+", (value or "").upper().replace("&", " AND ")))


def normalized_address(street, zipcode, borough=""):
    if borough.strip().lower() == "queens":
        street = re.sub(r"^\s*(\d{1,3})\s*-\s*(\d{1,3})(?=\s|$)", r"\1\2", street or "")
    tokens = re.findall(r"[A-Z0-9]+", (street or "").upper())
    tokens = [STREET_ALIASES.get(re.sub(r"(?<=\d)(ST|ND|RD|TH)$", "", token),
                                 re.sub(r"(?<=\d)(ST|ND|RD|TH)$", "", token))
              for token in tokens]
    zip5 = re.search(r"\d{5}", zipcode or "")
    return (" ".join(tokens), zip5.group() if zip5 else "")


def candidate_address(value, borough=""):
    match = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", value or "")
    return normalized_address(value[:match.start()].strip(), match.group(1), borough) if match else ("", "")


def read_license_file(path, status):
    fields = {"inactive": {"id": "license_permit_id", "county": "premises_county",
                           "street": "actual_address_of_premises", "zip": "zip_code",
                           "original": "original_issue_date", "expires": "expiration_date"},
              "active": {"id": "licensepermitid", "county": "premisescounty",
                         "street": "actualaddressofpremises", "zip": "zipcode",
                         "original": "originalissuedate", "expires": "expirationdate"}}[status]
    by_identity, by_address = defaultdict(list), defaultdict(list)
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = set(fields.values()) | {"dba", "legalname", "description"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"SLA {status} file is missing: " +
                             ", ".join(sorted(required - set(reader.fieldnames or []))))
        count = 0
        for row in reader:
            count += 1
            borough = COUNTY_TO_BOROUGH.get((row[fields["county"]] or "").strip().lower())
            address = normalized_address(row[fields["street"]], row[fields["zip"]])
            if not borough or not all(address):
                continue
            item = {"id": row[fields["id"]].strip(), "dba": row["dba"].strip(),
                    "legalname": row["legalname"].strip(), "description": row["description"].strip(),
                    "original": row[fields["original"]][:10], "expires": row[fields["expires"]][:10]}
            address_key = (borough, *address)
            by_address[address_key].append(item)
            for name in {normalized_name(item["dba"]), normalized_name(item["legalname"])} - {""}:
                by_identity[(address_key, name)].append(item)
    return by_identity, by_address, count


def attach_leads(queue_path, active_path, inactive_path):
    active, active_addresses, active_count = read_license_file(active_path, "active")
    inactive, inactive_addresses, inactive_count = read_license_file(inactive_path, "inactive")
    with Path(queue_path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        required = {"business_id", "candidate_name", "candidate_address", "borough",
                    "first_operational_prepermit", "verification_status", "outcome_status"}
        if not required <= set(fields) or set(EXTRA_FIELDS) & set(fields):
            raise ValueError("Expected an untouched lifespan queue without SLA match fields.")
        rows = list(reader)
    counts = Counter()
    for row in rows:
        if row["verification_status"] != "independent_verification_required" or row["outcome_status"] != "unresolved":
            raise ValueError("SLA matching requires an untouched unresolved review queue.")
        address = candidate_address(row["candidate_address"])
        key = (row["borough"].strip().lower(), *address)
        name_key = (key, normalized_name(row["candidate_name"]))
        baseline = date.fromisoformat(row["first_operational_prepermit"])
        active_hits = active.get(name_key, []) if all(address) else []
        inactive_hits = [item for item in inactive.get(name_key, [])
                         if not item["expires"] or date.fromisoformat(item["expires"]) >= baseline]
        other_at_address = len(active_addresses.get(key, [])) + len(inactive_addresses.get(key, []))
        status = ("both_active_and_inactive_license_leads" if active_hits and inactive_hits else
                  "active_license_lead" if active_hits else
                  "inactive_license_lead" if inactive_hits else "no_exact_license_match")
        counts[status] += 1
        row.update(dict.fromkeys(EXTRA_FIELDS, ""))
        row["sla_match_status"] = status
        row["sla_active_ids"] = ";".join(sorted({item["id"] for item in active_hits if item["id"]}))
        row["sla_inactive_ids"] = ";".join(sorted({item["id"] for item in inactive_hits if item["id"]}))
        row["sla_active_original_issues"] = ";".join(sorted({item["original"] for item in active_hits if item["original"]}))
        row["sla_inactive_original_issues"] = ";".join(sorted({item["original"] for item in inactive_hits if item["original"]}))
        row["sla_inactive_expiration_dates"] = ";".join(sorted({item["expires"] for item in inactive_hits if item["expires"]}))
        row["sla_license_descriptions"] = ";".join(sorted({item["description"] for item in active_hits + inactive_hits
                                                              if item["description"]}))
        row["sla_other_name_same_address_count"] = str(max(0, other_at_address - len(active_hits) - len(inactive_hits)))
        for license_status, identifier, id_field in (("active", "9s3h-dpkz", "licensepermitid"),
                                                     ("inactive", "6dg3-2z7i", "license_permit_id")):
            ids = row[f"sla_{license_status}_ids"].split(";") if row[f"sla_{license_status}_ids"] else []
            where = id_field + " in (" + ",".join("'" + value.replace("'", "''") + "'" for value in ids) + ")"
            row[f"sla_{license_status}_source_url"] = (
                f"https://data.ny.gov/resource/{identifier}.json?" + urlencode({"$where": where})
                if ids else f"https://data.ny.gov/d/{identifier}")
    return rows, fields + list(EXTRA_FIELDS), {"queue_rows": len(rows),
                                               "active_nyc_license_rows": active_count,
                                               "inactive_nyc_license_rows": inactive_count,
                                               "match_status_counts": dict(counts)}


def write_leads(queue_path, active_path, inactive_path, output_path):
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("SLA leads output or manifest already exists.")
    rows, fields, summary = attach_leads(queue_path, active_path, inactive_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), **summary,
                "source_sha256": {"queue": fingerprint(queue_path), "active": fingerprint(active_path),
                                  "inactive": fingerprint(inactive_path)},
                "output_sha256": fingerprint(output_path), "training_eligible": False,
                "warning": "An inactive liquor license is not proof of a permanent restaurant closure or its date. Exact name/address matches require identity review; license expiration is not closure date."}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--sla-manifest", type=Path, default=ROOT / "data/raw_sources/sla_licenses/manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        revision = json.loads(args.sla_manifest.read_text(encoding="utf-8"))["revision"]
        root = args.sla_manifest.parent / revision
        print(json.dumps(write_leads(args.queue, root / "active.csv", root / "inactive.csv", args.output), indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"SLA lead matching failed: {error}\n")


if __name__ == "__main__":
    main()
