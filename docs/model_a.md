# Model A: population-level XGBoost baseline (research baseline)

**Status:** implemented and tested on synthetic data; **not yet run on the real event table** (the table lives on the researcher's machine).
Model A is a research baseline for the Model B/C comparison. It is **not clinically validated** and gives no medical advice.

## 1. Purpose
Predict the binary event "maximum available Libre glucose in (t0, t0 + 120 min] is at least 180 mg/dL" from information available at the logged
meal-row time t0, with **no personalisation**. It is the non-personalised comparison point for Models B and C, not an attempt at the best classifier.
Definitions are unchanged (D9/D10): anchor = `Meal Type` row timestamp; window (t0, t0+120]; target = max available glucose >= 180; invalid windows excluded
as in the event table; no `meal_end`; no photo pairing. Primary channel: **Libre GL** (D14, PROPOSED, not locked). Dexcom is a later sensitivity analysis; channels are never averaged.

## 2. Evaluation protocol (`src/glycotwin/models/model_a_cv.py`, `scripts/run_model_a.py`)
1. **Population:** the core-eligible events of the local event table for the channel (`eligible_core == True`). Events with a missing predictor stay in (see 3).
2. **Groups:** `bio.csv` column `A1c PDL (Lab)`: healthy < 5.7; pre-diabetes 5.7 to 6.4 inclusive; t2d > 6.4 (rule from the authors' notebook; cohort 15 / 16 / 14).
   Participants are linked to `bio.csv` rows through the identifier column (`subject`) only. A positional mapping is never used; if no unique identifier column matches, the run stops.
3. **Folds:** participant-level, stratified by the participant's group: `StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)` over participants sorted by id
   (so row order is irrelevant). Default seed 0. Each participant is in exactly one fold, so no participant is in both training and validation. A group with fewer than 5 participants is refused.
4. **Out-of-fold predictions:** for each fold k, fit on the other four folds' participants and predict fold k. Every event receives exactly one prediction from a model that never saw that participant (asserted in code and tests). Training-set metrics are not results.
5. **Pooled metrics** are computed on all out-of-fold predictions; per-fold and per-group results are reported alongside. Participant-clustered bootstrap 95% intervals (1,000 draws, seeded) are given for ROC-AUC, average precision and Brier score.

## 3. Feature policy
- **Features (exactly three, from the repo's documented Model A):** `carbs_g`, `baseline_glucose`, `activity_level`. These are the same inputs the Bayesian models can use, so the later comparison isolates personalisation.
- All three come from the event table, which keeps its leakage safeguards: baseline from data at or before t0 minus the channel lag; activity = mean METs over the four hours strictly before t0.
- **Never used:** the target and its derivatives (`peak_glucose`, `peak_glucose_rise`, `n_window_readings`, `window_completeness`), eligibility columns, identifiers, timestamps, group labels, `Amount Consumed`, image paths, `label_raw`, `label_norm`. `assert_feature_policy` enforces this and the tests check it.
- **Missing predictors:** kept as NaN and passed to XGBoost's native missing-value handling. Nothing is imputed. The share missing per feature is reported.
- No new features, no feature selection.

## 4. Model configuration (fixed, untuned)
`PopulationBaselineModel` with `n_estimators=100, max_depth=3, learning_rate=0.1, objective=binary:logistic, eval_metric=logloss, random_state=0, n_jobs=1`; every other XGBoost parameter at its library default.
No class weights, no resampling, no threshold change, no hyper-parameter search. Probabilities are raw (no isotonic/Platt recalibration yet).

## 5. Metrics
ROC-AUC, average precision (PR-AUC), Brier score (and the Brier score of a constant-prevalence forecast for reference), log loss, expected calibration error (10 and 5 bins),
calibration slope and intercept (logistic recalibration on logit(p); ideal 1 and 0), reliability bins, mean predicted probability against prevalence, and, at fixed decision thresholds, the confusion matrix, sensitivity (recall), specificity, precision and F1.
Two thresholds are fixed in advance and both are reported: **0.5**, and **the training-fold prevalence**. Neither is tuned on the out-of-fold results.
A metric that cannot be computed (one class, no predicted positives, and so on) is reported as `null` with the reason, never dropped.
AUROC/PR-AUC are not reported when a subset has fewer than 2 events of either class.

## 6. Reproducibility
The report's `manifest` records: seed, fold method, a SHA-256 of the fold assignment, the feature columns, every XGBoost parameter, library versions (Python, numpy, pandas, scipy, scikit-learn, xgboost),
a SHA-256 fingerprint of the event-table columns Model A uses, the event-table file name, the missing-value and class-imbalance policies, the decision thresholds and the git commit (and whether the tree was dirty).
Participant-level files (fold assignment, out-of-fold predictions) are written to git-ignored local folders; printed output is aggregate only.

## 7. Limitations and open points
1. **Feature set:** the blueprint PDF could not be re-read in the engineering environment; the three-feature set is the repo's documented Model A (and the code, tests and status tracker agree). If the blueprint lists more inputs, that is a decision for you (the other event-table features, such as macros, trend slope and the 1 h / 24 h activity means, are *not* used; D12 keeps the extra activity windows exploratory).
2. **Thresholds and hyper-parameters** are conventions chosen here (0.5 and training prevalence; the repo's earlier fixed configuration), not blueprint-verified values.
3. **Libre as primary** is D14, PROPOSED. Labels agree only moderately across channels (kappa about 0.50), so every Model A result is channel-conditional.
4. **Small effective sample:** about 45 participants, of whom only some have both classes; per-participant calibration is not estimable and group results (healthy, pre-diabetes, t2d) are descriptive only; no superiority or significance is claimed.
5. **Dependence:** events from one person are correlated; the participant-level folds and the clustered bootstrap address leakage and interval width, but pooled metrics still weight participants by their number of events.
6. **Fold variability:** one seed is the default; the variability of metrics across fold assignments is not assessed unless you rerun with other seeds.
7. **Selection:** `eligible_core` includes the "isolated meal" rule, which depends on the next meal (R7); results apply to isolated meals only.
8. **Activity coverage:** `activity_level` is the mean of available METs; events with sparse coverage still carry a value (coverage is stored but not a feature).
9. **Calibration:** raw boosted-tree probabilities are often over-confident; calibration is measured, not corrected. The interpretation of any real-data result is pending your review.
