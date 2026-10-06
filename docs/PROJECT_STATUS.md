# GlycoTwin project status

Research proof of concept. **Not a diagnostic or treatment tool**; it gives no medical advice and no
insulin, medication or diet recommendations. Specification: `GlycoTwin-Master-Blueprint.pdf` (38 pages).
This file is the single tracker; it is updated after every implementation phase.

## 1. Current checkpoint

| Item | Value |
|---|---|
| Branch | `claude/glycotwin-initial-scaffold-gegpzd` |
| Stable baseline (GitHub) | `b570d9a` (kept as an ancestor of everything below; tagged/bundled, see section 6) |
| Local commits on top of it (not pushed) | `068536c` research core, `cd57f0f` renamed audit scripts, plus the Phase 1 commits listed in section 2 |
| Automated tests | **133 passed** in one full run at the time of writing (`python -m pytest -q`). One earlier unexplained failure is still open (E-03). |
| Real CGMacros data in the engineering environment | **None.** Every real-data item below needs a run on your machine. |
| Official PhysioNet / Nature pages | Not reachable from the engineering environment; the data dictionary text must come from you (H3). |

### Status vocabulary

- **VERIFIED**: tests pass *and* negative controls or mutation checks show the tests can fail; for items that depend on the real data, a reproducible real-data run is also committed. Pure mathematics may be VERIFIED on synthetic tests alone.
- **IMPLEMENTED**: code exists and its tests pass on synthetic data; real-data validation is pending.
- **PARTIAL**: some of the requirement exists. **NOT STARTED**. **BLOCKED**: cannot proceed until another item or human input is resolved. **NEEDS HUMAN ACTION**: only you can do it.

## 2. Completed so far

- Milestone 1: scaffold, config, read-only inventory tool, real inventory run (committed by you at `3de4fcb`/`b570d9a`).
- Preservation and reconciliation: three recoverable copies of the local-only work (section 6); GitHub `b570d9a` fast-forwarded in; the two colliding audit scripts kept under new names; nothing overwritten.
- Research core (Models A/B/C, closed-form Bayesian update, versioned in-memory twin, evaluation metrics, leakage-safe split) integrated and tested on synthetic data.
- Phase 1 foundation (this phase): meal extraction defects fixed (leading gaps, overlap flags, missing-channel exclusions logged, participant/event ids, past-only baseline); event, feature and outcome layer with the blueprint's mutation leakage test; one-command event-count and schema report; privacy fix for the inventory report; corrected aggregate dataset summary; `docs/data_validity_rules.md`; dependency declarations and a drift test.

## 3. Feature matrix

Legend for the last column: **AI** = I can complete it; **HUMAN** = needs you; **AI after H#** = I continue once your input arrives.

### 3.1 Data and scientific validity (blueprint sections 6, 7, 8)

