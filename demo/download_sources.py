"""Versioned downloads for the integrated sources and two auxiliary inputs.

This stages raw publisher data only. It never edits cleaned sources, the master
tract table, or the running dashboard's cached dataset.
"""

import argparse
import csv
import gzip
import hashlib
import http.client
import json
import os
import shutil
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "data" / "raw_sources"
NYC_COUNTIES = ("005", "047", "061", "081", "085")
USER_AGENT = "GroundworkNYC-capstone/1.0 (public-data research)"
PAGE_SIZE = 50000
ACS_CONTEXT_TABLES = ("b01001", "b17001", "b19301", "b19001", "b08301", "b15003", "b05002", "b11001", "b25003", "b25064", "b19013", "b23025", "b25010")


@dataclass(frozen=True)
class Source:
    name: str
    label: str
    kind: str
    cadence: str
    identifier: str = ""
    minimum_bytes: int = 100


SOURCES = {
    source.name: source for source in (
        Source("acs_demographics", "ACS tract demographics", "acs_profile", "annual", minimum_bytes=1000),
        Source("acs_income", "ACS tract income", "acs_income", "annual", minimum_bytes=1000),
        Source("lodes", "LODES workplace jobs", "lodes", "annual", minimum_bytes=100000),
        Source("lodes_rac", "LODES residence-area jobs", "lodes_rac", "annual", minimum_bytes=100000),
        Source("acs_context", "ACS social economic housing context", "acs_context", "annual", minimum_bytes=1000000),
        Source("subway_entrances", "MTA subway entrances and exits", "socrata_ny", "on publisher update", "i9wp-a4ja"),
        Source("taxi_zone_geometry", "TLC taxi zone geometry", "taxi_geometry", "on publisher update", minimum_bytes=100000),
        Source("osm", "BBBike New York OSM extract", "osm", "weekly", minimum_bytes=1000000),
        Source("restaurants", "NYC restaurant inspections", "socrata", "daily", "43nn-pn8j"),
        Source("mta_subway", "MTA station-hour subway entries", "mta", "weekly", "5wq4-mkjj"),
        Source("citibike", "Citi Bike monthly trips", "citibike", "monthly", minimum_bytes=1000000),
        Source("pedestrians", "NYC DOT pedestrian counts", "socrata", "on publisher update", "cqsj-cfgu"),
        Source("tlc_hvfhv", "TLC high-volume for-hire trips", "tlc", "monthly", minimum_bytes=1000000),
        Source("pluto", "NYC PLUTO tax lots", "socrata", "on publisher update", "64uk-42ks"),
        Source("storefronts", "NYC Storefront Registry", "socrata", "on publisher update", "92iy-9c3n"),
        Source("storefront_rent_stats", "NYC storefront rent statistics", "socrata", "annual", "dxru-eun8"),
        Source("epa_walkability", "EPA Smart Location Database v3", "epa", "on publisher update", minimum_bytes=1000000),
        Source("events", "NYC permitted events", "socrata", "daily", "tvpp-9vvx"),
        Source("events_historical", "NYC historical permitted events", "socrata", "on publisher update", "bkfu-528j"),
        Source("sla_active_context", "NYS active liquor licenses for current context", "socrata_ny", "on publisher update", "9s3h-dpkz"),
        Source("weather", "NOAA Central Park daily weather", "weather", "daily", minimum_bytes=10000),
        Source("business_patterns", "Census ZIP Business Patterns", "cbp", "annual", minimum_bytes=100000),
        Source("business_patterns_2015", "Census ZIP Business Patterns 2015 baseline", "cbp_2015", "fixed 2015", minimum_bytes=100000),
        Source("tract_geography_2020", "2020 New York Census tracts", "geography", "fixed 2020", minimum_bytes=100000),
        Source("mobile_food_vending", "NYC mobile food vending violations", "socrata", "on publisher update", "jdpy-va39"),
    )
}


