# Model B: personalised Bayesian carbohydrate sensitivity (no activity term)

**Status: H12 DECIDED (blueprint form, no intercept); real-data execution still BLOCKED until you review the implementation
and tests.** The sequential machinery is tested on synthetic data only. Model B is a research model and is not clinically validated.

## 1. Decision H12 (researcher, recorded)
The blueprint rise model is `rise = (beta + gamma * a) * carbs`; Model B is the gamma = 0 case. The earlier code added a
personalised intercept. **Primary specification: the blueprint form, `rise = beta_i * carbs`, with no intercept.** Implemented as
the design list `MODEL_B_DESIGN = ["carbs_g"]` (`models/model_b_cv.py`, from `bayesian.MODEL_B_BLUEPRINT_FEATURES`). Prior family,
Gaussian likelihood, conjugate update, posterior predictive, sequential procedure, folds and leakage protections are unchanged.

**Not yet aligned (flagged, not changed):** the legacy `bayesian.MODEL_B_FEATURES = ["intercept", "carbs_g"]` is still used by the earlier
prequential harness (`models/experiment.py`) and the in-memory twin store (`twin/state.py`), which couple Model B with Model C. They are
not used by `model_b_cv.py`; aligning them belongs with the Model C work.

## 2. Final formulation (Model B, blueprint form)
For participant i and meal j, with carbohydrate `c_ij` (g), lag-guarded pre-meal baseline `b_ij` and observed rise `r_ij = peak_ij - b_ij`:

- **Observation model:** `r_ij = beta_i * c_ij + e_ij`,  `e_ij ~ Normal(0, sigma^2)`, sigma^2 known (pooled within-participant residual
  variance of the fold's training participants, fitted through the origin).
- **Prior:** `beta_i ~ Normal(m_0, tau_0^2)`. Empirical-Bayes from the fold's training participants only: `m_0` = pooled least squares
  through the origin; `tau_0^2` = between-participant variance of per-participant slopes minus their average sampling variance, floored
  to stay positive (`fit_population_prior`; diffuse fallback flagged in `prior_source` if fewer than 5 usable participants).
- **Update after observing meal j (only once its window (t0, t0+120 min] has closed, and after its own forecast):**
  `1/tau_j^2 = 1/tau_{j-1}^2 + c_ij^2 / sigma^2`
  `m_j = tau_j^2 * ( m_{j-1} / tau_{j-1}^2 + c_ij * r_ij / sigma^2 )`
- **Prediction for the next meal (carbs c, baseline b), from the current posterior (m, tau^2):**
  `r ~ Normal( m * c,  sigma^2 + c^2 * tau^2 )`
  `P(peak >= 180) = P(b + r >= 180) = Phi( (b + m * c - 180) / sqrt(sigma^2 + c^2 * tau^2) )`
  90% predictive interval for r: `m * c +/- 1.645 * sqrt(sigma^2 + c^2 * tau^2)`.
  With c = 0 the predicted rise is exactly 0 and only the noise sigma remains (a consequence of the no-intercept form).
- **Inputs:** `carbs_g` only in the regression; `baseline_glucose` only in the threshold conversion; the observed rise only for updates.
  No intercept, no activity, no label input.

## 3. Sequential protocol (`models/model_b_cv.py`, `scripts/run_model_b.py`)
1. Same participants, core-eligible Libre events, group-stratified participant folds and seed as Model A (identical fold hash).
2. For fold k: fit the prior on the other folds' participants. Validation participants never touch it.
3. Each validation participant starts from that prior. Events are sorted by `meal_time`. Before forecasting an event at t, the
   updates of earlier events whose window (t0, t0+120 min] has closed by t are applied; then the event is forecast; only then is
   its own update queued. Later validation events therefore use earlier validation observations (online learning), and nothing
   later than t is ever used. One participant's data never updates another's state.
4. Outputs per event: probability, predicted rise and 90% interval, posterior carb-sensitivity mean/SD at forecast time, number of
   own observations used, posterior version; plus a never-updated "frozen prior" forecast as a control.
5. Evaluation: Model A's metric bundle (ROC-AUC, PR-AUC, Brier, log loss, ECE, calibration slope/intercept, confusion matrix at 0.5
   and at training-fold prevalence, prevalence), per fold, per group, participant-clustered bootstrap; rise MAE and 90%-interval
   coverage; paired participant-clustered differences B vs A (Brier, log loss) and B vs its frozen prior (Brier, log loss, MAE).
   An interval containing zero is inconclusive. No superiority claim from one metric.
6. Personalisation evidence (aggregate only): observations per participant, participants with at least 1/3/5/10/20 observations,
   prior by fold, final posterior sensitivity distribution, final-minus-prior change, posterior/prior SD ratio, between-participant
   spread. Individual trajectories go to a git-ignored local file.

**Not done:** the in-memory `TwinStore` couples Models B and C (it forecasts and updates both, and C needs finite activity), so
Model B is not yet wired into it; posterior versions are recorded in the trajectory file instead.

## 4. Distinctions
- **Model A:** population XGBoost on carbs, baseline and activity; no personal history.
- **Model B:** personal carb sensitivity learned online from the person's own earlier meals; no activity term.
- **Model C (later):** Model B plus an activity-dependent sensitivity term.

## 5. Limitations
No intercept: any rise not proportional to carbohydrate (protein/fat effects, baseline drift, measurement offset) goes into the residual
and into beta, so beta is "rise per gram" through the origin, not a pure carbohydrate effect. Gaussian, constant-variance rise and known
noise variance (R14); no forgetting (sensitivity assumed constant over the 10 days);
the update uses only core-eligible (isolated) meals; probabilities are raw; Libre primary is PROPOSED (D14); results are
channel-conditional; synthetic tests prove the code, not the science.

## 6. Re-run on Model C's exact event subset (paired B-vs-C preparation)
`python scripts\run_model_b.py --population activity-eligible` runs Model B, unchanged, on exactly Model C's events (core-eligible AND activity-eligible).
- The folds are built from ALL core-eligible participants (new optional `fold_group_of` argument of `run_model_b`; the default path is unchanged), so they are
  identical to Models A and C even if a participant has no activity-eligible events (tested: without the argument the folds would drift).
- Outputs carry an `_activity_eligible` suffix and never overwrite the original core-eligible run (`model_b_<channel>.json`, the forecasts CSV and the trajectories file keep their names).
- The report manifest records the population, the core event count and the number of events dropped for missing or low-coverage activity.
- `model_c_cv.compare_c_to_b` pairs the two forecast files on identical events and refuses the core-eligible B run.
Model B still never reads activity; its formulation, prior and results are unchanged.

