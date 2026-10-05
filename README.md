# GlycoTwin

A personalized metabolic **Digital Twin** research prototype for the Digital Twin Challenge 2026.

> **Status: foundation + dataset-inventory tool only.** Nothing described under "Planned" is
> implemented or validated. No glucose forecasting, personalization, backend, or dashboard
> exists yet. This is a research prototype, not a diagnostic system — it must not be used
> to give medical advice, treatment recommendations, or medication/insulin guidance.

## Research motivation
Investigate glucose forecasting for free-living, non-insulin-managed prediabetes and type 2
diabetes by combining clinical information, continuous glucose monitoring (CGM), meal records,
and wearable activity/heart-rate signals (CGMacros dataset).

## Intended scope (planned)
- Dataset audit and research decisions (first)
- ML prediction engine and personalized response parameters
- Continuously updated Digital Twin state
- FastAPI backend, SQLite persistence, React dashboard

These are goals, not validated capabilities. Scientific assumptions (targets, horizons,
preprocessing) are deliberately deferred until the data audit is complete.

## Repository structure
```
src/glycotwin/config.py        dataset path configuration (implemented)
src/glycotwin/data/inventory.py  read-only file/schema inventory logic (implemented)
scripts/audit_dataset.py       CLI: runs the inventory against a configured dataset root
tests/                         config + inventory tests (synthetic fixtures only)
data/raw|interim|processed     local only, git-ignored
data/interim/audit_local/      full local inventory report (real paths); git-ignored
data/audit/                    aggregate, redacted inventory summary (tracked)
notebooks/ reports/ docs/      placeholders (.gitkeep)
```
`twin/` and `models/` subpackages will be added when they have content.

### What `scripts/audit_dataset.py` does today
Given a dataset root, it **read-only** inventories the directory tree: file counts/sizes by
extension, CSV/TSV/Parquet column names + dtypes + missingness, a name-based (not semantic)
flag for likely timestamp columns, an image file count (files are never opened), and detected
documentation/metadata files. It writes two reports:
- `data/audit/dataset_inventory_summary.{json,md}` — aggregate facts only, with any
  participant-like folder name replaced by `<participant_id>`. A *candidate* for eventually
  committing to Git — review it yourself first; nothing here is automatically guaranteed safe.
- `data/interim/audit_local/full_inventory.json` — the same data unredacted, with real file
  paths, for local debugging. Always git-ignored, never committed.

It never modifies, renames, or deletes anything under the dataset root, never prints
row-level values, and never assumes what a column or folder means beyond that naming
heuristic — real semantics must come from CGMacros's own documentation.

## Environment setup
Requires Python >= 3.10.
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

## Local dataset configuration
Keep CGMacros outside Git. Point the project at it:
```bash
cp .env.example .env               # then edit GLYCOTWIN_DATA_ROOT
export GLYCOTWIN_DATA_ROOT=/path/to/CGMacros
```
The code reads the **environment variable** (it does not auto-load `.env`; export it or use
your shell/IDE's env-file support). If unset or invalid, scripts fail with a clear message.

## Current stage and milestones
1. [done] Project scaffolding and path configuration
2. [done] Read-only dataset inventory tool (file/schema/missingness facts; built and tested
   against synthetic fixtures only — not yet run against the real CGMacros dataset)
3. [next] Run the inventory against the real dataset and review its output; then make
   research decisions (targets, horizons, splits) from what it actually shows
4. Baseline models, then personalization / twin state
5. Backend and dashboard

## Data privacy and licensing
- Raw data, participant-level files, and meal photos must never be committed.
- CGMacros dates are privacy-shifted; this project never attempts to recover true dates.
- Follow the CGMacros dataset license and terms; cite it appropriately.
- Only the redacted, aggregate `data/audit/dataset_inventory_summary.*` is ever a candidate
  for committing — and only after you review it yourself. It is not automatically safe
  just because the tool redacts known participant-folder patterns.
- Never send raw participant records or images to an external service.

## Verify
```bash
pytest
python scripts/audit_dataset.py --data-root /path/to/CGMacros
```
