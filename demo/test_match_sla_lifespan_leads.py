import csv
import tempfile
import unittest
from pathlib import Path

from match_sla_lifespan_leads import attach_leads, normalized_address


def write_rows(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class SlaLifespanLeadsTests(unittest.TestCase):
    def test_address_aliases_and_inactive_license_stay_unresolved(self):
        self.assertEqual(normalized_address("114 EAST 25 STREET", "10010"),
                         normalized_address("114 E 25TH ST", "10010"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            queue, active, inactive = (root / name for name in ("queue.csv", "active.csv", "inactive.csv"))
            write_rows(queue, ("business_id", "candidate_name", "candidate_address", "borough",
                               "first_operational_prepermit", "verification_status", "outcome_status"),
                       [{"business_id": "1", "candidate_name": "Vested", "candidate_address": "114 EAST 25 STREET 10010",
                         "borough": "Manhattan", "first_operational_prepermit": "2024-01-01",
                         "verification_status": "independent_verification_required", "outcome_status": "unresolved"}])
            write_rows(active, ("licensepermitid", "premisescounty", "actualaddressofpremises", "zipcode",
                                "originalissuedate", "expirationdate", "dba", "legalname", "description"),
                       [{"licensepermitid": "new", "premisescounty": "New York",
                         "actualaddressofpremises": "114 E 25TH ST", "zipcode": "10010",
                         "originalissuedate": "2025-02-01", "expirationdate": "2027-01-01",
                         "dba": "Vested", "legalname": "Vested LLC", "description": "Restaurant"}])
            write_rows(inactive, ("license_permit_id", "premises_county", "actual_address_of_premises",
                                  "zip_code", "original_issue_date", "expiration_date", "dba", "legalname",
                                  "description"),
                       [{"license_permit_id": "old", "premises_county": "New York",
                         "actual_address_of_premises": "114 E 25TH ST", "zip_code": "10010",
                         "original_issue_date": "2024-02-01", "expiration_date": "2026-09-30",
                         "dba": "Vested", "legalname": "Vested LLC", "description": "Restaurant"}])
            rows, _, summary = attach_leads(queue, active, inactive)
            self.assertEqual(summary["match_status_counts"], {"both_active_and_inactive_license_leads": 1})
            self.assertEqual(rows[0]["outcome_status"], "unresolved")
            self.assertEqual(rows[0]["sla_active_ids"], "new")
            self.assertEqual(rows[0]["sla_inactive_ids"], "old")
            self.assertIn("license_permit_id", rows[0]["sla_inactive_source_url"])


if __name__ == "__main__":
    unittest.main()
