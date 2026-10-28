import csv
import tempfile
import unittest
from pathlib import Path

from prepare_survival_evidence import build_packet


class SurvivalEvidencePacketTests(unittest.TestCase):
    def write_csv(self, path, fields, rows):
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_dated_matches_remain_review_leads(self):
        with tempfile.TemporaryDirectory() as folder:
            review = Path(folder) / "review.csv"
            inspections = Path(folder) / "inspections.csv"
            fields = ["business_id", "borough", "candidate_name", "candidate_address",
                      "candidate_baseline_on", "verification_status", "outcome_status"]
            cases = [
                dict(zip(fields, [f"case-{name}", "Manhattan", f"Cafe {name}", address,
                                  "2023-12-20", "independent_verification_required", "unresolved"]))
                for name, address in [("A", "10 West Main Street"), ("B", "20 Broadway"),
                                      ("C", "30 Park Avenue"), ("D", "40 Broadway")]
            ]
            self.write_csv(review, fields, cases)
            raw_fields = ["camis", "dba", "boro", "building", "street", "inspection_date",
                          "action", "record_date"]

            def inspection(camis, name, building, street, when, action="No violations were recorded"):
                return dict(zip(raw_fields, [camis, name, "Manhattan", building, street, when,
                                             action, "2026-10-16T06:00:00.000"]))

            self.write_csv(inspections, raw_fields, [
                inspection("100", "Cafe A", "10", "W MAIN ST", "2023-12-21"),
                inspection("100", "Cafe A", "10", "W MAIN ST", "2023-12-21"),
                inspection("100", "Cafe A", "10", "W MAIN ST", "2024-12-21"),
                inspection("200", "Cafe C", "30", "PARK AVE", "2023-12-19"),
                inspection("201", "Cafe C", "30", "PARK AVE", "2023-12-18"),
                inspection("300", "Cafe D", "40", "BROADWAY", "2023-12-20",
                           "Establishment Closed by DOHMH"),
                inspection("300", "Cafe D", "40", "BROADWAY", "2024-12-21"),
            ])
            rows, output_fields, counts = build_packet(review, inspections)
            self.assertEqual(len(output_fields), len(fields) + 6)
            self.assertEqual(rows[0]["inspection_match_status"], "exact_match_possible_operating_pair")
            self.assertEqual(rows[0]["inspection_baseline_lead"], "2023-12-21")
            self.assertEqual(rows[0]["inspection_followup_lead"], "2024-12-21")
            self.assertIn("camis=100", rows[0]["inspection_source_url"])
            self.assertEqual(rows[1]["inspection_match_status"], "no_exact_match")
            self.assertEqual(rows[1]["inspection_record_date"], "")
            self.assertEqual(rows[2]["inspection_match_status"], "ambiguous_multiple_camis")
            self.assertEqual(rows[3]["inspection_match_status"], "exact_match_no_baseline_inspection")
            self.assertEqual(counts["exact_match_possible_operating_pair"], 1)
            self.assertTrue(all(row["verification_status"] == "independent_verification_required"
                                and row["outcome_status"] == "unresolved" for row in rows))

    def test_adjudicated_queue_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            review = Path(folder) / "review.csv"
            inspections = Path(folder) / "inspections.csv"
            fields = ["business_id", "borough", "candidate_name", "candidate_address",
                      "candidate_baseline_on", "verification_status", "outcome_status"]
            self.write_csv(inspections, ["camis", "dba", "boro", "building", "street",
                                         "inspection_date", "action", "record_date"], [])
            for verification, outcome in (("independently_verified", "verified_operating"),
                                          ("unknown_status", "unresolved")):
                with self.subTest(verification=verification):
                    self.write_csv(review, fields, [dict(zip(fields, ["case-1", "Bronx", "Cafe A",
                                                               "1 Main St", "2023-12-20",
                                                               verification, outcome]))])
                    with self.assertRaisesRegex(ValueError, "untouched unresolved"):
                        build_packet(review, inspections)


if __name__ == "__main__":
    unittest.main()
