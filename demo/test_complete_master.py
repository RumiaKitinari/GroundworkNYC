import unittest

from complete_master import allocate_zone_counts, geographic_rent_predictions, rent_estimates, zip722_index


class CompletionTests(unittest.TestCase):
    def test_zip_counts_do_not_sum_nested_industries(self):
        result = zip722_index([{"zip": "10001", "naics": "722///", "est": "100"},
                               {"zip": "10001", "naics": "722511", "est": "40"}])
        self.assertEqual(result["10001"], 100)
    def test_zone_totals_are_allocated_not_repeated(self):
        links = [{"geoid": "a", "location_id": "1", "taxi_zone_area_share": ".25"},
                 {"geoid": "b", "location_id": "1", "taxi_zone_area_share": ".75"}]
        totals, expected = allocate_zone_counts(links, {"1": {"dropoffs": 100, "evening": 20}}, {"a", "b"})
        self.assertEqual(totals["a"]["dropoffs"], 25)
        self.assertEqual(totals["b"]["dropoffs"], 75)
        self.assertEqual(expected["dropoffs"], 100)
        links[1]["taxi_zone_area_share"] = "1"
        with self.assertRaisesRegex(ValueError, "more than one"):
            allocate_zone_counts(links, {"1": {"dropoffs": 100}}, {"a", "b"})

    def test_rent_predictions_use_only_passed_donors(self):
        train = [{"borough": "Queens", "reported_median_monthly_rent_psf": "3",
                  "centroid_latitude": "40.7", "centroid_longitude": "-73.9"}]
        query = {**train[0], "reported_median_monthly_rent_psf": "999"}
        for method in ("borough_median", "local_log_idw_5"):
            self.assertAlmostEqual(geographic_rent_predictions(train, [query], method)[0], 3)

    def test_rent_validation_keeps_observed_values_separate(self):
        rows = [{"geoid": str(i), "nta_code": str(i // 2), "borough": "Queens",
                 "reported_median_monthly_rent_psf": "3", "centroid_latitude": str(40.7+i*.001),
                 "centroid_longitude": "-73.9"} for i in range(12)]
        rows[-1]["reported_median_monthly_rent_psf"] = ""
        estimates, report = rent_estimates(rows)
        self.assertEqual(set(estimates), {"11"})
        self.assertEqual(rows[-1]["reported_median_monthly_rent_psf"], "")
        self.assertEqual(report["validation"]["borough_median"]["held_out_rows"], 11)


if __name__ == "__main__":
    unittest.main()