def request(url, method="GET", attempts=4, headers=None):
    for attempt in range(attempts):
        try:
            return urlopen(Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}), timeout=120)
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except (URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(min(8, 2 ** attempt))
    raise RuntimeError("Download retries exhausted")


def remote_headers(url):
    with request(url, method="HEAD", attempts=2) as response:
        return {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"),
                "content_length": response.headers.get("Content-Length")}


def first_available(build_url, years_or_months):
    for value in years_or_months:
        url = build_url(value)
        try:
            headers = remote_headers(url)
            if headers.get("content_length") == "0":
                continue
            return value, url, headers
        except HTTPError as error:
            if error.code not in (403, 404):
                raise
    raise ValueError("No published file found in the discovery window")


def month_candidates(today, starting_lag=1, count=12):
    first = today.replace(day=1)
    for offset in range(starting_lag, starting_lag + count):
        month = first.month - 2 - offset
        yield f"{first.year + month // 12:04d}-{month % 12 + 1:02d}"


def census_year(build_url, today):
    return first_available(build_url, range(today.year - 1, today.year - 6, -1))


def socrata_metadata(source):
    host = "data.ny.gov" if source.kind in ("mta", "socrata_ny") else "data.cityofnewyork.us"
    url = f"https://{host}/api/views/{source.identifier}.json"
    with request(url) as response:
        meta = json.load(response)
    updated = meta.get("rowsUpdatedAt")
    if not updated:
        raise ValueError(f"Publisher did not provide a data-update timestamp for {source.name}")
    return {"url": url, "name": meta.get("name"), "rows_updated_at": updated,
            "version": str(updated), "data_url": f"https://{host}/resource/{source.identifier}.csv"}


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(source, today):
    kind = source.kind
    if kind in ("socrata", "socrata_ny", "mta"):
        info = socrata_metadata(source)
        if kind == "mta":
            url = info["data_url"].replace(".csv", ".json") + "?" + urlencode(
                {"$select": "max(transit_timestamp) as latest", "$where": "transit_mode = 'subway'"})
            with request(url) as response:
                latest = date.fromisoformat(json.load(response)[0]["latest"][:10])
            # A full Monday-Sunday week must precede the most recent observed day.
            monday = latest - timedelta(days=latest.weekday() + 7)
            info["week_start"] = monday.isoformat()
            info["version"] += "_" + info["week_start"] + "_ridership_transfers_v2"
        return info
    if kind in ("acs_profile", "acs_income"):
        group = "profile" if kind == "acs_profile" else "detail"
        metadata = "https://api.census.gov/data/{year}/acs/acs5" + ("/profile" if group == "profile" else "") + ".json"
        year, _, _ = census_year(lambda y: metadata.format(year=y), today)
        base = "https://api.census.gov/data/{year}/acs/acs5"
        if group == "profile":
            base += "/profile?get=NAME,group(DP05)&for=tract:*&in=state:36&in=county:005"
        else:
            base += "?get=NAME,B19013_001E,B19013_001M&for=tract:*&in=state:36&in=county:005"
        urls = [base.format(year=year).replace("county:005", f"county:{county}") for county in NYC_COUNTIES]
        key = os.environ.get("CENSUS_API_KEY")
        return {"version": str(year), "urls": [url + "&" + urlencode({"key": key}) if key else url for url in urls],
                "url": urls[0], "format": "json", "credentials_required": not bool(key)}
    if kind == "acs_context":
        build = lambda y: f"https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/acsdt5y{y}-b01001.dat"
        year, url, headers = census_year(build, today)
        urls = [build(year).replace("b01001.dat", table + ".dat") for table in ACS_CONTEXT_TABLES]
        return {"version": str(year), "url": url, "headers": headers, "format": "dat",
                "urls": urls, "table_headers": {link: remote_headers(link) for link in urls}}
    if kind in ("lodes", "lodes_rac"):
        area = "rac" if kind == "lodes_rac" else "wac"
        year, url, headers = census_year(
            lambda y: f"https://lehd.ces.census.gov/data/lodes/LODES8/ny/{area}/ny_{area}_S000_JT00_{y}.csv.gz", today)
        return {"version": str(year), "url": url, "headers": headers, "format": "gz"}
    if kind == "cbp_2015":
        url = "https://www2.census.gov/programs-surveys/cbp/datasets/2015/zbp15detail.zip"
        return {"version": "2015", "url": url, "headers": remote_headers(url), "format": "zip"}
    if kind == "cbp":
        year, url, headers = census_year(
            lambda y: f"https://www2.census.gov/programs-surveys/cbp/datasets/{y}/zbp{str(y)[2:]}detail.zip", today)
        return {"version": str(year), "url": url, "headers": headers, "format": "zip"}
    if kind in ("citibike", "tlc"):
        if kind == "citibike":
            build = lambda month: f"https://s3.amazonaws.com/tripdata/{month.replace('-', '')}-citibike-tripdata.zip"
        else:
            build = lambda month: f"https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_{month}.parquet"
        month, url, headers = first_available(build, month_candidates(today, 0 if kind == "citibike" else 1))
        return {"version": month, "url": url, "headers": headers, "format": "zip" if kind == "citibike" else "parquet"}
    urls = {
        "osm": ("https://download.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf", "pbf"),
        "epa": ("https://edg.epa.gov/data/public/OLEM/SLD/SmartLocationDatabaseV3.zip", "zip"),
        "weather": ("https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv", "csv"),
        "geography": ("https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_36_tract_500k.zip", "zip"),
        "taxi_geometry": ("https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip", "zip"),
    }
    url, fmt = urls[kind]
    headers = remote_headers(url)
    return {"version": headers.get("last_modified") or "current", "url": url,
            "headers": headers, "format": fmt}


def manifest_path(source):
    return DESTINATION / source.name / "manifest.json"


def load_manifest(source):
    path = manifest_path(source)
    return json.loads(path.read_text()) if path.exists() else {"source": source.name, "revisions": []}


def fingerprint(info):
    headers = info.get("headers") or {}
    details = {"version": info["version"], "url": info["url"],
               "etag": headers.get("etag"), "last_modified": headers.get("last_modified")}
    if "table_headers" in info:
        details["table_headers"] = info["table_headers"]
    return json.dumps(details, sort_keys=True)


def stage_file(url, path, minimum_bytes, fmt):
    with request(url) as response, path.open("wb") as target:
        expected_bytes = getattr(response, "headers", {}).get("Content-Length")
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    if expected_bytes and path.stat().st_size != int(expected_bytes):
        raise ValueError(f"Incomplete publisher file: {path.name}")
    if path.stat().st_size < minimum_bytes:
        raise ValueError(f"Downloaded file is too small: {path.name}")
    with path.open("rb") as stream:
        beginning = stream.read(256)
        if beginning.lstrip().startswith((b"<html", b"<!DOCTYPE", b"{\"error\"")):
            raise ValueError("Publisher returned an error page instead of data")
        if fmt == "gzip" and not beginning.startswith(b"\x1f\x8b"):
            raise ValueError("Expected gzip data")
        if fmt == "parquet":
            stream.seek(-4, 2)
            if beginning[:4] != b"PAR1" or stream.read(4) != b"PAR1":
                raise ValueError("Expected complete Parquet data")
        if fmt == "pbf" and b"OSMHeader" not in beginning:
            raise ValueError("Expected an OpenStreetMap PBF")
    if fmt == "zip" and not zipfile.is_zipfile(path):
        raise ValueError("Expected a complete ZIP archive")
    if fmt == "json":
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, list) or len(data) < 2 or not isinstance(data[0], list):
            raise ValueError("Expected Census tabular JSON")
    if fmt == "csv":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            if len(next(csv.reader(stream), [])) < 2:
                raise ValueError("Expected a CSV header")
    if fmt == "dat":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            if "GEO_ID" not in next(csv.reader(stream, delimiter="|"), []):
                raise ValueError("Expected an ACS table-based summary file")
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": file_digest(path)}


