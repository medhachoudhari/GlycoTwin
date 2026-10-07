# Model C: activity-conditioned personalised Bayesian carbohydrate sensitivity (the main innovation experiment)

**Status:** implemented and tested on synthetic data only. **No real-data run has been made.** Model C is a research model and is not
clinically validated. The paired C-versus-B comparison needs Model B re-run on the exact same activity-eligible event subset (separate step).

## 1. Locked specification (decisions B1 to B6)
- **B1** un-centred activity, no intercept. **B2** raw pre-meal `activity_level` (no [0,1] normalisation); prior regularisation is scale-aware.
- **B3** population = core-eligible AND activity-eligible events. **B4** unstratified empirical-Bayes prior, as in Model B.
- **B5** gamma's between-participant spread is estimated empirically and reported (nothing prespecified).
- **B6** report the participant and event counts supporting identifiable beta and gamma; no extra arbitrary minimum.

## 2. Equations
For participant i, meal j: `c` = carbs_g, `a` = `activity_level` (mean raw METs over the four hours strictly before the meal row, D6), baseline `b`, rise `r = peak - b`.

- **Observation model:** `r_ij = (beta_i + gamma_i * a_ij) * c_ij + e_ij = beta_i * c_ij + gamma_i * (c_ij * a_ij) + e_ij`, `e_ij ~ Normal(0, sigma^2)`, sigma^2 known.
  Design `x = [c, c*a]`, coefficients `theta_i = (beta_i, gamma_i)`. No intercept, no activity main effect.
- **Prior:** `theta_i ~ Normal(mu_pop, Sigma_between)`, fitted on the fold's training participants only (section 3).
- **Update after meal j** (once its window (t0, t0+120 min] has closed, and after its own forecast):
  `Sigma_j = (Sigma_{j-1}^-1 + x x^T / sigma^2)^-1`,  `mu_j = Sigma_j (Sigma_{j-1}^-1 mu_{j-1} + x * r / sigma^2)`.
- **Prediction for a new meal (c, a, baseline b) from the current posterior (mu, Sigma):**
  `r ~ Normal(x^T mu, sigma^2 + x^T Sigma x)`, with `x^T mu = (mu_beta + mu_gamma * a) * c`;
  `P(peak >= 180) = P(b + r >= 180) = Phi( (b + x^T mu - 180) / sqrt(sigma^2 + x^T Sigma x) )`.
  With c = 0 the predicted rise is 0 and only sigma remains. Baseline enters only this threshold conversion; the observed rise is used only after the forecast.
- **Nesting:** with the gamma prior pinned at mean 0 and variance 0, Model C equals Model B exactly (tested).

## 3. Prior and scale-aware regularisation (`fit_scale_aware_prior` in `models/model_c_cv.py`)
All quantities come from the fold's training rows only.
1. `mu_pop` = pooled least squares of the rise on `[c, c*a]` (no intercept).
2. For every training participant with more than 2 events and a rank-2 design, fit least squares; `sigma^2 = sum(RSS_i) / sum(n_i - 2)` (pooled within-participant residual variance; fixed, never updated).
3. `S_obs` = covariance of those per-participant coefficient vectors; `S_samp` = mean over participants of `sigma^2 (X_i^T X_i)^-1`; `S_raw = sym(S_obs - S_samp)`.
4. **Regularisation (replaces the unit-dependent coefficient floor):** let `D = diag(rms(c), rms(c*a))` over the training rows, so `D theta` is an effect on the rise in mg/dL.
   Eigen-decompose `D S_raw D`, raise every eigenvalue below `floor = 1e-3 * trace(D S_obs D) / 2` up to `floor`, and map back: `Sigma_between = D^-1 (floored) D^-1`.
   The 1e-3 is a dimensionless ratio (the same ratio Model B's floor uses). Because `D` absorbs the unit of the activity, multiplying activity by any factor `s` divides gamma by `s` and leaves
   the effect-space matrix, the floor and every forecast unchanged (tested for s = 0.1, 10 and 1000, including a case where the floor is active).
5. **Fallback** (fewer than 5 usable participants): `Sigma_between = D^-1 (1e4 I) D^-1`, flagged in `prior_source` (`diffuse_fallback`).
`fit_population_prior` (used by Model B) is unchanged.

## 4. Protocol (`models/model_c_cv.py`, `scripts/run_model_c.py`)
Same participants, group-stratified 5-fold participant CV and seed 0 as Models A and B. The folds are built from ALL core-eligible participants (identical fold hash), then restricted to activity-eligible events.
Sequential forecast, observe, update, participant isolation and leakage rules are those of Model B. Validation participants never influence `mu_pop`, `Sigma_between`, `sigma^2` or the effect scales (independent-recomputation and validation-perturbation tests).
Events with missing or low-coverage activity (`eligible_activity == False`) are dropped, never imputed; the number dropped is reported.

## 5. What is reported (aggregate only)
Model A's metric set for Model C; per fold and per group; participant-clustered intervals; rise MAE and 90% interval coverage; C versus its own never-updated prior (paired); and
- beta and gamma population mean and between-participant SD (prior, across folds and per fold), sigma;
- the raw between-participant variance before regularisation, the share of gamma's observed spread that is sampling noise, the number of eigenvalues raised to the floor;
- posterior beta and gamma SD at forecast time and final; final-minus-prior beta and gamma; final-over-prior SD ratios;
- participants whose own events identify both coefficients (more than 2 events, rank-2 design); events per participant; personal observations available at forecast time.
Individual trajectories go to a git-ignored local file.

## 6. Limitations and open points
Gaussian, constant-variance rise and known noise variance (R14); no forgetting; the active-versus-sedentary definition is not locked and no such subgroup is reported;
only isolated (core-eligible) meals update the posterior; probabilities are raw; Libre as primary is PROPOSED (D14); the legacy intercept-based harness (`models/experiment.py`), twin store (`twin/state.py`) and
simulator are not yet aligned with this form (legacy alignment work, flagged); gamma may be weakly identified at about 28 events per participant and the empirical gamma spread may be dominated by sampling noise: read the reported noise share before interpreting any gamma.
