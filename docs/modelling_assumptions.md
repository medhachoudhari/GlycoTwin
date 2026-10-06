# Modelling assumptions and open decisions

Status: the research/twin core is tested on **synthetic data only**. No real CGMacros file
has been inspected, so every item below marked UNVERIFIED depends on the real schema or on
the GlycoTwin Master Blueprint, which was not available when this was written.

## Verified by tests (mathematical properties, synthetic data)
- The conjugate update equals the closed-form formula and the ridge/MAP solution; sequential
  single-meal updates equal one batch update and are order-independent.
- `forecast_exceeds_180` equals the Monte-Carlo frequency of `baseline + rise > 180` under
  the model, and its 90% interval has 90% predictive coverage.
- Under a correctly specified simulation, leave-one-participant-out forecasts are calibrated
  (interval coverage ~0.90, small ECE). This says nothing about real data.
- The experiment machinery detects an activity interaction when one is simulated, and does
  not invent one when it is absent.

## Assumptions that remain (UNVERIFIED against the blueprint / real data)
1. **Target.** `label = 1[baseline + peak_rise > 180]` with `peak_rise = max(CGM in the 2 h
   window) - baseline`. Whether the blueprint wants "exceeds" or "crosses" is unconfirmed.
   If baseline is already >= 180 the label is trivially 1; such meals probably need excluding
   or flagging by the adapter.
2. **Gaussian, constant-variance peak rise.** A maximum over a window is non-negative and
   likely right-skewed, with variance probably growing with carbs. The probability is exact
   only for the Gaussian model, not for real peaks.
3. **Known noise variance** (estimated once from within-participant residuals). Needed for the
   closed-form update; understates uncertainty if the variance is mis-estimated.
4. **Between-participant spread is estimated from few participants** and projected to
   positive-semidefinite, which inflates it slightly (conservative: weaker shrinkage). Expect a
   noisy estimate at CGMacros scale. With < 5 usable participants the prior is diffuse
   (`prior_source == "diffuse_fallback"`) and early forecasts are near-uninformative.
5. **Model C has an interaction but no activity main effect.** A true main effect of activity
   on the rise could be absorbed by the interaction coefficient. Confirm the intended form.
6. **"Active day" vs `activity_level`.** The key experiment compares active-day and
   sedentary-day meals; the code uses a per-meal pre-meal activity summary and a threshold
   parameter. Whether "active day" is a day-level or meal-level quantity, the window, units
   and threshold are undecided pending the audit and the blueprint.
7. **No forgetting.** The posterior only gains precision, so a participant whose sensitivity
   drifts adapts ever more slowly. If "adaptive" in the blueprint means time-varying
   sensitivity, a discount/forgetting factor is required.
8. **Model A comparability.** A is a classifier on (carbs, baseline, activity) trained on
   pooled meals with no personal history and no recalibration; B/C use baseline only through
   the threshold conversion. A fair calibration comparison may need A recalibrated
   (e.g. isotonic/Platt on training data only).
9. **Experiment inference is missing.** There is no participant-clustered/paired bootstrap yet,
   so calibration differences between models cannot be given confidence intervals. Do not
   report an improvement without one.

## Adapter responsibilities (cannot be enforced in the core)
- `activity_level` must be computed only from data before `meal_time`; `baseline_glucose` at
  or before it.
- Flag meals with incomplete CGM coverage of the 2 h window, and meals whose window contains
  another meal (the peak is then not attributable to one meal).
- `meal_time` may be privacy-shifted per participant: never compare times across participants.
