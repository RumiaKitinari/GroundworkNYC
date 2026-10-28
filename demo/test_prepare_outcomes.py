import tempfile
import unittest
from pathlib import Path

from prepare_outcomes import build_candidates
from refresh_integrated import write_csv


class OutcomePreparationTests(unittest.TestCase):
    def test_inspection_gap_and_closure_order_remain_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, current = root / "raw.csv", root / "current.csv"
            write_csv(raw, [
                {"camis": "1", "inspection_date": "2021-01-01T00:00:00", "action": "Establishment Closed by DOHMH"},
                {"camis": "1", "inspection_date": "2022-01-01T00:00:00", "action": "Reopened"},
                {"camis": "2", "inspection_date": "2020-01-01T00:00:00", "action": "No violations"},
            ], ("camis", "inspection_date", "action"))
            write_csv(current, [{"camis": "1", "geoid": "36061000100", "dba": "One", "building": "1", "street": "Main"},
                                {"camis": "2", "geoid": "36061000200", "dba": "Two", "building": "2", "street": "Main"}],
                      ("camis", "geoid", "dba", "building", "street"))
            rows = build_candidates(raw, current)
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0]["closure_order_seen"])
            self.assertEqual(rows[0]["last_inspection_on"], "2022-01-01")
            self.assertEqual(rows[1]["verification_status"], "independent_verification_required")
            self.assertNotIn("outcome_status", rows[0])


if __name__ == "__main__":
    unittest.main()
