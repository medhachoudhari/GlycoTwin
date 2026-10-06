# GlycoTwin project status

Research proof of concept. **Not a diagnostic or treatment tool**; it gives no medical advice and no
insulin, medication or diet recommendations. Specification: `GlycoTwin-Master-Blueprint.pdf` (38 pages).
This file is the single tracker; it is updated after every implementation phase.

## 0. Gate checkpoint (GREEN / YELLOW / RED)

A gate is **GREEN only when every stated acceptance criterion has actually been met** with the evidence it names.
**YELLOW**: some criteria are met with evidence; the rest are not yet met. **RED**: a required criterion has no evidence and
cannot be met until real-data results or a human input exist. Synthetic tests never turn a data or research gate green.

| Gate | Signal | One-line reason |
|---|---|---|
| 1. Repository and engineering | **YELLOW** | Clean-export tests pass in a fresh venv and docs are consistent; but nothing is published (backups are local/ephemeral) and one unexplained test failure is still open. |
| 2. Data validity | **RED** | No evidence script has been run on the real dataset; the tooling is ready and tested, but it only exists in this session. |
| 3. Research validity | **RED** | No real run of Models A/B/C or the controls; sample-size minimums unconfirmed; design verified on simulations only. |
| 4. Innovative features | **YELLOW** | Math, lifecycle and uncertainty verified on synthetic data; replay and persistent history not built; nothing demonstrated on real data. |
| 5. Product readiness | **RED** | No persistence, API, replay, or dashboard (deliberately not started; they sit behind Gates 2-3). |

### Gate 1: repository and engineering: YELLOW

| Acceptance criterion | Met? | Evidence (command / file) |
|---|---|---|
| Correct repository state | Partly | Branch `claude/glycotwin-initial-scaffold-gegpzd`, clean tree, `b570d9a` is an ancestor of HEAD, `git fsck` clean, no data/secret files tracked (`git ls-files`, `.gitignore` checked). **Not published: 12 commits are local only; GitHub is still at `b570d9a`.** |
| Backups preserved | Partly | Verified: `refs.bundle` (contains `1f53759` and `b570d9a`), folder copy matches all 17 manifest hashes, local branch `backup/local-only-research-core-1f53759` (`11dbae6`), local tag `baseline-b570d9a`. **The bundle and folder copy live in the session scratch area (ephemeral) and the branch is local: not durable until pushed (H5).** |
| Tests pass from a clean checkout/export | Yes | `git archive HEAD` into a new virtualenv, `pip install -r requirements.txt && pip install -e .` exactly as the README says, `python -m pytest -q`: **159 passed** at `7aed9f6` (before the latest commits). Final run at HEAD: **173 passed** at `69dc56f` (fresh virtualenv, `git archive` export, 1 run). |
| Dependencies and docs consistent | Yes | `tests/test_project_config.py` (every import declared in `pyproject.toml` and `requirements.txt`); a path check found no README/docs reference to a missing file. |
| Test suite reliable | **No** | One failure in one full run before the integration was never captured. A repeat hunt (random order seeds, 159-test export at `7aed9f6`) had 0 failures in the first 27 of 40 planned runs when this was written; that lowers but does not remove the doubt. Cause unidentified (E-03). |

Blockers: publication (H5); the unexplained failure. **Next acceptance criterion for GREEN:** the push is verified (`git rev-parse origin/<branch>` equals HEAD,
backup branch on the remote) **and** either the failure is reproduced and fixed or at least 100 consecutive clean runs from a clean export are logged.

### Gate 2: data validity: RED

