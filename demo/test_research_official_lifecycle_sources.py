import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_official_lifecycle_sources import REQUIRED_FIELDS, attach_references, fetch_source


class OfficialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.case = {"business_id": "1", "candidate_name": "Test Cafe", "candidate_address": "10 MAIN ST 10001", "borough": "Manhattan"}
        self.opening = {"establishment_record_dba": "Test Cafe", "establishment_record_establishment_street": "10 Main Street",
                        "establishment_record_establishment_zip": "10001", "establishment_record_establishment_borough": "Manhattan",
                        "establishment_record_actual_opening_date": "2015-02-03T00:00:00"}

    def test_earlier_opening_conflicts_retained_without_creating_labels(self):
        second = dict(self.opening, establishment_record_actual_opening_date="2016-02-03T00:00:00")
        row = attach_references([self.case], [self.opening, second], [], [])[0]
        self.assertTrue(row["sbs_conflicting_opening_dates"])
        self.assertEqual(row["sbs_reported_opening_dates"], "2015-02-03;2016-02-03")
        self.assertFalse(row["training_eligible"])

    def test_eviction_is_address_only_and_application_requires_address(self):
        eviction = {"eviction_address": "10 Main St", "eviction_zip": "10001", "borough": "MANHATTAN",
                    "residential_commercial_ind": "Commercial", "executed_date": "2024-03-25"}
        application = {"food_service_establishment": "1", "bulding_number": "99", "street": "Main Street",
                       "zip": "10001", "borough": "Manhattan", "legal_business_name": "Different site LLC"}
        row = attach_references([self.case], [], [application], [eviction])[0]
        self.assertEqual(row["commercial_executions_at_address"], 1)
        self.assertEqual(row["outdoor_same_camis_rows"], 1)
        self.assertEqual(row["outdoor_same_camis_address_rows"], 0)
        self.assertEqual(row["outdoor_reported_legal_names"], "")
        self.assertFalse(row["training_eligible"])

    def test_wrong_name_or_zip_does_not_match(self):
        for changes in ({"establishment_record_dba": "Different Cafe"}, {"establishment_record_establishment_zip": "10002"}):
            row = attach_references([self.case], [dict(self.opening, **changes)], [], [])[0]
            self.assertEqual(row["sbs_exact_identity_rows"], 0)

    def test_rejects_residential_rows_and_duplicate_candidates(self):
        with self.assertRaises(ValueError):
            attach_references([self.case], [], [], [{"residential_commercial_ind": "Residential"}])
        with self.assertRaises(ValueError):
            attach_references([self.case, self.case], [], [], [])

    def test_full_export_count_and_stable_revision_required(self):
        fields = sorted(REQUIRED_FIELDS["sbs_openings"])
        payload = (",".join(fields) + "\n" + ",".join("x" for _ in fields) + "\n").encode()
        spec = {"id": "test", "where": "", "minimum_rows": 1}
        def encoded(value):
            return io.BytesIO(json.dumps(value).encode())
        for final_revision, final_count, valid in ((1, 1, True), (2, 1, False), (1, 2, False)):
            responses = [encoded({"rowsUpdatedAt": 1}), encoded([{"n": "1"}]), io.BytesIO(payload),
                         encoded({"rowsUpdatedAt": final_revision}), encoded([{"n": str(final_count)}])]
            with self.subTest(revision=final_revision, count=final_count), tempfile.TemporaryDirectory() as folder:
                with patch("research_official_lifecycle_sources.request", side_effect=responses):
                    if valid:
                        result = fetch_source(spec, Path(folder), "sbs_openings")
                        self.assertEqual(result["rows"], 1)
                        self.assertFalse(result["sampling"])
                    else:
                        with self.assertRaises(ValueError):
                            fetch_source(spec, Path(folder), "sbs_openings")


if __name__ == "__main__":
    unittest.main()
