# Blueprint-form population prior (opt-in) and the gamma prior

Source: Master Blueprint section 10, "Prior". Implementation: `src/glycotwin/models/blueprint_prior.py`; used through
`initialize_twin_from_population(..., prior_scheme="blueprint", glycaemic_group=...)`. The default remains the empirical-Bayes prior
of the Model B/C research runs, so no reported result changes.

## Blueprint text versus implementation
| Blueprint statement | Implementation | Decision needed? |
|---|---|---|
| beta "initialized from the population-level regression of glucose rise on carbs, ... across all patients in the training fold, stratified by glycaemic group" | Regression of rise on carbohydrate through the origin (the blueprint/H12 model has no intercept) over the training rows of the participant's group; pooled when no group is supplied, the group column is absent, or the group has fewer than 5 training participants; the fallback is recorded | none |
| gamma "initialized at 0 (no assumed activity effect)" | prior mean exactly 0 | none |
| gamma "moderately wide prior variance" | prior sd = 0.5 x &#124;beta mean&#124; / rms(activity); i.e. one prior sd of the activity term at a typical activity is half the population sensitivity | **yes: the blueprint gives no number.** 0.5 is a convention scaled to the blueprint's own toy example (an activity effect of roughly 30% of beta); not fitted to outcomes, not tuned. Dependence of conclusions on it is not studied. It is a parameter. |
| beta prior variance | not stated; empirical-Bayes between-participant variance of per-participant slopes (method of moments, floored), within the group when large enough | documented choice |
| "Gaussian observation noise whose variance is estimated from the population's meal-to-meal variability" | pooled within-participant residual variance of the per-participant fits | none |
| "two correlated parameters" in the posterior | the prior is independent; the posterior becomes correlated through the data (tested) | none |

## Why not make it the default
The B-vs-C comparison reported in `docs/model_b_vs_c_report.md` used the unstratified empirical-Bayes priors (decisions R14/H12 of the researcher). Changing the prior
changes the model that was evaluated. The blueprint-form prior is therefore an additional option for the twin; a comparison of the two priors on real data has **not** been run.

## Grouped data
Stratification needs a `glycaemic_group` column on the population events. The group derivation from `bio.csv` (A1c rule from the dataset authors' notebook) is
implemented in `scripts/audit_bio_groups.py`, but the real `bio.csv` column names and the participant-to-row alignment could not be inspected in this environment
(`data/raw` is empty), so the real-data wiring is not done. Until then the prior falls back to pooled and says so.