def download_socrata(source, info, stage):
    host = "data.ny.gov" if source.kind == "socrata_ny" else "data.cityofnewyork.us"
    base = f"https://{host}/resource/{source.identifier}"
    with request(base + ".json?" + urlencode({"$select": "count(*) as n"})) as response:
        expected = int(json.load(response)[0]["n"])
    if expected < 1:
        raise ValueError("Publisher table is empty")
    path = stage / "rows.csv"
    if source.name == "events_historical":
        url = f"https://data.cityofnewyork.us/api/views/{source.identifier}/rows.csv?accessType=DOWNLOAD"
        packed = stage / ".bulk-transfer"
        with request(url, headers={"Accept-Encoding": "gzip"}) as response, packed.open("wb") as target:
            encoding = response.headers.get("Content-Encoding", "").lower()
            expected_bytes = response.headers.get("Content-Length")
            shutil.copyfileobj(response, target)
        if expected_bytes and packed.stat().st_size != int(expected_bytes):
            raise ValueError("Incomplete historical-event transfer")
        if encoding == "gzip":
            with gzip.open(packed, "rb") as incoming, path.open("wb") as target:
                shutil.copyfileobj(incoming, target)
            packed.unlink()
        elif encoding in {"", "identity"}:
            packed.rename(path)
        else:
            raise ValueError("Unsupported historical-event transfer encoding")
        result = stage_file_validation(path, "csv")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream)
            fields = next(reader)
            total = 0
            for row in reader:
                if len(row) != len(fields):
                    raise ValueError("Malformed historical-event bulk export row")
                total += 1
        if total != expected or socrata_metadata(source)["rows_updated_at"] != info["rows_updated_at"]:
            raise ValueError("Historical-event bulk export does not match stable publisher count/version")
        result["rows"] = total
        print(f"  {source.name}: {total:,}/{expected:,} rows (complete bulk export)", flush=True)
        return [result]
    page_path = stage / ".page.csv"
    total, fields = 0, None
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        while total < expected:
            url = base + ".csv?" + urlencode({"$order": ":id", "$limit": PAGE_SIZE, "$offset": total})
            for attempt in range(4):
                try:
                    with request(url) as response, page_path.open("wb") as page:
                        content_length = response.headers.get("Content-Length")
                        shutil.copyfileobj(response, page)
                    if content_length and page_path.stat().st_size != int(content_length):
                        raise http.client.IncompleteRead(b"", int(content_length))
                    break
                except (OSError, http.client.IncompleteRead):
                    if attempt == 3:
                        raise
                    time.sleep(min(8, 2 ** attempt))
            with page_path.open(newline="", encoding="utf-8-sig") as page:
                reader = csv.reader(page)
                header = next(reader, None)
                if not header or (fields is not None and header != fields):
                    raise ValueError("Publisher schema changed during pagination")
                page_rows = 0
                for row in reader:
                    if len(row) != len(header):
                        raise ValueError("Malformed publisher CSV row")
                    page_rows += 1
            if page_rows != min(PAGE_SIZE, expected - total):
                raise ValueError("Publisher page row count changed during download")
            if fields is None:
                fields = header
                writer.writerow(header)
            with page_path.open(newline="", encoding="utf-8-sig") as page:
                reader = csv.reader(page)
                next(reader)
                writer.writerows(reader)
            total += page_rows
            print(f"  {source.name}: {total:,}/{expected:,} rows", flush=True)
    page_path.unlink()
    if total != expected or socrata_metadata(source)["rows_updated_at"] != info["rows_updated_at"]:
        raise ValueError("Publisher changed during download; staged snapshot was not published")
    result = stage_file_validation(path, "csv")
    result["rows"] = total
    return [result]


