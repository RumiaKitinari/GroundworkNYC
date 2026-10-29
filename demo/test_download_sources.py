import io
import json
import tempfile
import gzip
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import download_sources as downloads


class DownloadSourceTests(unittest.TestCase):
    def test_historical_bulk_gzip_is_complete_and_count_checked(self):
        class Response(io.BytesIO):
            def __init__(self, content, headers=None):
                super().__init__(content)
                self.headers = headers or {}

        payload = b"event_id,name\n1,First\n2,Second\n"
        packed = gzip.compress(payload)
        def fake_request(url, **kwargs):
            if "count" in url:
                return Response(b'[{"n":"2"}]')
            self.assertEqual(kwargs["headers"]["Accept-Encoding"], "gzip")
            return Response(packed, {"Content-Encoding": "gzip", "Content-Length": str(len(packed))})

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(downloads, "request", side_effect=fake_request), \
                patch.object(downloads, "socrata_metadata", return_value={"rows_updated_at": 1}):
            result = downloads.download_socrata(downloads.SOURCES["events_historical"], {"rows_updated_at": 1}, Path(folder))
            self.assertEqual(result[0]["rows"], 2)
            self.assertEqual((Path(folder) / "rows.csv").read_bytes(), payload)

    def test_socrata_retries_interrupted_page_without_duplicate_rows(self):
        source = downloads.SOURCES["restaurants"]
        calls = {"second_page": 0}

        class Response(io.BytesIO):
            def __init__(self, payload, fail=False):
                super().__init__(payload)
                self.headers = {"Content-Length": str(len(payload))}
                self.fail = fail

            def read(self, size=-1):
                if self.fail and self.tell() > 0:
                    raise ConnectionResetError("stream interrupted")
                return super().read(8 if self.fail else size)

        def fake_request(url, **_kwargs):
            query = parse_qs(urlsplit(url).query)
            if "$select" in query:
                return Response(b'[{"n":"4"}]')
            offset = int(query["$offset"][0])
            if offset == 0:
                return Response(b"id,name\n1,One\n2,Two\n")
            calls["second_page"] += 1
            return Response(b"id,name\n3,Three\n4,Four\n", fail=calls["second_page"] == 1)

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(downloads, "PAGE_SIZE", 2), \
                patch.object(downloads, "request", side_effect=fake_request), \
                patch.object(downloads, "socrata_metadata", return_value={"rows_updated_at": 1}), \
                patch.object(downloads.time, "sleep"):
            result = downloads.download_socrata(source, {"rows_updated_at": 1}, Path(folder))
            self.assertEqual(result[0]["rows"], 4)
            self.assertEqual(calls["second_page"], 2)
            self.assertEqual((Path(folder) / "rows.csv").read_text(),
                             "id,name\n1,One\n2,Two\n3,Three\n4,Four\n")

    def test_registry_covers_integrated_and_auxiliary_sources(self):
        self.assertEqual(len(downloads.SOURCES), 25)
        self.assertEqual(len(set(downloads.SOURCES)), 25)
        self.assertEqual(downloads.SOURCES["events_historical"].identifier, "bkfu-528j")
        self.assertEqual(downloads.SOURCES["business_patterns_2015"].kind, "cbp_2015")
        self.assertIn("tract_geography_2020", downloads.SOURCES)
        self.assertIn("mobile_food_vending", downloads.SOURCES)
        self.assertEqual(downloads.SOURCES["storefront_rent_stats"].identifier, "dxru-eun8")
        self.assertEqual(downloads.SOURCES["subway_entrances"].kind, "socrata_ny")

    def test_month_discovery_starts_with_latest_complete_month(self):
        self.assertEqual(list(downloads.month_candidates(date(2026, 9, 30), 0, 3)),
                         ["2026-08", "2026-07", "2026-06"])
        self.assertEqual(list(downloads.month_candidates(date(2027, 1, 1), 1, 2)),
                         ["2026-11", "2026-10"])

    def test_direct_download_is_versioned_and_skips_unchanged_source(self):
        source = downloads.SOURCES["weather"]
        info = {"version": "test", "url": "https://example.test/weather.csv", "format": "csv",
                "headers": {"etag": "one"}}
        payload = b"date,temperature\n2026-09-30,20\n" * 500
        with tempfile.TemporaryDirectory() as folder, patch.object(downloads, "DESTINATION", Path(folder)), \
                patch.object(downloads, "request", side_effect=lambda *args, **kwargs: io.BytesIO(payload)), \
                patch.object(downloads, "remote_headers", return_value={"etag": "one"}):
            self.assertEqual(downloads.download_source(source, info), "downloaded")
            self.assertEqual(downloads.download_source(source, info), "unchanged")
            self.assertEqual(downloads.download_source(source, info, force=True), "downloaded")
            manifest = json.loads(downloads.manifest_path(source).read_text())
            self.assertEqual(len(manifest["revisions"]), 2)
            for revision in manifest["revisions"]:
                path = Path(folder) / source.name / revision["directory"] / revision["files"][0]["file"]
                self.assertEqual(path.read_bytes(), payload)

    def test_error_page_never_becomes_a_published_revision(self):
        source = downloads.SOURCES["weather"]
        info = {"version": "test", "url": "https://example.test/weather.csv", "format": "csv"}
        with tempfile.TemporaryDirectory() as folder, patch.object(downloads, "DESTINATION", Path(folder)), \
                patch.object(downloads, "request", side_effect=lambda *args, **kwargs: io.BytesIO(b"<html>error</html>" * 1000)), \
                patch.object(downloads, "remote_headers", return_value={}):
            with self.assertRaises(ValueError):
                downloads.download_source(source, info)
            self.assertFalse(downloads.manifest_path(source).exists())
            self.assertEqual(list((Path(folder) / source.name).iterdir()), [])

    def test_census_key_is_used_but_not_recorded_in_source_url(self):
        with patch.object(downloads, "census_year", return_value=(2024, "", {})), \
                patch.dict("os.environ", {"CENSUS_API_KEY": "private-test-key"}):
            info = downloads.resolve(downloads.SOURCES["acs_income"], date(2026, 9, 30))
        self.assertEqual(info["version"], "2024")
        self.assertEqual(len(info["urls"]), 5)
        self.assertIn("private-test-key", info["urls"][0])
        self.assertNotIn("private-test-key", info["url"])
        self.assertNotIn("private-test-key", downloads.fingerprint(info))

    def test_mutated_publisher_file_is_not_published(self):
        source = downloads.SOURCES["weather"]
        info = {"version": "test", "url": "https://example.test/weather.csv", "format": "csv",
                "headers": {"etag": "old"}}
        with tempfile.TemporaryDirectory() as folder, patch.object(downloads, "DESTINATION", Path(folder)), \
                patch.object(downloads, "request", side_effect=lambda *args, **kwargs: io.BytesIO(b"date,value\n2026-09-30,1\n" * 500)), \
                patch.object(downloads, "remote_headers", return_value={"etag": "new"}):
            with self.assertRaisesRegex(ValueError, "changed during download"):
                downloads.download_source(source, info)
            self.assertFalse(downloads.manifest_path(source).exists())


if __name__ == "__main__":
    unittest.main()
