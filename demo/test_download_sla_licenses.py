import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import download_sla_licenses as sla
from evaluation import fingerprint


class DownloadSlaLicensesTests(unittest.TestCase):
    def test_pinned_revision_is_reused_only_when_files_verify(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(sla, "publisher_metadata", return_value=123), \
                patch.object(sla, "fetch_dataset") as fetch:
            def fake_fetch(status, path):
                path.write_text(status + "\n", encoding="utf-8")
                return {"rows": 1, "sha256": fingerprint(path)}

            fetch.side_effect = fake_fetch
            first = sla.download(folder)
            second = sla.download(folder)
            self.assertEqual(first["revision"], second["revision"])
            self.assertEqual(second["status"], "already_verified")
            self.assertEqual(fetch.call_count, 2)
            self.assertTrue((Path(folder) / first["revision"] / "inactive.csv").is_file())


if __name__ == "__main__":
    unittest.main()