def stage_file_validation(path, fmt):
    # Validate already-downloaded output without issuing another request.
    if path.stat().st_size == 0:
        raise ValueError("Empty download")
    if fmt == "csv":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            if len(next(csv.reader(stream), [])) < 2:
                raise ValueError("Missing CSV header")
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": file_digest(path)}


def download_mta(info, stage):
    from download_subway import download_week

    result = download_week(info["week_start"], stage)
    return [{"file": result["file"], "bytes": (stage / result["file"]).stat().st_size,
             "sha256": result["sha256"], "rows": result["rows"], "hours": result["hours"],
             "stations": result["stations"]}]


def download_source(source, info, force=False):
    if info.get("credentials_required"):
        raise ValueError("CENSUS_API_KEY is required for Census data queries; see demo/README.md")
    manifest = load_manifest(source)
    key = fingerprint(info)
    if not force and any(revision.get("fingerprint") == key for revision in manifest["revisions"]):
        print(f"{source.name}: unchanged; already downloaded")
        return "unchanged"
    home = DESTINATION / source.name
    home.mkdir(parents=True, exist_ok=True)
    stage = home / (".staging-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        if source.kind in ("socrata", "socrata_ny"):
            files = download_socrata(source, info, stage)
        elif source.kind == "mta":
            files = download_mta(info, stage)
        else:
            urls = info.get("urls") or [info["url"]]
            files = []
            for index, url in enumerate(urls):
                suffix = {"gz": ".csv.gz", "pbf": ".osm.pbf", "zip": ".zip", "parquet": ".parquet",
                          "json": ".json", "csv": ".csv", "dat": ".dat"}[info["format"]]
                name = (url.rsplit("/", 1)[-1] if source.kind == "acs_context" else
                        f"raw_{NYC_COUNTIES[index]}{suffix}" if len(urls) > 1 else "raw" + suffix)
                print(f"  downloading {source.name}: {name}", flush=True)
                files.append(stage_file(url, stage / name, source.minimum_bytes,
                                        "gzip" if info["format"] == "gz" else info["format"]))
                if source.kind == "acs_context":
                    files[-1]["source_url"] = url
                    files[-1]["publisher_headers"] = info["table_headers"][url]
            if source.kind == "acs_context":
                for url, before in info["table_headers"].items():
                    after = remote_headers(url)
                    if any(before.get(field) and after.get(field) != before[field] for field in ("etag", "last_modified", "content_length")):
                        raise ValueError("An ACS table changed during download")
            if source.kind not in ("acs_profile", "acs_income"):
                before = info.get("headers") or {}
                after = remote_headers(info["url"])
                for field in ("etag", "last_modified"):
                    if before.get(field) and after.get(field) != before[field]:
                        raise ValueError("Publisher file changed during download; staged copy was not published")
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        revision_name = now + "_" + uuid.uuid4().hex[:8]
        revision = {"fingerprint": key, "publisher_version": info["version"], "source_url": info["url"],
                    "downloaded_at": datetime.now(timezone.utc).isoformat(), "directory": revision_name,
                    "files": files}
        stage.rename(home / revision_name)
        manifest["revisions"].append(revision)
        temp_manifest = home / (".manifest-" + uuid.uuid4().hex + ".json")
        temp_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
        temp_manifest.replace(manifest_path(source))
        print(f"{source.name}: saved {len(files)} file(s) in {revision_name}")
        return "downloaded"
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--list", action="store_true", help="List the source families")
    choice.add_argument("--source", action="append", choices=sorted(SOURCES), help="Download one or more sources")
    choice.add_argument("--all", action="store_true", help="Download every source (several GB possible)")
    parser.add_argument("--check", action="store_true", help="Check publisher versions without downloading")
    parser.add_argument("--force", action="store_true", help="Create a new revision even when unchanged")
    args = parser.parse_args()
    if args.list:
        for source in SOURCES.values():
            print(f"{source.name:20} {source.cadence:20} {source.label}")
        return 0
    today = date.today()
    selected = list(SOURCES) if args.all else list(dict.fromkeys(args.source))
    failed = []
    for name in selected:
        source = SOURCES[name]
        try:
            info = resolve(source, today)
            changed = not any(revision.get("fingerprint") == fingerprint(info)
                              for revision in load_manifest(source)["revisions"])
            if args.check:
                note = "; CENSUS_API_KEY required to download" if info.get("credentials_required") else ""
                print(f"{name}: publisher version {info['version']}; {'new' if changed else 'already downloaded'}{note}")
            else:
                download_source(source, info, args.force)
        except (ValueError, OSError, HTTPError, URLError, json.JSONDecodeError) as error:
            print(f"{name}: FAILED: {error}", file=sys.stderr)
            failed.append(name)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