| Acceptance criterion | Met? | Evidence |
|---|---|---|
| Evidence scripts run on the real dataset | **No** | None has been run. The real dataset exists only on your machine. |
| Meal semantics verified (start vs later point; meal-end field) | **No** | R1/R2 open. Probe `scripts/audit_meal_event_semantics.py`: 10 tests, 9 injected bugs caught; it separates the two patterns on synthetic files. Real answer unknown. |
| CGM sampling limitations verified | **No** | R3 open. `scripts/audit_cgm_sampling_phase.py`: 31 tests, 15 bugs caught, ~1 s per channel on a 15,000-row series (about 2 minutes for all 45 files). Pushed `audit_cgm_interpolation.py` prints fixed conclusions and is not evidence. |
| Missingness, gap and overlap exclusions, eligible counts, outcome labels | **No** | `scripts/build_event_table.py` (4 tests) will report them; not run. |
| Facts that ARE verified from real data | Limited | Only the committed inventory aggregate: 45 files, 687,580 rows, column counts 13/14/15 (2/32/11), every row count divisible by 5 and 44 of 45 by 15. Structural facts, causes not established. |

Blockers: the scripts are not on your machine (unpushed); you must run them (H2) and supply the dictionary rows (H3) and `bio.csv` names (H4).
**Next acceptance criterion for GREEN:** aggregate JSON from `build_event_table.py`, `check_leakage_on_data.py`, `audit_cgm_sampling_phase.py` and
`audit_meal_event_semantics.py` is committed under `data/audit/` and rules R1-R14 each cite it or are explicitly decided by you.

### Gate 3: research validity: RED

| Acceptance criterion | Met? | Evidence |
|---|---|---|
| Feature timing and leakage safeguards verified | Synthetic only | `tests/test_events.py` (13), `tests/test_leakage_check.py` (5): mutation test passes through the real pipeline and fails when a pipeline leaks. The real-data run (`check_leakage_on_data.py`) has not happened. |
| Participant-level and chronological evaluation confirmed | Code only | Leave-one-participant-out prequential harness; updates only after the window closes; priors, baselines and the active cut from other participants only (`tests/test_experiment.py`, 15 tests, 12 bugs caught). |
| Experiment design and minimum sample sizes verified | **No** | Placeholders unconfirmed (H8). The simulation in `docs/INNOVATION_ROADMAP.md` section 6 shows the placeholders (20 participants, median 8 events) are too small even for a strong activity effect (power 0.38) and that a modest effect is undetectable. |
| Models A, B, C and controls run on eligible real data | **No** | Not run; `scripts/run_experiment.py` will refuse underpowered data. |
| Metrics, intervals, calibration, limitations, verdict on the innovation | **No** | None exist. **The evidence neither supports nor contradicts the innovation.** |

Blockers: Gate 2; H1 and H8. **Next acceptance criterion for GREEN:** the frozen plan (H1, H8, decision rules) is committed, then one real run of
`run_experiment.py` produces a report with every pre-listed comparison, intervals and sample sizes, plus the sensitivity variants.

### Gate 4: innovative features: YELLOW

| Acceptance criterion | Met? | Evidence |
|---|---|---|
| Activity-conditioned Bayesian personalisation verified | Math: yes. Real data: no | `tests/test_bayesian.py` (17): matches the closed-form and ridge/MAP solutions, sequential = batch, PSD, Monte-Carlo agreement; 16 bugs caught. Model C recovers a simulated interaction. |
| Forecast, observe, update lifecycle verified | In memory | `tests/test_twin_state.py` (7): version chain, idempotent reconcile, window and consistency guards, order independence. Not connected to the event table (T-06). |
| Uncertainty calculations verified | Synthetic | Probability equals the Monte-Carlo frequency; 90% interval has 90% coverage; calibrated under correct specification. |
| Replay and state history verified | **No** | History exists in memory only; **replay not built**; no persistence. |
| Implemented vs demonstrated on real data | Distinguished | See `docs/INNOVATION_ROADMAP.md` section 4: every row "Demonstrated on real data: No". |

Blockers: demonstration waits on Gates 2-3. **Next acceptance criterion for GREEN:** a real eligible participant's forecast, reconcile and update chain
is stored with parent links and replayed end to end, with the result reported whatever it is.