| ID | Blueprint section and requirement | Status | Evidence (files, tests) | Works today / remains | Depends on, assumptions | Next action | Acceptance criterion | Who |
|---|---|---|---|---|---|---|---|---|
| D-01 | 26: configurable local data root | VERIFIED | `config.py`; `tests/test_config.py` (5) | Env var or `--data-root`; clear errors; no default path | none | none | missing/invalid path fails with an actionable message | AI |
| D-02 | 27 d1-2: read-only dataset inventory | VERIFIED | `data/inventory.py`; `tests/test_inventory.py` (8), `test_inventory_privacy.py` (4); real run in committed `dataset_inventory_summary.md` | Counts, schemas, missingness; read-only | none | none | tests pass; real run committed | AI |
| D-03 | 6/19: redacted aggregate evidence | IMPLEMENTED | `scripts/derive_aggregate_summary.py`; `tests/test_derive_aggregate_summary.py` (5); `data/audit/dataset_aggregate_summary.*` | No participant names; test keeps it in sync with the source markdown. Legacy `dataset_inventory_summary.{md,json}` (names; stale JSON) still tracked | your decision | Remove or replace the legacy pair | no participant file name in any tracked summary | HUMAN (H6) |
| D-04 | 6: load per-participant CSVs | IMPLEMENTED | `data/meals.py::load_participant_data`; `test_meals.py` | Strips columns, parses time, keeps raw and normalised labels. Not yet run on real files here | real files | `scripts/build_event_table.py` on your machine | runs on all 45 files with no read errors | AI after H2 |
| D-05 | 6: participant-level schema handling | PARTIAL | `meals.extract_meal_events_detailed` logs `cgm_channel_missing`; `build_event_table.py::schema_report`; tests | **Fact:** column counts differ (13/14/15 columns in 2/32/11 files). Which columns differ is unknown | R5 | run the report | schema groups and per-channel availability recorded in `data_validity_rules.md` | AI after H2 |
| D-06 | 6/16: `bio.csv` clinical baseline, glycaemic group | NOT STARTED | none | Fact: `bio.csv` is 45 rows x 24 columns; column names unknown to the engineering environment | R13 | paste the header names | static profile loaded; group label available for stratified splits | AI after H4 |
| D-07 | 6: Fitbit HR/METs alignment | PARTIAL | `data/events.py::pre_meal_activity`; `test_events.py` | Strictly-before 4 h mean METs with coverage. HR deviation not built; real coverage unknown | R10 | measure coverage on real data | coverage distribution committed; HR deviation defined | AI after H2 |
| D-08 | 3/7: native-timestamp CGM pipeline | BLOCKED | none | The blueprint assumes native-interval files. The README lists only the interpolated per-minute file; no native source found. Lag-guarded baseline/trend implemented as the fallback | R3, H3 | confirm whether any native export exists | either a native source is identified or the lag-guard fallback is accepted in writing | HUMAN (H3) |
| D-09 | 7 risk 1: interpolation evidence | PARTIAL | pushed `audit_cgm_interpolation.py` (hard-coded conclusions, no pytest); mine `audit_cgm_sampling_phase.py` (31 tests, mutation-checked, synthetic only) | No real-data result is committed for either | R3 | run the pilot (5) then all 45 | aggregate JSON committed; verdict recorded in R3 | HUMAN (H2) |
| D-10 | 8: meal-event construction, exclusions | IMPLEMENTED | `data/meals.py::extract_meal_events_detailed`; `test_meals.py` (6), `test_meals_detailed.py` (14); 15 mutants all caught | Leading/internal/trailing gaps, past-only baseline, overlap flags, exclusion log that reconciles. Confirmed defects fixed | R1, R6, R11 | real-data run | exclusion reasons reconcile on all 45 files | AI after H2 |
| D-11 | 8: meal start / end semantics | NEEDS HUMAN ACTION | `docs/data_validity_rules.md` section B | Window anchored at the logged row (D1); inconsistency in the blueprint resolved explicitly, awaiting your confirmation | R1, R2 | confirm D1; supply dictionary rows | decision recorded with evidence | HUMAN (H1, H3) |
| D-12 | 6: feature table | PARTIAL | `data/events.py::build_event_table`, `FEATURE_COLUMNS` | Done: macros, baseline, 30-min trend, 4 h METs, time since last meal. Missing: HR deviation, glycaemic group | D-06, D-07 | add after H4 | all blueprint features present or explicitly dropped | AI after H4 |
| D-13 | 8: target (peak, rise, label >= 180) | IMPLEMENTED | `events.compute_outcome`; `test_events.py` | Excludes the reading at t0; label inclusive; 140 mg/dL secondary label not added | R9 | add secondary label after counts exist | boundary and t0 tests pass | AI |
| D-14 | 6 checkpoint: event counts | IMPLEMENTED | `events.event_count_report`, `scripts/build_event_table.py`; `test_build_event_table_script.py` (4) | Anonymised counts, exclusion reasons, per-class counts; groups need `bio.csv` | R9, R5 | run on your machine | counts per class and exclusion reason committed | HUMAN (H2) |
| D-15 | 7: leakage unit test | IMPLEMENTED | `test_events.py` (13): mutation test through the real pipeline, plus a stronger lag-guard variant and a non-vacuity test | Passes on synthetic frames. The blueprint requires it on real participants (>= 5) before training | real data | write `scripts/check_leakage_on_data.py`, run it | passes for >= 1 meal per participant on real files | AI writes, HUMAN runs |
| D-16 | 7/9: participant-level split for Model A (5-fold, stratified) | NOT STARTED | none | needs the group label | D-06 | build seeded fold manifest | disjoint participants per fold, seeded and reproducible | AI after H4 |
| D-17 | 7/9: chronological split for B/C | IMPLEMENTED | `features.chronological_participant_split`, `assert_no_temporal_leakage`; `test_leakage_and_eval.py` | Per-participant, purges overlapping outcome windows. Blueprint says first half trains: parameter | none | add the prequential harness (M-11) | no train window reaches the first test meal | AI |

