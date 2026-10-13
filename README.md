# GlycoTwin

A personalized metabolic **Digital Twin** research prototype for the Digital Twin Challenge 2026,
built on the CGMacros dataset. Specification: `GlycoTwin-Master-Blueprint.pdf` (the project's internal
design brief; referenced throughout `docs/` but **not included in this public repository**).

> **Research proof of concept. Not a diagnostic or treatment tool.** It gives no medical advice and
> makes no insulin, medication or diet recommendations. Nothing here is clinically validated.

> **Current stage (see `docs/PROJECT_STATUS.md` for the evidence-based tracker):** three different things
> are true at once, and should not be conflated:
> 1. **Code logic** (event extraction, leakage checks, the Bayesian update) is unit-tested on **synthetic
>    fixtures only** — those tests prove the code runs correctly, not that any scientific claim is true.
> 2. **A real-data retrospective research result does exist.** The real CGMacros data were inventoried
>    (aggregate facts in `data/audit/dataset_aggregate_summary.md`), run through the event/leakage
>    pipeline, and evaluated: **963 activity-eligible meals across 34 participants**, Libre/Dexcom channel
>    reconciled, comparing Model B against Model C. The result was **inconclusive** for the
>    activity-conditioning hypothesis (most paired metric intervals include zero — see
>    `docs/model_b_vs_c_report.md` for the full numbers and `demo/evidence_map.md` for where every figure
>    used in the demo video and presentation traces back to). This is retrospective **research evidence**,
>    not a claim that the hypothesis is confirmed, and not clinical validation.
> 3. **The live application** (FastAPI + SQLite backend with accounts/sessions/per-user twin ownership,
>    and the React dashboard — see "Run the website" below) runs the same Bayesian engine in real time, but
>    a live twin's prior comes from a synthetic demo population or an aggregate prior artifact, not from
>    the retrospective CGMacros run directly. The application working end-to-end is a **functionality**
>    claim; it is separate from the retrospective research result in (2) and from clinical validation,
>    neither of which it constitutes. **Nothing in this project is clinically validated.**

## Digital Twin Challenge 2026 submission

| | |
|---|---|
| **Project title** | GlycoTwin — Personalized Post-Meal Glucose Digital Twin |
| **Team** | NeuralForge (solo participant) |
| **Team member** | Medha Choudhari — third-year B.E./B.Tech Computer Science and Engineering student |
| **College / university** | Bapuji Institute of Engineering and Technology (BIET), Davangere, Karnataka, India |
| **Incubator** | *[Pending confirmation — not yet provided]* |
| **Demo video (15–20 min)** | *[Unlisted YouTube link — pending; the finished 15:34 video is at `demo/video/GlycoTwin_demo_subtitled.mp4`, not yet uploaded to YouTube]* |
| **Architecture diagram** | [`docs/submission/GlycoTwin_Architecture.pdf`](docs/submission/GlycoTwin_Architecture.pdf) (editable: [`.pptx`](docs/submission/GlycoTwin_Architecture.pptx)) |
| **Project presentation** | [`docs/submission/GlycoTwin_Presentation.pdf`](docs/submission/GlycoTwin_Presentation.pdf) (editable: [`.pptx`](docs/submission/GlycoTwin_Presentation.pptx)) |
| **License** | MIT (code) — see [`LICENSE`](LICENSE); prepared, pending your final confirmation before commit. CGMacros dataset remains under its own CC BY-NC-SA 4.0 terms (see "License" below). |

### Problem statement
After the same meal, two people can show very different post-meal glucose responses — age, body
composition, recent activity and individual metabolism all matter. Most glucose-forecasting tools give one
population-average prediction and discard it: they do not remember the person, do not report how
confident they are, and do not improve as more is learned about that individual.

### Healthcare use case
A research and self-monitoring context: an individual (or a researcher studying a cohort) wearing a
continuous glucose monitor who wants to understand how their own glucose responds to specific meals and
activity. **Not** a clinical decision-support tool: GlycoTwin makes no diagnosis, gives no insulin-dosing,
medication or diet advice, and every page of the application and every submission document says so.

