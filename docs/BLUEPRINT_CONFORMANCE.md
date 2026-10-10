# Blueprint traceability matrix

**Source of truth:** `GlycoTwin-Master-Blueprint.pdf`, 38 pages, read in full text form (equations, tables, diagram text, evaluation, safety, demo, risks, checklists). Diagram *images* were not inspected, only their text. An earlier version of this file wrongly said the PDF was unreadable.
**Not clinically validated. No claim that Model C beats Model B: the reported comparison is inconclusive (`docs/model_b_vs_c_report.md`). No real-data experiment was run in this pass: the dataset and the local forecast files are not in this environment.**

**Status.** COMPLETE = built and tested, nothing material missing. PARTIAL = part built. MISSING = buildable now without a database or web stack, not built. BLOCKED = needs data or a decision not available here. NOT BUILT (instructed) = database/API/frontend, excluded by the researcher. DEVIATION = built differently on purpose (reason stated).
**Real-data column.** `none` = never run on real data; `reported` = the researcher reported a real run (numbers supplied as text; not reproduced here). Synthetic tests check mechanics only and never validate a scientific claim.

| ID | Part | Requirement | Implementation | Status | Tests | Real data | Next action |
|---|---|---|---|---|---|---|---|
| A1 | 10 | Model `rise = (beta + gamma a) c`, Gaussian | `src/glycotwin/models/bayesian.py`, `src/glycotwin/models/model_c_cv.py` | COMPLETE | `tests/test_bayesian.py`, `tests/test_model_c_cv.py` | reported (inconclusive) | none |
| A2 | 10 | Closed-form posterior update (Sigma1, mu1) | `conjugate_update` in `src/glycotwin/models/bayesian.py` | COMPLETE | `tests/test_bayesian.py` | n/a | none |
| A3 | 10, 27 | Part 10 toy example reproduced by a unit test | `tests/test_blueprint_prior.py` (illustrative prior sds; the blueprint gives none) | COMPLETE | `tests/test_blueprint_prior.py` | n/a | none |
| A4 | 10 | beta prior = population regression stratified by glycaemic group | `src/glycotwin/models/blueprint_prior.py`, `docs/blueprint_prior.md` (opt-in) | PARTIAL: built, opt-in; the Model B/C runners now accept `--prior-scheme blueprint` (stratum chosen from the held-out participant's group, parameters from training participants only) | `tests/test_blueprint_prior.py`, `tests/test_prior_scheme_runners.py`, `tests/test_prior_compare.py` | none | run S2 (runbook section 3) then `scripts/compare_priors.py` (section 3b; prespecified screen in `docs/prior_comparison.md`) |
| A5 | 10 | gamma prior mean 0, "moderately wide" variance | same file; width 0.5 x beta / rms(activity) is OUR convention | PARTIAL: width is not specified by the blueprint; prespecified grid 0.25 / 0.5 / 1 / 2 via `--gamma-relative-sd` | `tests/test_blueprint_prior.py`, `tests/test_prior_scheme_runners.py` | none | run S3 (runbook section 3); report, do not tune |
| A6 | 10 | Research runs use the blueprint prior | Model B/C research runs use unstratified empirical-Bayes priors (researcher decisions R14/H12) | DEVIATION | `tests/test_model_b_cv.py`, `tests/test_model_c_cv.py` | reported | keep; regenerate B/C only if D-1 chooses the blueprint prior |
| A7 | 10 | Noise variance estimated from the population | `fit_population_prior`, `fit_scale_aware_prior`, `fit_blueprint_prior` | COMPLETE | `tests/test_bayesian.py`, `tests/test_blueprint_prior.py` | reported | none |
| A8 | 10 | Uncertainty never grows; narrows with meals | `posterior_convergence` in `src/glycotwin/twin/insight.py` | COMPLETE (per participant) | `tests/test_innovation_features.py` | none | run `replay_participant.py` on real participants; pooled-across-people convergence curve is not built (gap G-6) |
| A9 | 10 | Cold start from the population prior, never refuses | `src/glycotwin/twin/adapter.py` | COMPLETE | `tests/test_innovation_features.py` | none | real-data replay |
| A10 | 10, 32 | Fallback: clip posterior shift per meal if unstable | none | MISSING by design: the blueprint makes it conditional on instability appearing | none | none | build only if real-data replay shows instability |
| B1 | 11 | Forecast, wait for the window, observe, update, new version | `forecast_meal`, `reconcile_forecast` in `src/glycotwin/twin/state.py` | COMPLETE | `tests/test_twin_state.py`, `tests/test_audit_fixes.py` | none | real-data replay |
| B2 | 11 | Update only after `meal_end + 120 min` | `reconcile_forecast(observed_through=...)`, replay window rule | DEVIATION: anchor is the `Meal Type` row time, not `meal_end` (decision D9) | `tests/test_twin_state.py`, `tests/test_primary_event_definition.py` | reported | none |
| B3 | 11, 13 | Sensor gap over 30 min: mark excluded, no update | `exclude_forecast`, `ExclusionRecord` in `src/glycotwin/twin/state.py`; replay `excluded_reason` | COMPLETE for the twin; event-table gap limit default is 15 min (open rule R6) | `tests/test_blueprint_lifecycle_gaps.py` | none | decision D-3: gap limit 15 or 30 |
| B4 | 4, 11 | Versioned twin, parent link, `created_at`, never recomputed | `TwinState`, `TwinStore` in `src/glycotwin/twin/state.py`; SQLite `SqlTwinStore` in `src/glycotwin/backend/store.py` | COMPLETE (in memory and in SQLite) | `tests/test_twin_state.py` | n/a | none |
| B5 | 15 | Replay start / step engine | `ReplaySession`, `replay_lifecycle` in `src/glycotwin/twin/replay.py`; `scripts/replay_participant.py` | PARTIAL: engine complete and atomic; no HTTP endpoints | `tests/test_blueprint_lifecycle_gaps.py`, `tests/test_audit_fixes.py` | none | run on one real participant (command below) |
| B6 | 28 | T0-T8 demo sequence | `src/glycotwin/twin/demo.py`, `scripts/demo_twin_lifecycle.py` (SYNTHETIC, labelled) | PARTIAL: runs on simulated data only; the live demo needs a real participant, a UI and rehearsal | `tests/test_twin_insight.py` | none | real-participant replay; UI is NOT BUILT (instructed) |
| C1 | 4 | `static_profile` | `TwinState.profile`, `src/glycotwin/twin/state_view.py` | PARTIAL: carries what the caller supplies | `tests/test_quality_state_view.py` | none | `bio.csv` mapping (BLOCKED) |
| C2 | 4 | `current_glucose_state` | `twin_state_view` | PARTIAL: as of the last logged meal, no 5-minute tick | `tests/test_quality_state_view.py` | none | needs a streaming input (infrastructure) |
| C3 | 4 | `recent_activity_state` (METs, step count, label) | `twin_state_view`, `src/glycotwin/models/activity_strata.py` | PARTIAL: step count absent from the event table | `tests/test_quality_state_view.py` | none | none unless steps are in the data |
| C4 | 4 | `recent_hr_state` | `twin_state_view` (None when absent) | PARTIAL: HR deviation feature not built | `tests/test_quality_state_view.py` | none | decision D-4: define HR deviation |
| C5 | 4 | `meal_state` (open windows, carbs on board) | `twin_state_view` | PARTIAL: `carbs_on_board` is None (no absorption model in the blueprint) | `tests/test_quality_state_view.py` | none | decision D-5 |
| C6 | 4 | `uncertainty` (band width, rolling calibration score) | `twin_state_view` (rolling Brier of the last 10 reconciled forecasts) | COMPLETE (our definition of the score) | `tests/test_quality_state_view.py` | none | none |
| C7 | 4 | `prediction_state`, `historical_response_state` | `twin_state_view`, `reconciliation_report` | COMPLETE | `tests/test_quality_state_view.py`, `tests/test_innovation_features.py` | none | none |
| C8 | 16, 23 | Twin history table / CSV export | `twin_history_rows`, `twin_history_csv` in `src/glycotwin/twin/insight.py` | COMPLETE as data | `tests/test_blueprint_lifecycle_gaps.py` | none | none |
| D1 | 11, 19 | Forecast probability with interval | `forecast_exceeds_180` in `src/glycotwin/models/bayesian.py` | COMPLETE | `tests/test_bayesian.py` | reported | none |
| D2 | 19 | Data-quality flag and warning, separate from the posterior | `src/glycotwin/twin/quality.py`, `ForecastRecord.data_quality` | COMPLETE as a flag | `tests/test_quality_state_view.py` | none | none |
| D3 | 13, 19 | Low quality: "widen the interval" | `interval_adjusted` is always False | DELIBERATE DEVIATION: no validated model links the flags to forecast error; a factor would be invented | `tests/test_quality_state_view.py` | none | decision D-6: empirical coverage by quality stratum on real data, then adopt a factor only if it is supported |
| D4 | 19 | "Insufficient history" badge | `assess_forecast_quality` (< 3 own meals) | COMPLETE | `tests/test_quality_state_view.py` | none | none |
| D5 | 18 | Explanation: carbs, activity, trend, similar past meals | `explain_forecast`, `explain_forecast_in_context` | COMPLETE (exact additive terms; display conventions for "similar" and "trend") | `tests/test_innovation_features.py` | none | none |
| D6 | 18, 14 | SHAP for Model A only | `PopulationBaselineModel.contributions` (XGBoost TreeSHAP, no new package) | COMPLETE as a function | `tests/test_blueprint_lifecycle_gaps.py` | none | summarise on real Model A when it is run |
| D7 | 20 | What-if, side by side, verbatim research label | `what_if`, `what_if_side_by_side`, `WHAT_IF_SCREEN_LABEL` in `src/glycotwin/twin/insight.py` | COMPLETE as functions; the screen needs a UI | `tests/test_twin_insight.py`, `tests/test_blueprint_lifecycle_gaps.py` | n/a | UI NOT BUILT (instructed) |
| D8 | 25 | No dosing, medication, diagnosis; disclaimer text | `GUARDRAILS`, demo banner, README | PARTIAL: no UI or API to carry a persistent disclaimer | `tests/test_twin_insight.py` | n/a | with the UI |
| E1 | 6, 7 | Native-timestamp CGM pipeline | none | BLOCKED: no native export identified; a lag-guarded baseline over the interpolated file is the fallback | `tests/test_leakage_check.py` | none | researcher confirms whether native files exist (D-7) |
| E2 | 7 | Five leakage risks guarded; leakage unit test on >= 5 participants | `src/glycotwin/features.py`, `src/glycotwin/data/leakage_check.py`, `scripts/check_leakage_on_data.py` | COMPLETE in code; the real-data pass is not reproduced here | `tests/test_leakage_check.py`, `tests/test_events.py`, `tests/test_leakage_and_eval.py` | reported (not reproduced) | re-run before any final numbers |
| E3 | 6, 8 | Feature table | `src/glycotwin/data/events.py::FEATURE_COLUMNS` | PARTIAL: no `hr_deviation_from_resting`, no `glycaemic_group` | `tests/test_events.py` | reported | D-4 |
| E4 | 8 | Target over (meal_end, +120], >= 180, gap exclusion, logged exclusions | `compute_outcome`, `extract_meal_events_detailed` | DEVIATION: Meal Type row anchor (D9); gap default 15 | `tests/test_meals_detailed.py`, `tests/test_primary_event_definition.py` | reported | none |
| E5 | 6, 8 | 140 mg/dL secondary label; counts per group | event counts in `scripts/build_event_table.py` | PARTIAL: no 140 label (changes the event table schema) | `tests/test_build_event_table_script.py` | none | decision D-8 |
| E6 | 9 | Model A XGBoost, patient-level 5-fold stratified by group | `src/glycotwin/models/baseline.py`, `src/glycotwin/models/model_a_cv.py` | COMPLETE in code | `tests/test_model_a_cv.py` | none seen here | run (commands below) |
| E7 | 9 | Isotonic calibration of Model A | legacy `src/glycotwin/models/experiment.py` only | PARTIAL: not in the Model A CV | `tests/test_experiment.py` | none | decision D-9 (changes Model A's protocol) |
| E8 | 9 | B/C probability from the posterior predictive, not corrected | `forecast_exceeds_180` | COMPLETE | `tests/test_bayesian.py` | reported | none |
| E9 | 7, 9 | B/C evaluated on genuinely unseen future meals | sequential forecast-observe-update inside participant-level folds | DEVIATION: prequential instead of "first half trains" | `tests/test_model_b_cv.py`, `tests/test_model_c_cv.py` | reported | none |
| F1 | 21 | AUROC, AUPRC, Brier, ECE, reliability diagrams | `src/glycotwin/models/evaluation.py`, `src/glycotwin/models/reliability_svg.py` | COMPLETE | `tests/test_leakage_and_eval.py`, `tests/test_model_bc_compare.py` | reported | none |
| F2 | 21 | F1, sensitivity, specificity at 50% | `metric_bundle` in `src/glycotwin/models/model_a_cv.py` | COMPLETE per model run | `tests/test_model_a_cv.py` | none | none |
| F3 | 21 | Confidence intervals | participant-clustered percentile bootstrap, `src/glycotwin/models/model_bc_compare.py` | COMPLETE | `tests/test_model_bc_compare.py` | reported | none |
| F4 | 21 | Per-glycaemic-group results | `glycaemic_group_breakdown`; `group_metrics` for Model A | PARTIAL: tool ready (`--groups-file`); no group file | `tests/test_model_bc_compare.py` | none | produce the participant-to-group file (BLOCKED on `bio.csv`) |
| F5 | 21 | Per-patient AUROC / Brier where enough meals | `per_participant_metric_distribution` | COMPLETE (aggregate counts) | `tests/test_model_bc_compare.py` | none | run |
| F6 | 21 | Active-day vs sedentary-day split, per patient | `active_vs_sedentary_per_participant`, `src/glycotwin/models/activity_strata.py`, `docs/activity_definition.md` | COMPLETE in code | `tests/test_model_bc_compare.py`, `tests/test_quality_state_view.py` | none | run on the real files; decision D-10: confirm the median-split definition BEFORE seeing results |
| F7 | 21 | Cold-start (first 3) vs experienced (10+) | `cold_start_vs_experienced` | COMPLETE in code | `tests/test_model_bc_compare.py` | none | run |
| F8 | 21 | Posterior-width convergence; reconciliation hit-rate trend | `posterior_convergence`, `hit_rate_trend` | COMPLETE per participant | `tests/test_innovation_features.py` | none | pooled curves (G-6) |
| F9 | 22 | Key experiment A vs B vs C, calibration | `key_experiment_three_models` (`--model-a`) | COMPLETE in code; refuses unless A's shared events match B/C on participant, fold, label | `tests/test_model_bc_compare.py` | B vs C reported (inconclusive); A not run | run Model A, then the comparison |
| F10 | 22, 32 | Report a negative / inconclusive result honestly | `docs/model_b_vs_c_report.md` | COMPLETE | `tests/test_model_bc_compare.py` | reported | none |
| F11 | 21, 32 | Robustness: bootstrap seed, channel | `--seed-check`; `--channel Dexcom GL` runs the whole pipeline as a sensitivity analysis | PARTIAL: Dexcom sensitivity not run; fold-assignment variability not assessed | `tests/test_model_bc_compare.py` | none | run Dexcom pipeline; repeated fold seeds (G-5) |
| F12 | 32 | Gamma-exclusion sensitivity (researcher's own finding) | none | BLOCKED: the exclusion rule is not in the repository | none | reported only as text | D-11: supply the rule |
| G1 | 16 | SQLite schema, round-trip test | `src/glycotwin/backend/models.py`, `src/glycotwin/backend/store.py`, `docs/BACKEND.md` (8 tables, FKs, unique guards; persists across restarts) | PARTIAL: versioned twin, parameters, forecasts, observations, reconciliations, what-if and quality flags are stored; the blueprint's raw `glucose_readings` / `activity_readings` / `heart_rate_readings` / `meals` tables are deliberately not built (no raw participant data is stored) | `tests/test_backend.py` | none | decide whether a streaming readings table is wanted (it would hold raw CGM) |
| G2 | 15 | FastAPI endpoints, API tests | `src/glycotwin/backend/app.py`, `src/glycotwin/backend/routers/twins.py`, `src/glycotwin/backend/services.py` | PARTIAL: health, twin create/state/history, forecast, observe, reconcile, what-if, forecast list; NOT the blueprint's `/patients` list, `/timeseries`, `/ingest/*`, `/replay/*` or `/forecasts/{id}/explanation` | `tests/test_backend.py` | none | decide which remaining Part 15 endpoints are wanted |
| G3 | 17 | React dashboard, 13 screens | data functions exist for screens 3, 7-12 | NOT BUILT (instructed) | none | n/a | on instruction |
| G4 | 26 | Folder structure, configs, notebooks | package layout `src/glycotwin/...`; no `configs/*.yaml` | DEVIATION | `tests/test_project_config.py` | n/a | none |
| G5 | 30, 33 | README sections, architecture diagrams, model card | `README.md`, `docs/ARCHITECTURE.md` (text), `docs/model_card.md` | PARTIAL: no diagrams or screenshots; India-context numbers not sourced (Part 2I forbids an unsourced statistic) | `tests/test_docs_conformance.py` | n/a | diagrams; sourced ICMR-INDIAB reference if used |
| G6 | 30 | LICENSE, citations | none | BLOCKED (researcher's licence choice, H7) | none | n/a | D-12 |

## Novel contributions versus standard implementation
* **Research contributions (the blueprint's own claim, Part 5):** (1) carbohydrate sensitivity modelled as `beta + gamma * activity` with a personalised online posterior for a non-insulin population; (2) the experimental test of whether that conditioning improves calibration over an otherwise identical personalised model, on each person's own active-day meals. **The evidence so far is inconclusive** (nearly every paired interval contains zero; calibration point estimates slightly favour B). Only these two are research contributions; neither is demonstrated.
* **Architecture, not new mathematics:** the persistent versioned twin with an audit chain (blueprint Part 4's argument for "twin, not classifier"). The conjugate update itself is standard Bayesian linear regression; the blueprint says so.
* **Standard engineering features:** XGBoost baseline, TreeSHAP, calibration metrics, bootstrap intervals, dashboard, API, database, replay, data-quality flags, what-if (a closed-form function of the posterior).

## Remaining gaps, ranked
1. **No real-data validation of any new module** (adapter, comparison splits, replay) and Model A has no result here. Everything marked "none" in the Real data column.
2. **Grouped analyses and the blueprint prior need glycaemic groups** (`bio.csv` header names and participant-to-row alignment not inspectable here).
3. **Active-day versus sedentary-day result does not exist**; the definition (D-10) should be confirmed before it is run.
4. **Prior comparison (empirical-Bayes versus blueprint) not run** (runner options and the paired `scripts/compare_priors.py` exist; no real run yet); gamma width (D-2) unvalidated.
5. **Fold-assignment variability and Dexcom sensitivity not assessed.**
6. **Pooled convergence / hit-rate curves across participants** (G-6) not built; per-person versions exist.
7. **Quality-aware interval widening** deliberately absent (D-6).
8. Database, API, dashboard, diagrams, licence: not built or blocked.

## Decisions needed from the researcher
* **D-1** Fair real-data comparison of the empirical-Bayes and blueprint priors before either becomes the default (same events, folds, seed; report both).
* **D-2** gamma prior width (currently sd = 0.5 x |beta| / rms(activity)); confirm or give the intended value.
* **D-3** Sensor-gap limit: 15 min (current default) or the blueprint's 30 min (changes the event set; every real result would be regenerated).
* **D-4** Heart-rate deviation definition (resting HR source, window).
* **D-5** Whether a carbs-on-board absorption model is wanted (none is specified).
* **D-6** Whether to estimate quality-stratified interval coverage on real data and adopt a widening factor only if supported.
* **D-7** Whether any native-interval CGM export exists.
* **D-8** Add the 140 mg/dL secondary label (changes the event table schema).
* **D-9** Isotonic calibration for Model A (changes Model A's protocol).
* **D-10** Confirm the median-split active/sedentary definition before it is run on real data.
* **D-11** The gamma-exclusion rule behind the reported finding.
* **D-12** Licence.

## Results that need regenerating if a protocol decision changes
All real B/C/A outputs if D-3 changes the gap limit or if the event definition changes; B/C outputs if D-1 adopts the blueprint prior; Model A if D-9 adds isotonic calibration. Nothing was regenerated in this pass.

## Commands for the pending real-data experiments
The exact, unambiguous PowerShell commands (one run folder per analysis, explicit input and output paths, verification steps) are in `docs/REAL_DATA_RUNBOOK.md`. The earlier block that lived here is superseded: it left the group file undefined, ran the comparison twice onto the same report path, and relied on default paths and the Dexcom default channel of two scripts.

## Checklist
| | Implementation complete | Scientifically validated | Blocked / not done |
|---|---|---|---|
| β/γ personalisation, update, versioning, audit trail | yes | no real-data validation of the new twin modules; B-vs-C real result inconclusive | |
| Reconciliation, exclusion branch, replay | yes | no | |
| Uncertainty, convergence, hit-rate | yes (per person) | no | pooled curves |
| Data-quality warnings | yes (flag only) | no | interval widening (D-6) |
| What-if, explanation, SHAP (Model A) | yes | n/a | UI |
| Cold-start, active/sedentary, groups, Model A key experiment | tools yes | no (never run) | needs data, groups, D-10 |
| Blueprint prior | yes (opt-in) | no | D-1, D-2 |
| Database, API, dashboard | no | n/a | instructed |
| Native CGM, HR deviation, licence | no | n/a | D-4, D-7, D-12 |
