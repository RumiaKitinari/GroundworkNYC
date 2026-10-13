# Quick backend data test

**Result: 5 tests passed using 20 provisional records recovered from the uploaded data.**

| Check | Result |
| --- | --- |
| Backend source-record validation | 20 records accepted; 20 unique block-group identifiers |
| NYC geography | 20 valid polygons; all recovered sample identifiers belong to Queens |
| Numeric source fields | Walkability and accessibility values are finite; population and job counts are nonnegative |
| H3 indexing | All sampled locations map to valid cells at resolutions 7, 8 and 9; 19 distinct resolution-8 cells |
| API behavior | Liveness returns 200; readiness and prediction requests correctly return 503 without a configured spatial database |

The sample's walkability index ranges from **9.67 to 18.67**, with a mean of **14.42** on the original index scale. This is a small recovery sample, not a representative Queens or NYC estimate.

## Upload problem

The outer ZIP contains a file named `Walkability  Accessibility.csv`. Its contents are a ZIP with an EPA Smart Location Database geodatabase, rather than CSV text. The inner ZIP has no readable central directory and ends inside its main compressed feature table. That table is missing at least 62,747,317 compressed bytes. The outer ZIP was readable; the nested archive was incomplete.

Forty-one complete embedded files were recovered and passed their ZIP CRC checks. The main feature table was only partially recovered and cannot pass a whole-file integrity check. GDAL warned that its missing table index required guessing feature locations, which may return incorrect results. Twenty structurally plausible Queens records were selected, their polygons transformed to WGS84, and their attributes converted through the backend's existing normalizer. The tests confirm this sample's structure and compatibility; they cannot establish full source integrity.

No PostgreSQL import, trained prediction, complete dashboard or production readiness is claimed. The upload supplies only this walkability/accessibility source, not the other datasets or pretrained model.

## Repeat the quick test

From `GroundworkNYC/backend`, using the backend's Python environment:

```bash
python -m pytest -q tests/test_supplied_walkability.py
```

The normalized recovery sample is included at `data/samples/walkability-smoke.jsonl`. It is explicitly marked `provisional_from_truncated_archive`; the test intentionally retains that warning. The source's block-group identifiers are from its `GEOID10` field. `observed_at` records the import/test date, not the date its demographic or mobility measurements were collected.

A complete original CSV or EPA geodatabase archive is needed for a reliable full import. The [GDAL OpenFileGDB documentation](https://gdal.org/en/stable/drivers/vector/openfilegdb.html) describes the reader used for the recovery attempt.
