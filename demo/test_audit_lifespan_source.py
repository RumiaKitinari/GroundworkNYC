import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from audit_lifespan_source import audit_lifespans


class LifespanArchiveAuditTests(unittest.TestCase):
    def test_snapshot_exit_is_not_a_verified_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "restaurant_lifespans.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=("camis", "open_date", "survival_lower_years",
                                                            "survival_upper_years", "clean_cohort"))
                writer.writeheader()
                writer.writerow({"camis": "1", "open_date": "2021-01-01", "survival_lower_years": "0.2",
                                 "survival_upper_years": "0.8", "clean_cohort": "true"})
                writer.writerow({"camis": "2", "open_date": "2021-01-01", "survival_lower_years": "1.5",
                                 "survival_upper_years": "inf", "clean_cohort": "true"})
            audit = audit_lifespans(path, date(2026, 10, 20))
            self.assertFalse(audit["training_eligible"])
            self.assertEqual(audit["counts"]["snapshot_inferred_exit_within_year"], 1)
            self.assertEqual(audit["counts"]["right_censored_rows"], 1)

    def test_invalid_and_duplicate_rows_are_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "restaurant_lifespans.csv"
            path.write_text("camis,open_date,survival_lower_years,survival_upper_years,clean_cohort\n"
                            "1,2021-01-01,2,1,true\n1,2099-01-01,0,inf,true\n")
            counts = audit_lifespans(path, date(2026, 10, 20))["counts"]
            self.assertEqual(counts["invalid_interval"], 1)
            self.assertEqual(counts["invalid_open_date"], 1)
            self.assertEqual(counts["duplicate_camis"], 1)

    def test_required_schema_is_enforced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "restaurant_lifespans.csv"
            path.write_text("camis,open_date\n1,2021-01-01\n")
            with self.assertRaisesRegex(ValueError, "missing columns"):
                audit_lifespans(path)


if __name__ == "__main__":
    unittest.main()