### 3.2 Models and experiment (sections 9, 10, 21, 22)

| ID | Requirement | Status | Evidence | Works today / remains | Depends on, assumptions | Next action | Acceptance criterion | Who |
|---|---|---|---|---|---|---|---|---|
| M-01 | Model A: population XGBoost | PARTIAL | `models/baseline.py`; tests | Fits/predicts, seeded, rejects single class. No participant CV, no glycaemic-group feature, no isotonic calibration | D-16 | add CV and calibration | participant-wise CV runs; isotonic fitted on training folds only | AI |
| M-02 | Model B: personalised carb sensitivity | PARTIAL | `models/bayesian.py`; `test_bayesian.py` | Hierarchical prior + closed-form update. **Deviation from blueprint:** includes an intercept | R14 | decide intercept after real residual diagnostics | documented decision with diagnostics | AI after data |
| M-03 | Model C: activity interaction | PARTIAL | same | Interaction term with centred activity, recovered on synthetic data | R10 | same | same | AI after data |
| M-04 | Closed-form update | VERIFIED | `test_bayesian.py` (17): manual formula, ridge/MAP equivalence, sequential = batch, PSD, forecast = Monte Carlo; 16 mutants all caught | Mathematically correct; known noise variance is an assumption | none | none | tests pass | AI |
| M-05 | Prior from training population, stratified by group | PARTIAL | `fit_population_prior` | Empirical-Bayes; not stratified (no groups); leave-one-participant-out supported | D-06 | stratify after H4 | prior never sees held-out participants | AI after H4 |
| M-06 | Observation-noise and Gaussian assumptions | NEEDS HUMAN ACTION | `docs/modelling_assumptions.md` | Gaussian, constant variance, known noise variance are assumptions | real events | residual diagnostics | decision recorded | AI after data; H confirm |
| M-07 | Forecast with uncertainty (section 19) | PARTIAL | `bayesian.forecast_exceeds_180`, `twin/state.py` | Probability and 90% interval; data-quality flag is only partly wired | none | wire quality flags | interval widens with missing data in a test | AI |
| M-08 | Calibration metrics, reliability diagrams | PARTIAL | `models/evaluation.py` | Brier, ECE, AUROC, AUPRC, bins, small-sample warnings. No plots, no per-group reports, no cold-start split | none | add plots and splits | reliability diagrams from a real run | AI |
| M-09 | Active vs sedentary comparison | PARTIAL | `compare_models_on_activity_strata` | Works for a given threshold; the definition is undecided | R10 | decide from training data | definition recorded before results | AI after data |
| M-10 | Simple baselines, participant-clustered CIs | NOT STARTED | none | needed so a win is not an artefact | D-10 | implement | CIs reported for every comparison | AI |
| M-11 | Key experiment (A vs B vs C, prequential) | BLOCKED | none | needs eligible events and the rules above | D-14, R1, R9 | build the harness now; run once data exist | frozen plan; shuffled-history and permuted-activity controls | AI after H2 |
| M-12 | Evaluation manifest and seeds | NOT STARTED | none | | M-11 | implement | one command reproduces the table | AI |

### 3.3 Digital twin lifecycle (sections 4, 11, 16)

