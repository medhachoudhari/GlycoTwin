# Evidence map: where every number in the video comes from

Three kinds of statement appear in the video and are kept separate:
**Research** (CGMacros, the researcher's local runs, recorded in repository documents), **Application demonstration** (values entered by hand during the recording; the numbers on screen are the application's real outputs) and **Verification** (automated tests).
No participant-level record is shown anywhere in the video. This map covers the current video (`video/GlycoTwin_demo_subtitled.mp4`, 15:34), which opens on the real GlycoTwin landing page and walks through the application as a first-person, conversational demo.

## Research on CGMacros (documented, not recomputed for the video)
| Statement in the video | Source file | Note |
|---|---|---|
| 45 participants; about ten days of minute-level rows each | `data/audit/dataset_aggregate_summary.md` | 7 of 45 files have fewer than 14,400 rows (10 days at one row per minute); median 14,805 |
| 687,580 rows in total; 5,655 to 18,735 per participant | same | Committed aggregate audit (derived from a real-run inventory) |
| Two CGMs (Libre GL, Dexcom GL), activity (METs), heart rate, logged macros, meal photos | `docs/primary_channel_decision.md` section 2; `docs/data_validity_rules.md` | From the dataset README as read by the project |
| Photos never opened; "Amount Consumed" never a feature | `data/audit/dataset_aggregate_summary.md`; decision D7 in `docs/data_validity_rules.md` | |
| CC BY-NC-SA 4.0 licence | `README.md` (Data privacy and licensing) | |
| Anchor t0 = `Meal Type` row; window (t0, t0+120 min]; label = max ≥ 180 mg/dL | `docs/data_validity_rules.md` D1, D3, D9 | The release has no meal-end field (section B) |
| Baseline lag guard; no imputation; gap rules; isolated meals; activity = 4 h mean METs, ≥ 50 % coverage | `docs/data_validity_rules.md` D2, D4, D5, D6, D10 | |
| Libre: 1,706 meal rows; 1,697 extraction-valid; 1,262 core-eligible; 301 positive; 961 negative | `docs/primary_channel_decision.md` section 2; `docs/PROJECT_STATUS.md` (researcher-run entry) | "Reported" by the researcher; the JSON reports are not committed |
| Dexcom: 1,666 / 1,230 / 534 / 696 | same | |
| Sensors disagree on the label for 23.1 % of 1,229 matched events; κ ≈ 0.50 | `docs/primary_channel_decision.md` | |
| Leakage check passed for 45 of 45 participants on both sensors | `docs/primary_channel_decision.md` section 2 | Researcher-run; mutation test in `tests/test_leakage_check.py` |
| Participant-level folds, stratified by A1c group; sequential evaluation | `docs/model_a.md`, `docs/model_b.md`, `docs/model_b_vs_c_report.md` | |
| 963 events, 34 participants; B vs C table (AUC 0.7943 / 0.8059, +0.0116 [−0.0084, +0.0479] and the rows below it); 8 of 9 intervals contain zero | `docs/model_b_vs_c_report.md` sections 1, 2 | "Produced by the researcher's local runs ... Nothing here was recomputed in the engineering environment" |
| Each model vs its frozen prior (Brier −0.0103 / −0.0108; MAE −1.60 / −1.59, all intervals contain 0) | same, section 3 | |
| Shuffled-history, running-rate, population-XGBoost comparison: implemented, no real-data run in the repository | `docs/INNOVATION_ROADMAP.md`, `docs/model_a.md`, `docs/PROJECT_STATUS.md` | The video reports no numbers for it |

## Application demonstration (read from the real application during the recording)
| On screen | Checked by |
|---|---|
| Model B β 0.747 ± 0.187 at version 0; 0.950 ± 0.144 at version 1 | Recorder assertion on the My Twin table |
| First forecast: Model B expected maximum 155, 90 % interval 126–184, P(max ≥ 180) = 7.7 % | Recorder assertion |
| Second forecast, same inputs: 167, 140–194, 21.0 % | Recorder assertion |
| Explanation (carbohydrate term about 63, activity term about −4, 30 % of variance from parameter uncertainty) | Read from the Forecast page text of the second forecast |
| Forecast versus outcome: observed rise 75.0 mg/dL, outside the 90 % interval | Recorder assertion on the Insights table |
| Twin still at version 1 after signing out and in | Recorder assertion on the My Twin table |
| Entered by hand: 60 g, activity 0.3, glucose 110 mg/dL, meals 2026-01-01 08:00 and 12:00 UTC, observed maximum 185 mg/dL | Recording script (`tools/record.py`) |

The twin in the recording starts from the application's built-in demonstration prior (the interface labels it synthetic). The research numbers above do **not** come from this twin, and the hand-entered values are not a participant's observations.

## Verification
| Statement | Source |
|---|---|
| 815 Python tests and 37 frontend tests passed | Runs recorded in the project history on Linux with temporary databases (see `docs/GLYCOTWIN_COMPLETE_TEST_REPORT.md`, `docs/PROJECT_STATUS.md`) |
| Live twin and research runs share `conjugate_update` and `forecast_exceeds_180` | `src/glycotwin/models/bayesian.py`, used by `models/model_b_cv.py`, `models/model_c_cv.py`, `twin/state.py` |
