import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import download_sources as downloads


class DownloadSourceTests(unittest.TestCase):
    def test_registry_covers_integrated_and_auxiliary_sources(self):
        self.assertEqual(len(downloads.SOURCES), 18)
        self.assertEqual(len(set(downloads.SOURCES)), 18)
        self.assertIn("tract_geography_2020", downloads.SOURCES)
        self.assertIn("mobile_food_vending", downloads.SOURCES)
        self.assertEqual(downloads.SOURCES["storefront_rent_stats"].identifier, "dxru-eun8")

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
