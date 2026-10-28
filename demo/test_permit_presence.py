import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from evaluation import fingerprint
from permit_presence import refresh, review_leads


class PermitPresenceTests(unittest.TestCase):
    def snapshot(self, folder, revision, observed, rows):
        raw_dir = folder / revision
        raw_dir.mkdir()
        raw = raw_dir / "rows.csv"
        fields = ["camis", "dba", "boro", "building", "street", "zipcode", "nta", "record_date"]
        with raw.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({**row, "record_date": observed.isoformat()} for row in rows)
        return {"directory": revision, "downloaded_at": observed.isoformat() + "T12:00:00Z",
                "files": [{"file": "rows.csv", "bytes": raw.stat().st_size, "rows": len(rows),
                           "sha256": fingerprint(raw)}]}

    def restaurant(self, camis, name=None):
        return {"camis": str(camis), "dba": name or f"Restaurant {camis}", "boro": "Queens",
                "building": str(camis), "street": "MAIN STREET", "zipcode": "11354", "nta": "QN12"}

    def test_full_snapshot_tracking_keeps_leads_out_of_training(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "raw"
            raw.mkdir()
            baseline = [self.restaurant(i) for i in range(1, 101)]
            later = baseline[1:] + [self.restaurant(101, name="Restaurant 1")]
            later[-1]["building"] = "1"
            revisions = [self.snapshot(raw, "first", date(2026, 1, 1), baseline),
                         self.snapshot(raw, "second", date(2026, 1, 2), later),
                         self.snapshot(raw, "third", date(2026, 1, 10), later)]
            (raw / "manifest.json").write_text(json.dumps({"source": "restaurants", "revisions": revisions}))
            output = root / "private"
            report = refresh(raw, output, min_businesses=1)
            self.assertEqual(report["distinct_snapshot_dates"], 3)
            self.assertEqual(report["review_leads"], 1)
            self.assertEqual(report["possible_replacements"], 1)
            self.assertFalse(report["one_year_training_ready"])
            self.assertEqual(report["status"], "collecting_history")
            with (output / "generated_review_leads.csv").open(newline="") as stream:
                lead = next(csv.DictReader(stream))
            self.assertEqual(lead["possible_replacement_camis"], "101")
            self.assertEqual(lead["review_status"], "possible_permit_replacement")
            self.assertNotIn("outcome_status", lead)
            self.assertEqual(refresh(raw, output, min_businesses=1)["review_leads"], 1)
            (output / "snapshots/first.csv").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                refresh(raw, output, min_businesses=1)

    def test_reappearance_is_not_a_disappearance_lead(self):
        business = self.restaurant(1)
        snapshots = [{"record_date": date(2026, 1, day), "revision": str(day),
                      "rows": {"1": business} if day in (1, 12) else {}}
                     for day in (1, 2, 12)]
        self.assertEqual(review_leads(snapshots), [])

    def test_incomplete_citywide_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "raw"
            raw.mkdir()
            baseline = [self.restaurant(i) for i in range(1, 101)]
            revisions = [self.snapshot(raw, "first", date(2026, 1, 1), baseline),
                         self.snapshot(raw, "second", date(2026, 1, 2), baseline[:90])]
            (raw / "manifest.json").write_text(json.dumps({"source": "restaurants", "revisions": revisions}))
            with self.assertRaisesRegex(ValueError, "coverage dropped"):
                refresh(raw, root / "private", min_businesses=1)
            self.assertFalse((root / "private/status.json").exists())

    def test_one_year_window_still_requires_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "raw"
            raw.mkdir()
            baseline = [self.restaurant(i) for i in range(1, 101)]
            revisions = [self.snapshot(raw, "first", date(2025, 1, 1), baseline),
                         self.snapshot(raw, "second", date(2026, 1, 3), baseline)]
            (raw / "manifest.json").write_text(json.dumps({"source": "restaurants", "revisions": revisions}))
            report = refresh(raw, root / "private", min_businesses=1)
            self.assertEqual(report["baseline_dates_with_one_year_followup"], 1)
            self.assertEqual(report["status"], "followup_snapshots_available_review_required")
            self.assertFalse(report["one_year_training_ready"])


if __name__ == "__main__":
    unittest.main()
