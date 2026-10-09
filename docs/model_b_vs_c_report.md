# Model B versus Model C: matched real-data comparison (Libre channel, activity-eligible events)

**Status:** research report. **Not clinically validated; no clinical claim is made.** The numbers below were produced by the researcher's
local runs and supplied to this repository as text; the participant-level forecast files and full JSON reports are not in Git. Nothing here was
recomputed in the engineering environment. Items the researcher has not supplied are marked **NOT AVAILABLE** and are left empty rather than estimated.
The repository now contains `scripts/compare_models_b_c.py`, which regenerates these tables from the two local forecast files and refuses to run unless the
events, participants, folds and labels match (not yet run on the real files in this environment).

## 1. Design of the comparison
- **Question (blueprint):** does conditioning the personal carbohydrate sensitivity on pre-meal activity (Model C) improve forecasts of the 2-hour
  "peak >= 180 mg/dL" event over an otherwise identical personalised model without the activity term (Model B)?
- **Model B:** `rise = beta_i * carbs`. **Model C:** `rise = (beta_i + gamma_i * activity) * carbs` (no intercept; raw, un-centred 4 h pre-meal mean METs).
  Both: Gaussian likelihood, unstratified empirical-Bayes prior fitted on training participants only, conjugate sequential update, `P(event) = Phi((baseline + predicted rise - 180) / predictive sd)`.
  See `docs/model_b.md` and `docs/model_c.md`.
- **Matched evaluation:** the same **963 meal events from 34 participants**, identical outcomes and identical participant-level folds (seed 0, stratified by A1c group), primary channel Libre (decision D14, PROPOSED).
  Model B was re-run on exactly Model C's activity-eligible events.
- Metrics are out-of-fold and sequential: every forecast uses only information available before that meal. Intervals are participant-clustered percentile bootstrap 95% intervals (seed 0).
  Differences are **C minus B**; for the loss-type metrics (Brier, log loss, ECE, MAE) negative favours C.

## 2. Primary results (as supplied)
| Metric | Model B | Model C | C minus B | 95% CI | Excludes 0? |
|---|---|---|---|---|---|
| ROC-AUC | 0.7943 | 0.8059 | +0.0116 | [-0.0084, +0.0479] | no |
| PR-AUC | 0.5792 | 0.5890 | +0.0098 | [-0.0109, +0.0356] | no |
| Brier score | 0.1391 | 0.1379 | -0.0012 | [-0.0064, +0.0030] | no |
| Log loss | 0.4510 | 0.4500 | -0.0010 | [-0.0210, +0.0151] | no |
| ECE, 10 bins | 0.0455 | 0.0484 | +0.0029 | [-0.0145, +0.0179] | no |
| ECE, 5 bins | 0.0393 | 0.0460 | +0.0067 | [-0.0077, +0.0176] | no |
| Rise MAE (mg/dL) | 29.3962 | 29.5103 | +0.1142 | [-0.5234, +0.6760] | no |
| Mean rise error, predicted minus observed (mg/dL) | -9.0834 | -8.1290 | +0.9543 | [+0.0055, +2.2641] | **yes (lower bound barely above 0)** |
| 90% predictive-interval coverage (nominal 0.90) | 0.8951 | 0.8941 | -0.0010 | [-0.0135, +0.0122] | no |

(The supplied MAE and mean-error differences differ from the subtraction of the rounded model values by 0.0001, which is rounding.)

### 2.1 Reading the table
- **Eight of the nine intervals contain zero**, including every discrimination (AUC, PR-AUC), probability-loss (Brier, log loss), calibration (ECE) and accuracy (MAE) comparison. The participant-clustered bootstrap did **not** establish overall predictive superiority of C over B.
- **Calibration, the blueprint's stated target, is not improved:** both ECE point estimates are slightly *worse* for C (+0.0029 and +0.0067), with intervals that contain zero. The Brier score, which mixes discrimination and calibration, is marginally better for C (-0.0012), also with an interval containing zero.
- **Mean rise error** is the only interval excluding zero. Both models under-predict the rise on average (B by 9.1 mg/dL, C by 8.1 mg/dL); C's difference means a small reduction in negative bias of about 1 mg/dL. This is a bias measure, not an accuracy measure, MAE did not improve, and with nine intervals reported and no multiplicity adjustment one barely-excluding interval is not evidence of superiority.
- Predictive-interval coverage is close to nominal for both (0.895 versus 0.90) and equal.

## 3. Each model against its own never-updated prior (as supplied)
Difference = updated model minus its frozen population prior; negative favours the updated (personalised) model.
| | Brier | Log loss | Rise MAE (mg/dL) |
|---|---|---|---|
| Model B | -0.0103 [-0.0229, +0.0019] | -0.0198 [-0.0627, +0.0310] | -1.6000 [-3.2052, +0.0776] |
| Model C | -0.0108 [-0.0235, +0.0011] | -0.0240 [-0.0623, +0.0177] | -1.5888 [-3.3045, +0.1686] |

All six point estimates favour personal updating, and the C point estimates are about as large as B's, but **no interval excludes zero**, so even the benefit of personalisation itself is not statistically established in this sample for either model. (The B and C updating benefits are nearly the same size, which is consistent with the activity term adding little beyond personal carbohydrate sensitivity.)