### Proposed solution and key innovative features
A persistent, versioned Digital Twin that runs a **forecast → observe → update** loop: it forecasts the
probability and a 90% interval for the 2-hour post-meal glucose maximum with Models B and C (Bayesian,
personalised carbohydrate sensitivity, optionally activity-conditioned), waits for an eligible observed
outcome, and — only then — runs a closed-form Bayesian update that writes a new, numbered, auditable twin
version. See "Research question" and "What exists today" below for the implementation, and the
presentation (`docs/submission/GlycoTwin_Presentation.pdf`) for a guided walkthrough with real numbers from
a live run.

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
| Product | SQLite persistence, FastAPI API with accounts (register, sign in, sign out, guest), password hashing (scrypt), HttpOnly sessions and per-user twin ownership, React dashboard (landing page, sign in / create account, forecast, observations, history, insights) | Replay UI, password recovery, email verification, account deletion, guest cleanup, security audit, real-data validation |

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
src/glycotwin/twin/insight.py    twin insight, parameter history, what-if (in memory, read-only)
src/glycotwin/twin/replay.py     leakage-safe forecast -> reconcile -> update replay (in memory)
src/glycotwin/twin/demo.py       SYNTHETIC labelled demonstration (scripts/demo_twin_lifecycle.py)
src/glycotwin/twin/adapter.py    event table -> twin: leakage-safe prior (participant excluded), validated event feed
src/glycotwin/models/model_bc_compare.py  matched paired B-vs-C comparison (refuses unmatched inputs; scripts/compare_models_b_c.py)
src/glycotwin/models/reliability_svg.py   dependency-free reliability diagram (aggregate bins)
scripts/replay_participant.py    replay one participant through the in-memory twin (counts only on screen)
src/glycotwin/twin/state_view.py  the blueprint's formal TwinState composed from the store (unavailable parts listed, not invented)
src/glycotwin/twin/quality.py    forecast-time data-quality / insufficient-history warnings (flag only; probabilities and intervals are never altered)
src/glycotwin/models/activity_strata.py   per-participant active vs sedentary definition (docs/activity_definition.md)
src/glycotwin/models/blueprint_prior.py   opt-in blueprint-form prior: stratified beta, gamma centred at 0 (docs/blueprint_prior.md)
docs/BLUEPRINT_CONFORMANCE.md    every blueprint requirement vs code, with status and validation level; docs/ARCHITECTURE.md, docs/model_card.md
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
src/glycotwin/backend/           FastAPI + SQLite service: accounts (auth_service.py, security.py), ownership (ownership.py), routers/, services.py, store.py (docs/BACKEND.md)
frontend/                        React + Vite + TypeScript website (frontend/README.md); runs together with the backend
scripts/init_db.py               create tables (never drops data); --demo adds a SYNTHETIC twin that stays hidden until claimed
scripts/claim_twin.py            list unowned (old) twins and, deliberately and one-way, give one to an existing account
data/raw|interim|processed       local only, git-ignored
data/audit/                      aggregate summaries only
docs/                            PROJECT_STATUS.md, BACKEND.md, WEBSITE_TESTING_GUIDE.md, GLYCOTWIN_COMPLETE_TEST_REPORT.md, HOW_GLYCOTWIN_WORKS.md, data_validity_rules.md, modelling_assumptions.md
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

## Research backend (FastAPI + SQLite)
Experimental research API around the existing twin engine; not clinically validated, no diagnosis or treatment advice (every response says so).
Architecture, endpoints, accounts and ownership: `docs/BACKEND.md`. The database is a local SQLite file under `data\interim` (git-ignored); no other database service is needed.
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt; pip install -e .
# optional: choose the database file and the folder of aggregate prior artifacts (defaults shown)
$env:GLYCOTWIN_DATABASE_URL = "sqlite:///data/interim/glycotwin_backend.sqlite3"
$env:GLYCOTWIN_PRIOR_DIR    = "data\interim\priors"
python scripts\init_db.py --demo                          # create tables (never drops data) + a labelled SYNTHETIC demo twin (hidden until claimed)
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000     # then open http://127.0.0.1:8000/docs
pytest tests\test_backend.py tests\test_auth.py tests\test_ownership.py     # backend tests (synthetic data only, temporary databases)
```
Real participant data is never loaded automatically. A live twin's prior comes from the synthetic demo population or from an aggregate prior
artifact written offline: `python scripts\export_prior.py --event-table <local table> --name my_prior.json --live-person-not-in-population`
(or `--exclude-participant <id>` when the live person is part of the research data).

**Accounts and ownership (implemented).** Every twin route needs a signed-in session, and each twin belongs to exactly one account; another account gets the same
404 "twin not found" as for a twin that does not exist. Passwords are stored only as scrypt hashes; the session is an HttpOnly cookie whose token is stored only as a hash.
Twins created before accounts existed (or by `init_db.py --demo`) have no owner and are **hidden from everyone** until you claim one:
```powershell
python scripts\claim_twin.py --list-unowned
python scripts\claim_twin.py --twin-id <id> --email person@example.com            # dry run: shows what would happen
python scripts\claim_twin.py --twin-id <id> --email person@example.com --apply    # claim it (refused if it already has an owner)
```
**Back up the database file before the first start with the account-enabled code** (the upgrade only adds three tables, but a copy is the rollback).
Not implemented: password recovery, email verification, account deletion, guest-account cleanup, persistent rate limits (the counters reset on restart), per-user twin labels (labels stay globally unique).
Keep the backend bound to `127.0.0.1`; it has no TLS and has not been security-audited.

## Run the website (Windows PowerShell)
The website needs **both** programs running: the backend (port 8000) and the frontend (port 5173, which forwards `/api/...` to the backend). Use two PowerShell windows.
```powershell
# Window 1: project root (the folder with pyproject.toml). Optional: use a throw-away test database instead of your real one.
$env:GLYCOTWIN_DATABASE_URL = "sqlite:///" + ($env:TEMP -replace '\\','/') + "/glycotwin_test.sqlite3"
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000

