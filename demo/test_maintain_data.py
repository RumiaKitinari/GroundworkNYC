import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import maintain_data as maintenance


class DataMaintenanceTests(unittest.TestCase):
    def test_default_schedule_uses_keyless_bulk_acs_provider(self):
        sources = maintenance.due_sources(date(2026, 10, 20), {})
        self.assertIn("acs_context", sources)
        self.assertNotIn("acs_demographics", sources)
        self.assertNotIn("acs_income", sources)

    def test_source_checks_follow_daily_weekly_and_monthly_periods(self):
        today = date(2026, 10, 6)
        state = {"sources": {
            "restaurants": {"period": "2026-10-05"},
            "osm": {"period": "2026-W41"},
            "citibike": {"period": "2026-10"},
        }}
        self.assertEqual(maintenance.due_sources(today, state, ["restaurants", "osm", "citibike"]),
                         ["restaurants"])
        self.assertEqual(maintenance.due_sources(date(2026, 11, 1), state, ["citibike"]),
                         ["citibike"])
        self.assertEqual(maintenance.due_sources(today, state, ["osm"], force=True), ["osm"])

    def test_release_chain_finds_latest_integrated_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            releases = root / "releases"
            older = releases / "older"
            newer = releases / "newer"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "refresh_manifest.json").write_text(json.dumps({
                "base_release": maintenance.BASELINE.name,
                "raw_revisions": {"pluto": "parcel-v1"}, "as_of": "2026-10-01"}))
            (newer / "refresh_manifest.json").write_text(json.dumps({
                "base_release": "older", "raw_revisions": {"weather": "weather-v2"},
                "as_of": "2026-10-06"}))
            current = root / "current"
            current.symlink_to(newer, target_is_directory=True)
            lineage = maintenance.release_lineage(current, root)
            self.assertEqual(lineage["weather"]["revision"], "weather-v2")
            self.assertEqual(lineage["pluto"]["revision"], "parcel-v1")

    def test_raw_only_source_is_flagged_without_publishing(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(maintenance, "DATA", Path(folder)), \
                patch.object(maintenance, "STATE", Path(folder) / "state.json"), \
                patch.object(maintenance, "INVENTORY", Path(folder) / "inventory.json"), \
                patch.object(maintenance, "RUNS", Path(folder) / "runs"), \
                patch.object(maintenance, "resolve", return_value={"version": "2023"}), \
                patch.object(maintenance, "download_source", return_value="downloaded"), \
                patch.object(maintenance, "pending_integrations", return_value=[]), \
                patch.object(maintenance, "training_inventory", return_value={"structural_issues": []}), \
                patch.object(maintenance, "run") as rebuild:
            report = maintenance.check_and_refresh(date(2026, 10, 6), selected=["mobile_food_vending"])
            self.assertEqual(report["raw_only_changes"], ["mobile_food_vending"])
            self.assertIsNone(report["published_release"])
            rebuild.assert_not_called()

    def test_score_review_flag_stops_automatic_publication(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(maintenance, "DATA", Path(folder)), \
                patch.object(maintenance, "STATE", Path(folder) / "state.json"), \
                patch.object(maintenance, "INVENTORY", Path(folder) / "inventory.json"), \
                patch.object(maintenance, "RUNS", Path(folder) / "runs"), \
                patch.object(maintenance, "pending_integrations", return_value=["pluto"]), \
                patch.object(maintenance, "training_inventory", return_value={"structural_issues": []}), \
                patch.object(maintenance.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
                patch.object(maintenance, "run", return_value={
                    "score_audit": {"review_flags": ["Ranking movement needs review"]}}) as rebuild:
            state = {"sources": {"weather": {"period": "2026-10-06"}}}
            maintenance.write_json(Path(folder) / "state.json", state)
            report = maintenance.check_and_refresh(date(2026, 10, 6), selected=["weather"])
            self.assertEqual(report["status"], "attention")
            self.assertIn("score_audit", report["blocked"])
            rebuild.assert_called_once()
            self.assertFalse(rebuild.call_args.kwargs["publish"])

    def test_restaurant_download_refreshes_private_permit_tracking(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(maintenance, "DATA", Path(folder)), \
                patch.object(maintenance, "STATE", Path(folder) / "state.json"), \
                patch.object(maintenance, "INVENTORY", Path(folder) / "inventory.json"), \
                patch.object(maintenance, "RUNS", Path(folder) / "runs"), \
                patch.object(maintenance, "resolve", return_value={"version": "2026-10-17"}), \
                patch.object(maintenance, "download_source", return_value="downloaded"), \
                patch.object(maintenance, "refresh_permit_presence", return_value={
                    "status": "collecting_history", "latest_record_date": "2026-10-16",
                    "review_leads": 55, "one_year_training_ready": False}) as track, \
                patch.object(maintenance, "pending_integrations", return_value=[]), \
                patch.object(maintenance, "training_inventory", return_value={"structural_issues": []}):
            report = maintenance.check_and_refresh(date(2026, 10, 17), selected=["restaurants"])
            track.assert_called_once_with()
            self.assertEqual(report["permit_presence"]["review_leads"], 55)

    def test_invalid_restaurant_snapshot_blocks_publication(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(maintenance, "DATA", Path(folder)), \
                patch.object(maintenance, "STATE", Path(folder) / "state.json"), \
                patch.object(maintenance, "INVENTORY", Path(folder) / "inventory.json"), \
                patch.object(maintenance, "RUNS", Path(folder) / "runs"), \
                patch.object(maintenance, "resolve", return_value={"version": "2026-10-17"}), \
                patch.object(maintenance, "download_source", return_value="downloaded"), \
                patch.object(maintenance, "refresh_permit_presence", side_effect=ValueError("Incomplete export")), \
                patch.object(maintenance, "pending_integrations", return_value=["restaurants"]), \
                patch.object(maintenance, "training_inventory", return_value={"structural_issues": []}), \
                patch.object(maintenance, "run") as publish:
            report = maintenance.check_and_refresh(date(2026, 10, 17), selected=["restaurants"])
            self.assertEqual(report["status"], "failed")
            self.assertIn("Incomplete export", report["failed"]["permit_presence"])
            publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