### Gate 5: product readiness: RED

No persistence, API, replay UI or dashboard exists (`git ls-files` shows no FastAPI, SQLAlchemy or frontend files). Reproducibility infrastructure is partly
in place (manifest, seeds, deterministic scripts, dependency test). I have deliberately **not** built the blocked features to raise a completion figure.
**Next acceptance criterion for GREEN:** SQLite twin versions survive a restart, every blueprint endpoint returns its specified shape with validated input,
a recorded day replays from real eligible data, and every MUST HAVE screen works against the real backend, all with passing tests.

## 1. Current checkpoint

| Item | Value |
|---|---|
| Branch | `claude/glycotwin-initial-scaffold-gegpzd` |
| Stable baseline (GitHub) | `b570d9a` (kept as an ancestor of everything below; tagged/bundled, see section 6) |
| Local commits on top of it (**not pushed**) | `068536c` research core; `cd57f0f` renamed audit scripts; `88d18ef` dependency declarations; `d1803cd` inventory privacy fix and aggregate summary; `372e22d` event pipeline; `29b2d37` docs; `6a5fc2e` discovery refactor; `bd12e40` tracker update; `4bacde3` experiment harness. Commits `372e22d` and `29b2d37` each had one failing test (the dependency-drift guard catching a fragile sibling import); `6a5fc2e` fixes it. |
| Automated tests | **159 passed** at `4bacde3` (clean `git archive` export; see section 8) (`python -m pytest -q`). One earlier unexplained failure is still open (E-03). |
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
| D-11 | 8: meal start / end semantics | NEEDS HUMAN ACTION | `docs/data_validity_rules.md` section B; probe `scripts/audit_meal_event_semantics.py` now has `tests/test_audit_meal_event_semantics.py` (10; 9 injected bugs caught): separates a rise-after-row from a rise-before-row pattern on synthetic files; real-data answer unknown | Window anchored at the logged row (D1); inconsistency in the blueprint resolved explicitly, awaiting your confirmation | R1, R2 | confirm D1; supply dictionary rows | decision recorded with evidence | HUMAN (H1, H3) |
| D-12 | 6: feature table | PARTIAL | `data/events.py::build_event_table`, `FEATURE_COLUMNS` | Done: macros, baseline, 30-min trend, 4 h METs, time since last meal. Missing: HR deviation, glycaemic group | D-06, D-07 | add after H4 | all blueprint features present or explicitly dropped | AI after H4 |
| D-13 | 8: target (peak, rise, label >= 180) | IMPLEMENTED | `events.compute_outcome`; `test_events.py` | Excludes the reading at t0; label inclusive; 140 mg/dL secondary label not added | R9 | add secondary label after counts exist | boundary and t0 tests pass | AI |
| D-14 | 6 checkpoint: event counts | IMPLEMENTED | `events.event_count_report`, `scripts/build_event_table.py`; `test_build_event_table_script.py` (4) | Anonymised counts, exclusion reasons, per-class counts; groups need `bio.csv` | R9, R5 | run on your machine | counts per class and exclusion reason committed | HUMAN (H2) |
| D-15 | 7: leakage unit test | IMPLEMENTED | `test_events.py` (13), `test_leakage_check.py` (5): mutation test through the real pipeline, a stronger lag-guard variant, a non-vacuity test, and proof the check fails when a pipeline leaks; `scripts/check_leakage_on_data.py` runs it on real files | Passes on synthetic frames. The blueprint requires it on real participants (>= 5) before training | real data | run `scripts\check_leakage_on_data.py` (written) | passes for >= 1 meal per participant on real files | HUMAN (H2) |
| D-16 | 7/9: participant-level split for Model A (5-fold, stratified) | NOT STARTED | none | needs the group label | D-06 | build seeded fold manifest | disjoint participants per fold, seeded and reproducible | AI after H4 |
| D-17 | 7/9: chronological split for B/C | IMPLEMENTED | `features.chronological_participant_split`, `assert_no_temporal_leakage`; `test_leakage_and_eval.py` | Per-participant, purges overlapping outcome windows. Blueprint says first half trains: parameter | none | add the prequential harness (M-11) | no train window reaches the first test meal | AI |

