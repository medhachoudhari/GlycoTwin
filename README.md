# GlycoTwin

A personalized metabolic **Digital Twin** research prototype for the Digital Twin Challenge 2026,
built on the CGMacros dataset. Specification: `GlycoTwin-Master-Blueprint.pdf`.

> **Research proof of concept. Not a diagnostic or treatment tool.** It gives no medical advice and
> makes no insulin, medication or diet recommendations. Nothing here is clinically validated.

> **Current stage (see `docs/PROJECT_STATUS.md` for the evidence-based tracker):** data-validity
> foundation and research core, tested on **synthetic fixtures only**. No experiment has been run and
> no model result exists. The real CGMacros data have been inventoried (aggregate facts in
> `data/audit/dataset_aggregate_summary.md`) but the event, leakage and CGM-interpolation checks have not
> yet been run on them. No backend, database or dashboard exists yet.

## Research question
Does conditioning a personalised carbohydrate-sensitivity estimate on recent activity improve the
calibration of 2-hour post-meal glucose-threshold forecasts, compared with an otherwise identical
personalised model without the activity term, in free-living adults not on insulin? The answer may be
negative or inconclusive; that would be reported as such.

## What exists today

| Area | Implemented (tests pass on synthetic data) | Not yet |
|---|---|---|
| Data layer | Config, read-only inventory, meal extraction with gap checks, overlap flags and an exclusion log, past-only baseline, activity and trend features, outcome/label, event table, event-count and schema reports, leakage mutation test | Real-data runs, `bio.csv`, HR deviation |
| Research core | Models A/B/C, closed-form Bayesian update, uncertainty, calibration metrics, chronological split with purging, versioned in-memory twin | Participant CV, calibration plots, the key experiment |
| Product | none | SQLite, FastAPI, replay, React dashboard |

Open scientific questions and every decision are in `docs/data_validity_rules.md`; model assumptions in
`docs/modelling_assumptions.md`.

## Repository layout
```
src/glycotwin/config.py          dataset path configuration
src/glycotwin/data/inventory.py  read-only inventory (redacts participant folder AND file names)
src/glycotwin/data/meals.py      loading and meal extraction (gaps, overlaps, exclusion log)
src/glycotwin/data/events.py     features, outcomes, eligibility, event table, count reports
src/glycotwin/data/leakage_check.py  the blueprint's leakage test over real pipeline code
src/glycotwin/features.py        event schema validation, leakage-safe chronological split
src/glycotwin/models/            baseline.py (A), bayesian.py (B/C), evaluation.py, experiment.py (harness)
src/glycotwin/twin/state.py      versioned TwinState, forecast/reconcile
scripts/build_event_table.py     one command: event counts, exclusions, schema groups (aggregate output)
scripts/check_leakage_on_data.py the leakage unit test on real participant files
scripts/run_experiment.py        prequential A/B/C experiment with controls, clustered CIs, manifest
scripts/audit_cgm_sampling_phase.py   second-difference test of CGM sampling structure
scripts/audit_meal_event_semantics.py meal-row semantics probes
scripts/audit_meal_photo_pairing.py   meal row vs image rows: can a meal end be reconstructed? (read-only, aggregate)
scripts/run_model_c.py                Model C (activity-conditioned, rise = (beta+gamma*activity)*carbs; real run pending)
scripts/run_model_b.py                Model B (personalised Bayesian, rise = beta*carbs, sequential; real run pending review)
scripts/run_model_a.py                Model A (population XGBoost) participant-level stratified 5-fold out-of-fold evaluation
scripts/audit_bio_groups.py           bio.csv glycaemic groups and participant mapping (read-only, aggregate)
scripts/compare_cgm_channels.py       Libre vs Dexcom on identical meal events (channel reconciliation, not sensor validation)
scripts/audit_dataset.py, audit_meal_events.py, audit_cgm_interpolation.py   earlier audits (kept)
scripts/derive_aggregate_summary.py   redacted aggregate summary from the committed inventory
data/raw|interim|processed       local only, git-ignored
data/audit/                      aggregate summaries only
docs/                            PROJECT_STATUS.md, data_validity_rules.md, modelling_assumptions.md
tests/                           synthetic fixtures only; never real data
```

## Setup (Windows PowerShell)
Requires Python >= 3.10.
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
pytest
```
`requirements.txt` and `pyproject.toml` are kept in sync by `tests/test_project_config.py`.

## Running on the real dataset
Keep CGMacros outside Git and point to it (no default path is assumed):
```powershell
$env:GLYCOTWIN_DATA_ROOT = "C:\path\to\CGMacros"
python scripts\build_event_table.py          # counts, exclusions, schema groups; table goes to data\processed (ignored)
python scripts\check_leakage_on_data.py      # blueprint leakage test, one meal per participant
python scripts\audit_cgm_sampling_phase.py   # can sampling structure be inferred? (pilot: 5 participants)
python scripts\run_experiment.py            # A vs B vs C + controls; refuses to run on underpowered data
```
All printed output is aggregate-only (counts, reason names, column names, anonymous labels). Skim it
before sharing it. The participant-level event table stays local.

## Data privacy and licensing
- Raw data, participant-level files, event tables and meal photos are never committed (`.gitignore` blocks
  CSV/Parquet/images repo-wide; `data/raw`, `data/interim`, `data/processed` are ignored).
- CGMacros dates are privacy-shifted; this project never tries to recover true dates.
- The dataset is licensed CC BY-NC-SA 4.0 (per the blueprint); follow its terms and cite it.
- Only aggregate, redacted summaries belong in `data/audit/`. Nothing is "automatically safe": review them.
- Never send raw participant records or images to an external service.

## Limitations (current)
Synthetic tests prove code logic, not scientific validity. Native versus interpolated CGM readings are
not distinguishable from the released files by any documented flag; the blueprint's native-timestamp
plan may not be possible and a conservative lag guard is used instead. Meal-row semantics, event counts
and the Bayesian model's Gaussian assumptions are unverified on real data.
