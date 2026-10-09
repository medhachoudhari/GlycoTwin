# Model card: GlycoTwin Models B and C (research prototype)

- **Intended use:** research comparison of a personalised carbohydrate-sensitivity model (B) with one that adds a pre-meal activity interaction (C).
  **Not** for clinical use, dosing, diagnosis, or advice.
- **Data:** CGMacros (45 participants; 34 activity-eligible participants and 963 events in the reported comparison). Primary channel Libre (D14, proposed); Dexcom is a sensitivity analysis.
- **Target:** anchor = `Meal Type` row timestamp; window (t0, t0+120 min]; label 1 if the maximum available glucose >= 180 mg/dL.
- **Models:** B `rise = beta_i * carbs`; C `rise = (beta_i + gamma_i * activity) * carbs`. Gaussian, known noise variance, no intercept, empirical-Bayes prior from training participants, conjugate sequential updates.
- **Evidence:** `docs/model_b_vs_c_report.md`. The paired comparison is **inconclusive**: nearly every interval contains zero. Calibration was not improved.
- **Lifecycle:** a meal whose outcome window is untrustworthy (for example a sensor gap) is marked excluded and never updates the twin.
- **Known limitations:** 34 participants; label is a lower bound; self-reported macronutrients; wrist-device activity; gamma may be weakly identified and correlated with beta;
  Libre and Dexcom disagree on the label in about 23% of matched events; single fold assignment; no multiplicity adjustment.
- **What-if and explanation outputs** describe the model, not the person, and are not causal.
- **Prior options for the twin:** empirical-Bayes (used in the research runs) or the blueprint's stratified-regression / gamma-centred-at-0 prior (`docs/blueprint_prior.md`, not evaluated on real data).
- **Research-run prior options:** `--prior-scheme blueprint` (and Model C `--gamma-relative-sd` 0.25/0.5/1/2) are opt-in sensitivity analyses; the primary protocol uses empirical-Bayes priors.
- **Active vs sedentary:** relative to each participant's own median pre-meal activity (`docs/activity_definition.md`); not yet run on the real forecast files.
- **Data quality:** forecasts carry low-quality and insufficient-history warnings; the probability and interval are not adjusted for them.
