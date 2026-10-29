"""Versioned NYC DOF occupied-storefront rent context, separate from listings."""

import csv
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path


SOURCE_URL = "https://data.cityofnewyork.us/d/dxru-eun8"
COUNTY_BY_BOROUGH_DIGIT = {"1": "061", "2": "005", "3": "047", "4": "081", "5": "085"}


def positive_number(value):
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def source_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=4)
def parse_snapshot(path, expected_sha256):
    path = Path(path)
    if source_digest(path) != expected_sha256:
        raise ValueError("Storefront rent source checksum changed.")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    years = [int(row["reporting_year"]) for row in rows if row.get("reporting_year", "").isdigit()]
    if not years:
        raise ValueError("Storefront rent source has no reporting year.")
    year = max(years)
    by_geoid = {}
    for row in rows:
        if row.get("reporting_year") != str(year) or str(row.get("aggregate_level_citywide") or "").lower() != "census tract":
            continue
        code = row.get("aggregate_level_id", "")
        if not re.fullmatch(r"[1-5]\d{6}", code):
            continue
        rent = positive_number(row.get("median_monthly_rent_per_square"))
        if rent is None or rent > 1000:
            continue
        geoid = "36" + COUNTY_BY_BOROUGH_DIGIT[code[0]] + code[1:]
        by_geoid[geoid] = {
            "reported_median_monthly_rent_psf": round(rent, 2),
            "reported_median_storefront_sqft": positive_number(row.get("median_square_feet")),
            "registered_storefronts": positive_number(row.get("total_storefronts")),
            "leased_storefronts": positive_number(row.get("storefront_leased_to_tenants")),
        }
    if not by_geoid:
        raise ValueError("Storefront rent source has no usable tract medians.")
    return {"status": "available", "reporting_year": year, "source_url": SOURCE_URL,
            "tracts_with_reported_median": len(by_geoid), "by_geoid": by_geoid}


def load_rent_benchmarks(data_root):
    home = Path(data_root) / "raw_sources/storefront_rent_stats"
    try:
        manifest = json.loads((home / "manifest.json").read_text(encoding="utf-8"))
        revision = manifest["revisions"][-1]
        if len(revision["files"]) != 1:
            raise ValueError("Expected one versioned storefront rent file.")
        file = revision["files"][0]
        path = home / revision["directory"] / file["file"]
        return {**parse_snapshot(str(path), file["sha256"]),
                "retrieved_at": revision.get("downloaded_at")}
    except (FileNotFoundError, IndexError, KeyError, OSError, ValueError, json.JSONDecodeError):
        return {"status": "unavailable", "source_url": SOURCE_URL, "by_geoid": {}}