| ID | Requirement | Status | Evidence | Works today / remains | Depends on | Next action | Acceptance criterion | Who |
|---|---|---|---|---|---|---|---|---|
| T-01 | Formal `TwinState` | PARTIAL | `twin/state.py` | Holds the Bayesian parts and version. Blueprint's static profile, glucose/activity/HR state, meal state are not modelled | D-06 | extend | fields match the blueprint or deviations are documented | AI |
| T-02 | Versioned history, parent linkage, timestamps | PARTIAL | `TwinStore` | Versions and creation time exist; `parent_version_id` is implicit; in memory | T-05 | add explicit parent link | chain verified in a round-trip test | AI |
| T-03 | Forecast, reconcile, update | IMPLEMENTED | `forecast_meal`, `reconcile_forecast`; `test_twin_state.py` (7) | Order-independent, idempotent, window-guarded; synthetic only | none | connect to the event table (T-06) | one real eligible meal flows end to end | AI |
| T-04 | Safe on missing data, invalid windows, duplicates | IMPLEMENTED | same | Guards reject repeats, early windows, inconsistent labels, non-finite values | none | add failed-update rollback with persistence | a failed update leaves the version unchanged | AI |
| T-05 | SQLite persistence | NOT STARTED | none | not started by design (Phase 4) | M-04, T-02 | start after the experiment foundation | twin survives a process restart | AI |
| T-06 | Event table to forecast loop adapter | NOT STARTED | none | schemas now compatible (`events` -> `features.validate_meal_events`) | D-10 | write the adapter | adapter output passes `validate_meal_events` | AI |

### 3.4 Product and deliverables (sections 15, 17, 23, 25)

| ID | Requirement | Status | Next action | Acceptance criterion | Who |
|---|---|---|---|---|---|
| P-01 | FastAPI + Pydantic endpoints (section 15) | NOT STARTED (Phase 4) | after T-05 | every endpoint returns the specified shape; invalid input gives a clear 4xx | AI |
| P-02 | API and persistence tests | NOT STARTED | with P-01 | idempotency, validation, rollback tested | AI |
| P-03 | Replay engine (MUST) | NOT STARTED (Phase 5) | after P-01 | a recorded day replays end to end from real eligible data | AI |
| P-04 | React dashboard MUST screens | NOT STARTED (Phase 5) | after P-03 | all MUST screens work against the real backend | AI; HUMAN reviews |
| P-05 | SHOULD: activity chart, history, explanation, experiment chart | NOT STARTED | after P-04 | needs real results to chart | AI |
| P-06 | OPTIONAL: what-if, model card page, CSV export | NOT STARTED | only after core completes | n/a | AI |
| X-01 | README | PARTIAL | refreshed this phase; extend with architecture | an engineer can run the tests and scripts from it | AI |
| X-02 | Architecture diagrams, model card | NOT STARTED | Phase 6 | reflect the real code | AI |
| X-03 | Safety disclaimer on every UI screen | PARTIAL (README only) | with the UI | present and unremovable | AI |
| X-04 | LICENSE and citations | NOT STARTED | needs your licence choice | file present | HUMAN (H7) |

### 3.5 Engineering health

| ID | Requirement | Status | Evidence / note |
|---|---|---|---|
| E-01 | Git reconciliation preserving all work | IMPLEMENTED locally | `b570d9a` fast-forwarded; local-only work in layered commits; publication pending your approval (H5) |
| E-02 | Declared dependencies match imports | VERIFIED | `tests/test_project_config.py` (2) |
| E-03 | Intermittent test failure | OPEN | One failure in one full run before this phase (test not captured). Since then 52 full runs without an unexplained failure (14 with random hash seeds, 8 under CPU load, 30 in the background hunt; one hunt failure was my own mid-edit state). Cause unidentified; do not call the suite reliably green until understood |
| E-04 | Safety exclusions (no dosing, medication, diagnosis, avatar, chatbot) | PARTIAL | none of these exist in the code; the API does not exist yet, so the endpoint list cannot be audited |

## 4. Unresolved blockers, by severity