## 4. Exploratory and sensitivity findings (as supplied; post hoc unless stated)
- **Extreme gamma:** C's small aggregate advantage **disappeared after excluding participants with extreme estimated gamma**. NOT AVAILABLE: the exclusion rule, the number excluded, the metric values after exclusion, and whether this analysis was prespecified (if not, it is post hoc and must be labelled so).
- **Activity tertiles** (qualitative, point estimates only): in the **low-activity tertile** C performed better on AUC, Brier and MAE; in the **middle tertile** results were approximately equal; in the **high-activity tertile** B performed better on AUC, Brier and MAE. NOT AVAILABLE: the numeric values, confidence intervals, the tertile definition (pooled or training-fold cut points) and event and participant counts per tertile. The opposite directions at the extremes would offset in an aggregate comparison; that is a pattern to examine, not a finding.
- **Participant-level rise MAE:** C improved by more than 1 mg/dL for **5** participants, worsened by more than 1 mg/dL for **11**, and was within +/-1 mg/dL for **18** (34 in total). More participants were made worse than better.
- **Glycaemic-group breakdown (healthy, pre-diabetes, T2D):** NOT AVAILABLE.

## 5. Identifiability of gamma
- 963 events over 34 participants is about 28 events per participant (arithmetic). Gamma multiplies `carbs x activity`; it is learned from within-person co-variation of meal size and 4-hour mean METs, a low-contrast signal. Because activity is positive, the two regressors (`carbs` and `carbs x activity`) are correlated, so the posteriors of beta and gamma are expected to be negatively correlated.
- **Gamma may be weakly identified and correlated with beta; individual gamma estimates must not be interpreted as established physiological or causal evidence.** Whether this holds here is exactly what the Model C run's diagnostics measure: the share of gamma's observed between-participant spread that is sampling noise, the number of eigenvalues raised to the regularisation floor, and the number of participants whose own events identify both coefficients. **NOT AVAILABLE** in this repository; they must be read before any statement about gamma is made.
- That the advantage vanished when extreme-gamma participants were removed is *compatible with* a small number of poorly identified, large-gamma participants driving the aggregate difference. It does not demonstrate it.
- The activity variable is a wrist-device MET mean over a fixed 4-hour window; measurement error in a covariate attenuates any true interaction.

## 6. Conclusions that the evidence supports
Using the decision rules fixed in advance (`docs/INNOVATION_ROADMAP.md` section 3):
1. **Inconclusive.** The paired interval for every predictive metric (discrimination, probability loss, calibration, accuracy) contains zero; point differences are tiny (about 0.01 AUC, 0.001 Brier and log loss, 0.11 mg/dL MAE) and not in a consistent direction (C better on AUC, PR-AUC, Brier, log loss; B better on ECE and MAE).
2. The roadmap's criteria for "supported" are **not met**: they require C to beat B on active meals with an interval excluding zero, and to beat its own frozen-prior variant; no such interval has been shown, the active-meal analysis is only available as unquantified tertile point estimates, and the aggregate advantage did not survive excluding extreme-gamma participants.
3. This is neither evidence that the activity interaction improves calibration nor evidence ruling out a small effect that 34 participants and about 28 events each could not detect.
4. Nothing here supports clinical use, individual-level conclusions, or causal statements about activity and glucose.

## 7. Hypotheses (not tested, not results)
- H1: an activity effect exists but is small relative to meal-to-meal noise, so about 28 meals per person cannot resolve it.
- H2: the effect differs by activity level (helping at low activity, hurting at high), which an aggregate comparison would average away; the tertile pattern is compatible with this but is exploratory and unquantified here.
- H3: the 4-hour mean-METs window is a poor proxy for the physiology that matters (timing, intensity, type); other windows or heart-rate-based measures might carry more signal.
- H4: the effect differs by glycaemic group, which an unstratified prior blurs.
- H5: model misspecification (Gaussian, constant variance, no intercept, no forgetting) limits what an interaction term can add.
Each would need its own prespecified analysis; none is a finding of this comparison.

## 8. Limitations
Single dataset and one primary channel (Libre; Dexcom is a prespecified sensitivity analysis and the channels disagree on the label in about 23% of matched events); 34 participants; isolated meals only (selection depends on the next meal);
label is the maximum available glucose (a lower bound); self-reported macronutrients; activity from a wrist device; Gaussian rise model with known noise variance; no multiplicity adjustment across the nine metrics (and the fifteen intervals reported across sections 2 and 3);
one fold assignment (seed 0), so fold-assignment variability is not assessed; binned ECE is noisy at this sample size; sections 4 and 7 are exploratory.

## 9. What is still missing from the repository
NOT AVAILABLE and to be added from the researcher's local reports when wanted: tertile numbers, cut points and counts; the gamma-exclusion rule, count, post-exclusion metrics and prespecification status; the gamma-spread diagnostics (sampling-noise share, eigenvalues floored, participants with both coefficients identifiable); per-group results.
Nothing above should be edited to imply significance that the intervals do not show.
