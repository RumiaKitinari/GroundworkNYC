import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import download_lifespan_archive as archive


class DownloadLifespanArchiveTests(unittest.TestCase):
    def test_download_is_verified_and_existing_file_is_not_replaced(self):
        contents = b"pinned source bytes"
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(archive, "FILES", {"source.parquet": hashlib.sha256(contents).hexdigest()}), \
                patch.object(archive, "urlopen", return_value=io.BytesIO(contents)) as fetch:
            first = archive.download(folder)
            second = archive.download(folder)
            self.assertEqual((Path(folder) / "source.parquet").read_bytes(), contents)
            self.assertEqual(first["files"]["source.parquet"], "downloaded_and_verified")
            self.assertEqual(second["files"]["source.parquet"], "already_verified")
            fetch.assert_called_once()

    def test_wrong_hash_does_not_publish_file(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(archive, "FILES", {"source.parquet": "0" * 64}), \
                patch.object(archive, "urlopen", return_value=io.BytesIO(b"different")):
            with self.assertRaisesRegex(ValueError, "hash differs"):
                archive.download(folder)
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