### 3.2 Models and experiment (sections 9, 10, 21, 22)

| ID | Requirement | Status | Evidence | Works today / remains | Depends on, assumptions | Next action | Acceptance criterion | Who |
|---|---|---|---|---|---|---|---|---|
| M-01 | Model A: population XGBoost | PARTIAL | `models/baseline.py`; `experiment.py` (`include_model_a`); `test_run_experiment_script.py` | Fits/predicts, seeded, rejects single class; now evaluated leave-one-participant-out inside the harness (raw probabilities). No glycaemic-group feature, no isotonic calibration, no 5-fold stratified CV | D-06, D-16 | add isotonic calibration (inner split) and group stratification | isotonic fitted on training folds only; folds stratified by group | AI after H4 |
| M-02 | Model B: personalised carb sensitivity | PARTIAL | `models/bayesian.py`; `test_bayesian.py` | Hierarchical prior + closed-form update. **Deviation from blueprint:** includes an intercept | R14 | decide intercept after real residual diagnostics | documented decision with diagnostics | AI after data |
| M-03 | Model C: activity interaction | PARTIAL | same | Interaction term with centred activity, recovered on synthetic data | R10 | same | same | AI after data |
| M-04 | Closed-form update | VERIFIED | `test_bayesian.py` (17): manual formula, ridge/MAP equivalence, sequential = batch, PSD, forecast = Monte Carlo; 16 mutants all caught | Mathematically correct; known noise variance is an assumption | none | none | tests pass | AI |
| M-05 | Prior from training population, stratified by group | PARTIAL | `fit_population_prior` | Empirical-Bayes; not stratified (no groups); leave-one-participant-out supported | D-06 | stratify after H4 | prior never sees held-out participants | AI after H4 |
| M-06 | Observation-noise and Gaussian assumptions | NEEDS HUMAN ACTION | `docs/modelling_assumptions.md` | Gaussian, constant variance, known noise variance are assumptions | real events | residual diagnostics | decision recorded | AI after data; H confirm |
| M-07 | Forecast with uncertainty (section 19) | PARTIAL | `bayesian.forecast_exceeds_180`, `twin/state.py` | Probability and 90% interval; data-quality flag is only partly wired | none | wire quality flags | interval widens with missing data in a test | AI |
| M-08 | Calibration metrics, reliability diagrams | PARTIAL | `models/evaluation.py` | Brier, ECE, AUROC, AUPRC, bins, small-sample warnings. No plots, no per-group reports, no cold-start split | none | add plots and splits | reliability diagrams from a real run | AI |
| M-09 | Active vs sedentary comparison | PARTIAL | `compare_models_on_activity_strata` | Works for a given threshold; the definition is undecided | R10 | decide from training data | definition recorded before results | AI after data |
| M-10 | Simple baselines, participant-clustered CIs | IMPLEMENTED | `models/experiment.py` (`personal_rate`, `population_constant`, `paired_cluster_bootstrap`); `tests/test_experiment.py` (15), 12 injected bugs all caught | Baselines and a paired bootstrap that resamples PARTICIPANTS; an interval containing 0 is reported as inconclusive. Synthetic only. Note: the running-mean baseline is noisy, so beating it is a weak test; the shuffled-history control is the stronger one | none | none until real events exist | CIs reported for every comparison in the run report | AI |
| M-11 | Key experiment (A vs B vs C, prequential) | PARTIAL: harness IMPLEMENTED; the run is BLOCKED | `models/experiment.py`, `scripts/run_experiment.py`; `test_experiment.py`, `test_run_experiment_script.py` (4) | Forecast-then-learn per held-out participant; updates only after the outcome window closes; priors, baselines and the active/sedentary cut from other participants only; frozen, shuffled-history and permuted-activity controls; refuses underpowered data (placeholder minimums need your confirmation). On synthetic simulations it detects an effect when one exists and stays inconclusive when none does. No real run | D-14, R1, R9 | run once data and rules exist; confirm the minimums before looking at results | frozen plan; run report with every pre-listed comparison and its interval | AI after H2; HUMAN confirms minimums (H8) |
| M-13 | Power simulation for the minimum sample sizes (H8) | IMPLEMENTED | `scripts/simulate_power.py`, `models/simulation.py`; `test_simulate_power.py` (3) | SIMULATION under assumed heterogeneity and effect sizes; estimates false-positive rate and power of the harness; results in `docs/INNOVATION_ROADMAP.md` section 6; says nothing about CGMacros | none | rerun with real per-participant event counts | numbers are labelled assumed | AI |
| M-12 | Evaluation manifest and seeds | IMPLEMENTED | `experiment.build_manifest`; tested for determinism and data-change detection | Seeds, parameters, package versions, counts and a hash of the event table (no participant values) are recorded with every run | none | none | one command reproduces the report from the same table | AI |

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
2. **AI, now (no real data needed):** the event-table-to-twin adapter (T-06); isotonic calibration and the reliability-diagram generator (M-01, M-08); then Phase 4 groundwork that does not depend on results. The prequential harness, baselines and bootstrap (M-10, M-11, M-12) are done.
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
| **H2** | The real data are not in the engineering environment. | In PowerShell run `python scripts\build_event_table.py`, then `python scripts\check_leakage_on_data.py`, then `python scripts\audit_cgm_sampling_phase.py`, then `python scripts\audit_meal_event_semantics.py`, and paste each printed JSON (aggregate-only; skim it first). Add `--channel "Libre GL"` to the first for the second device. |
| **H3** | PhysioNet is not reachable from the engineering environment. | Open the dataset's `DataDictionary` and paste the definition rows for `Timestamp`, `Libre GL`, `Dexcom GL`, `Meal Type`, `Amount Consumed`, and any note on interpolation. Also say whether the download contains any file with native (uninterpolated) CGM readings. |
| **H4** | `bio.csv` is not in the engineering environment. | Paste the 24 column names of `bio.csv` (names only, no values) and say which column is the glycaemic group. |
| **H5** | Publishing is irreversible and the engineering workspace is ephemeral. | Reply "push" to publish the reconciled branch (fast-forward from `b570d9a`) and a `backup/local-only-research-core-1f53759` branch; or "hold". I have pushed nothing. |
| **H6** | Deleting tracked files is consequential. | Reply "replace legacy audit files" to remove `data/audit/dataset_inventory_summary.{json,md}` (still in Git history), or "keep". |
| **H7** | A licence is a legal choice; the final review is yours. | Pick a licence for the project code (note the dataset's CC BY-NC-SA 4.0 terms) and, at the end, review the demo and results before submission. |
| **H8** | The experiment's minimum sample sizes are a scientific choice made before seeing results; the code ships placeholders (20 participants, median 8 events each, 30 positives, 30 negatives). | Confirm or change those four numbers (or say "keep placeholders") before the first real run. |

## 8. Latest verification log

| When | Command / evidence | Result |
|---|---|---|
| after `6a5fc2e` | clean `git archive` export, `python -m pytest -q` | 140 passed |
| at `4bacde3` (experiment harness) | clean `git archive` export, `python -m pytest -q` | 159 passed |
| mutation checks | injected bugs, one at a time, into scratch copies | Bayesian/twin core 16/16 caught; sampling-phase audit 15/15; meals+events 15/15; experiment harness 12/12 (each after adding tests for the first survivor) |
| flake hunt | 30 background full runs with random hash seeds + earlier 22 | 51 clean runs; 1 failure explained (my mid-edit state). The pre-phase one-off failure remains unexplained (E-03) |