1. **Critical:** native vs interpolated CGM evidence is absent (D-08/D-09); meal-row meaning and the window anchor are unconfirmed (D-11).
2. **Critical:** no real event counts, so the 180 mg/dL target's feasibility is unknown (D-14, R9).
3. **High:** schema differences between participants are unexplained (D-05); no `bio.csv` columns, so no glycaemic group (D-06).
4. **High:** the key experiment cannot run until 1-3 are resolved (M-11).
5. **Medium:** legacy artifacts with participant file names are still tracked (D-03); one unexplained test failure (E-03); publication of the local work (E-01).

## 5. Next actions in dependency order

1. **You:** run the one-command evidence set (H2) and send the aggregate outputs.
2. **AI, now:** `scripts/check_leakage_on_data.py` (blueprint test on real files), the prequential harness skeleton (M-11), trivial baselines and cluster-bootstrap CIs (M-10), the event-table-to-twin adapter (T-06). None needs real data to write.
3. **AI after H2:** close R3, R5-R7, R9-R11 with the evidence; fix defects it exposes.
4. **AI after H4:** ingest `bio.csv`, stratified prior and folds (D-06, M-05, D-16).
5. **AI:** Phase 3 experiment run once D-14 shows enough events; freeze it.
6. **AI:** Phase 4 SQLite and FastAPI, Phase 5 replay and dashboard, Phase 6 documentation. Not before items 1-5.

## 6. Preservation record (recoverable copies of the local-only work)

- Folder copy and `refs.bundle` (contains `1f53759` and `b570d9a`), SHA-256 manifest of all 17 local-only files, all verified: stored in the engineering session's scratch area (ephemeral; **publishing a backup branch is H5**).
- Local branch `backup/local-only-research-core-1f53759` (commit `11dbae6`): byte-identical snapshot of the local-only files.
- Pushed originals of `scripts/audit_cgm_interpolation.py`, `scripts/audit_meal_events.py`, `src/glycotwin/data/meals.py` (extended, not replaced), `tests/test_meals.py` are intact; my competing scripts are `scripts/audit_cgm_sampling_phase.py` and `scripts/audit_meal_event_semantics.py`.

## 7. Human Action Queue

Only items that automation cannot do. Batched so you can answer once.

| ID | Why automation is insufficient | Your one instruction |
|---|---|---|
| **H1** | A scientific choice that evidence cannot settle yet: the outcome window anchor (`docs/data_validity_rules.md` section B). | Reply "confirm D1" or "use meal-end +20 min" (I will implement the alternative as the primary and keep the other as sensitivity). |
| **H2** | The real data are not in the engineering environment. | In PowerShell run `python scripts\build_event_table.py`, then `python scripts\audit_cgm_sampling_phase.py`, then `python scripts\audit_meal_event_semantics.py`, and paste each printed JSON (aggregate-only; skim it first). Add `--channel "Libre GL"` to the first for the second device. |
| **H3** | PhysioNet is not reachable from the engineering environment. | Open the dataset's `DataDictionary` and paste the definition rows for `Timestamp`, `Libre GL`, `Dexcom GL`, `Meal Type`, `Amount Consumed`, and any note on interpolation. Also say whether the download contains any file with native (uninterpolated) CGM readings. |
| **H4** | `bio.csv` is not in the engineering environment. | Paste the 24 column names of `bio.csv` (names only, no values) and say which column is the glycaemic group. |
| **H5** | Publishing is irreversible and the engineering workspace is ephemeral. | Reply "push" to publish the reconciled branch (fast-forward from `b570d9a`) and a `backup/local-only-research-core-1f53759` branch; or "hold". I have pushed nothing. |
| **H6** | Deleting tracked files is consequential. | Reply "replace legacy audit files" to remove `data/audit/dataset_inventory_summary.{json,md}` (still in Git history), or "keep". |
| **H7** | A licence is a legal choice; the final review is yours. | Pick a licence for the project code (note the dataset's CC BY-NC-SA 4.0 terms) and, at the end, review the demo and results before submission. |
