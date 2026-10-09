# Active-day versus sedentary-day: definition used for the evaluation

Blueprint sections 21-22 define the core comparison as Model C versus Model B "on each patient's own active-day meals versus sedentary-day meals".
The blueprint does not give a numerical rule for "active", so one had to be chosen. The choice is implemented in
`src/glycotwin/models/activity_strata.py` and used by `src/glycotwin/models/model_bc_compare.py` (`active_vs_sedentary_per_participant`).

## Definition
* **Variable:** `activity_level`, the 4-hour pre-meal mean METs: the same covariate Model C uses (blueprint section 10, "normalised rolling METs").
* **Relative to the person:** for each participant, take the median `activity_level` over that participant's compared events. A meal is **active** if its
  activity is strictly above that median and **sedentary** otherwise (at or below).
* **Both strata required:** a participant is used only if both strata hold at least 2 events (`min_per_side`); otherwise all of their events are
  `excluded` and counted. A participant with constant activity is therefore always excluded.
* **Prospective label (display only):** in the twin state view, a meal is labelled active/sedentary against the median of the person's *earlier* meals
  (needs at least 4), `unknown` before that.

## Why this and not an absolute METs threshold
1. The blueprint's wording is *within-patient* ("each patient's own"). An absolute cut-off labels some people always active and others never, so those
   people contribute nothing to a within-person comparison.
2. No validated METs cut-off for a wrist device in this free-living cohort is available in the source material; inventing one would be arbitrary.
3. A median split gives every contributing participant events in both strata, which maximises the power of the comparison (blueprint risk table:
   "design the active/sedentary split specifically to maximize power").

## Known limitations (not hidden)
* The median uses the person's whole evaluated period, so the label is a **retrospective analysis label**. It feeds no forecast and no model, so it cannot
  leak outcomes into a prediction, but it is not a rule a clinician could apply on the day.
* "Active" here means *more active than that person's usual*, not physiologically active. A person who is sedentary all the time still has "active" meals.
* The split is by the value of the covariate that Model C uses, so the two strata differ by construction in the size of the activity term; that is intended.
* Ties at the median go to sedentary, so strata can be unequal.
* This definition was chosen after the blueprint was written but **before any real active/sedentary result was seen**; it has not been tuned. The
  pre-existing pooled threshold function (`evaluation.compare_models_on_activity_strata`) and the pooled tertile table remain, as exploratory views.
* The earlier supplied tertile result (C better at low activity, B better at high activity) used pooled tertiles, not this definition, and is not a result of this one.
* Results of this analysis on real data do not exist yet. Reported as a comparison with intervals; no non-inferiority margin was prespecified.
