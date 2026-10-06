# Dataset aggregate summary (derived; no participant file names)

Derived from `data/audit/dataset_inventory_summary.md` (sha256 `2d989e2b745bdfb8...`) by `scripts/derive_aggregate_summary.py`. Not produced from raw data.

## Observed facts
- 3502 files; extensions {'.csv': 48, '.jpg': 3454}; 3454 image files (never opened).
- 45 participant CSV files: total 687580 rows; per-file rows min/median/max = 5655/14805/18735.
- Column counts differ across participant files: {13: 2, 14: 32, 15: 11}.
- 7 files have fewer than 14,400 rows (10 days at one row per minute).
- Row counts divisible by 5: 45/45; by 15: 44/45 (structural; cause not established).
- Other tables (dimensions only): bio.csv 45x24; gut_health_test.csv 47x23; microbes.csv 45x1980.

## Unresolved
- Which columns differ between participant files (only the column COUNTS are recorded here).
- Why every participant row count is divisible by 5 and nearly all by 15 (structural fact; cause not established).
- Meal-row meaning, native versus interpolated CGM readings: see docs/data_validity_rules.md.
