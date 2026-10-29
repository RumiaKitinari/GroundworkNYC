# Single-Hex Resolution Study

This study compares H3 resolutions 8, 9, and 10 against the five NYC counties' official 2020 Census tabulation-block polygons. It tests geographic granularity and coverage, not demand-model accuracy. The repeatable code is `audit_hex_resolution.py`; the full local output is `data/evaluation/reports/hex_resolution_20261005.json`.

| H3 resolution | Typical hex area | Median blocks materially overlapping a hex, by borough | Blocks split across two or more hexes, by borough |
| --- | ---: | ---: | ---: |
| 8 | 737,328 m2 | 25-53 | 26-31% |
| 9 | 105,333 m2 | 6-11 | 58-66% |
| 10 | 15,048 m2 | 1-3 | 93-96% |

Material overlap means at least 5% of a block polygon lies in a cell. Cells in the distribution have at least 10% estimated land coverage. Exact polygon intersections cover 100% of the 37,380 land-bearing census blocks across the five counties at all three tested resolutions. The current eligible-tract grid covers 99.695% of its tract area at resolution 8 and 99.813% at resolution 9; that grid excludes Staten Island and tracts ineligible for screening.

Resolution 9 is the next live map depth at zoom 14 and above. It gives a more useful street-scale display without the very high block fragmentation of resolution 10. The existing resolution-7 sector and resolution-8 cell views remain at lower zoom. Resolution 10 remains an offline experiment until finer-grain demand inputs or a defensible site-level model exist. A finer polygon must not be described as a finer measured demand observation: most current model inputs are tract-level and are interpolated into the hexes.

The block files include land area but not population or restaurant outcomes. Land area is allocated proportionally across each block polygon to approximate cell land share; mixed land/water blocks can distort that estimate. Census blocks are not identical to physical street blocks, and block counts alone do not tell us how many potential customers are present. A later double-hex experiment should be compared with this single-grid baseline on spatial coverage, boundary artifacts, ranking stability, and computational cost before it affects recommendations.