# Window 2: the frontend folder
cd frontend
npm install
npm run dev          # open http://127.0.0.1:5173/
```
Then: **Create account** (`#/register`) or **Continue as demo** (a temporary guest account), create a twin in Settings, request a forecast, record the outcome, apply it, and sign out and in again to see your saved history.
Details and test cases: `frontend/README.md` and `docs/WEBSITE_TESTING_GUIDE.md`. Not yet tested by the authors on Windows (see `docs/GLYCOTWIN_COMPLETE_TEST_REPORT.md`).

## Technical stack and AI/ML framework
| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite 6 (`frontend/`) |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2, Uvicorn, SQLite (`src/glycotwin/backend/`) |
| Research / ML | pandas, NumPy, SciPy, scikit-learn, XGBoost (Model A baseline); hand-written closed-form Bayesian linear models (Models B and C — conjugate Normal prior/update, no external ML framework needed for a closed-form update); `src/glycotwin/models/`, `src/glycotwin/twin/` |
| Tests | pytest, httpx (815 Python tests; 37 frontend tests as of the last recorded run — see `docs/GLYCOTWIN_COMPLETE_TEST_REPORT.md`) |
| Dataset | CGMacros (PhysioNet / PSI-TAMU), CC BY-NC-SA 4.0, never committed to this repository |

## Data privacy and licensing
- Raw data, participant-level files, event tables and meal photos are never committed (`.gitignore` blocks
  CSV/Parquet/images repo-wide; `data/raw`, `data/interim`, `data/processed` are ignored).
- CGMacros dates are privacy-shifted; this project never tries to recover true dates.
- The dataset is licensed **CC BY-NC-SA 4.0** (per the blueprint); follow its terms, cite it, and never
  redistribute it or any participant-level derivative. This repository contains no dataset files.
- Only aggregate, redacted summaries belong in `data/audit/`. Nothing is "automatically safe": review them.
- Never send raw participant records or images to an external service.

## License
This repository's own code is released under the **MIT License** — see [`LICENSE`](LICENSE). A code license
is a separate decision from the dataset's license above: the dataset's CC BY-NC-SA 4.0 terms apply to
CGMacros itself regardless of what license the *code* in this repository carries, and the `LICENSE` file
covers only the code in this repository — it grants no rights to the CGMacros dataset, which is not
included here. MIT was chosen because it is short, permissive, and compatible with every dependency this
project uses (FastAPI, Pydantic, SQLAlchemy, Uvicorn, pandas, NumPy, SciPy, scikit-learn, XGBoost, React,
Vite, pytest, httpx — all BSD-3, Apache-2.0, or MIT; none are copyleft, so none restrict how this
repository's own code may be licensed). `LICENSE` is prepared and ready, pending your final confirmation
before it is committed.

## Demo video
15:34, English narration, burned-in subtitles, chapter markers; opens on the real landing page and walks
through account creation, the forecast → observe → update loop, uncertainty, Bayesian personalization,
explainability, persistence, and the research evidence. **Not yet uploaded to YouTube** — the finished file
is `demo/video/GlycoTwin_demo_subtitled.mp4` (68 MB) / `demo/video/GlycoTwin_demo_subtitled_compact.mp4`
(41 MB); see `demo/README.md` for the full breakdown and upload steps. Once uploaded as an **unlisted**
YouTube video, put the link in the table above and here.

## Limitations (current)
Synthetic tests prove code logic, not scientific validity. Native versus interpolated CGM readings are
not distinguishable from the released files by any documented flag; the blueprint's native-timestamp
plan may not be possible and a conservative lag guard is used instead. Meal-row semantics, event counts
and the Bayesian model's Gaussian assumptions are unverified on real data. The website's account system is covered by automated tests only: no external security review, no Windows or real-device testing.
