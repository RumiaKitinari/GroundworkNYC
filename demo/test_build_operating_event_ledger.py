import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from build_operating_event_ledger import classify_event, collect_ledger, summarize


class OperatingLedgerTests(unittest.TestCase):
    def test_closure_is_not_operation_or_permanent_exit(self):
        self.assertEqual(classify_event("Cycle Inspection / Initial Inspection", ["Establishment Closed by DOHMH."]),
                         "temporary_health_closure_not_permanent_exit")
        self.assertEqual(classify_event("Cycle Inspection / Reopening Inspection", ["Establishment re-opened by DOHMH."]),
                         "reopening_operation_evidence")

    def test_nonoperational_blank_and_future_events_not_accepted(self):
        action = "Violations were cited in the following area(s)."
        self.assertEqual(classify_event("Pre-permit (Non-operational) / Initial Inspection", [action]),
                         "nonoperational_not_trading_evidence")
        self.assertEqual(classify_event("Cycle Inspection / Initial Inspection", [""]), "unclassified_not_operation_evidence")
        self.assertEqual(classify_event("Cycle Inspection / Initial Inspection", [action], valid_time=False), "invalid_or_placeholder_time")

    def test_operational_prepermit_supported_but_not_opening(self):
        self.assertEqual(classify_event("Pre-permit (Operational) / Initial Inspection", ["No violations were recorded at the time of this inspection."]),
                         "dated_operation_evidence")

    def test_dedup_gzip_and_identity_drift(self):
        candidate = {"business_id": "1", "candidate_name": "Test Cafe", "candidate_address": "10 Main St 10001",
                     "borough": "Manhattan", "first_cycle_inspection_lead": "2023-04-11"}
        base = {"CAMIS": "1", "DBA": "Test Cafe", "BORO": "Manhattan", "BUILDING": "10", "STREET": "MAIN STREET",
                "ZIPCODE": "10001", "INSPECTION DATE": "04/11/2023", "INSPECTION TYPE": "Cycle Inspection / Initial Inspection",
                "ACTION": "Violations were cited in the following area(s).", "RECORD DATE": "11/16/2023"}
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "wayback_20231117063638.csv"
            second = Path(folder) / "wayback_20240928031215.csv"
            for path, opener, row in ((first, open, base), (second, gzip.open, dict(base, DBA="New Name", **{"RECORD DATE": "09/27/2024"}))):
                with opener(path, "wt", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerows([row, row])
            events, coverage = collect_ledger([candidate], [first, second])
            self.assertEqual(len(events), 2)
            self.assertEqual(len(coverage), 2)
            self.assertTrue(all(r["duplicate_violation_rows"] == 2 for r in events))
            self.assertEqual({r["event_role"] for r in events}, {"cross_capture_identity_drift_review", "identity_conflict"})
            self.assertEqual(summarize([candidate], events)[0]["unique_dated_operating_events"], 0)


if __name__ == "__main__":
    unittest.main()
