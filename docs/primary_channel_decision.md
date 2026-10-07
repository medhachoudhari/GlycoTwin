# Primary CGM channel: methodological review and PROPOSED prespecification

**Status: PROPOSED (decision D14). Not locked.** Nothing here was chosen using a model result; no Model A/B/C has been run.
This is a review, not a validation of either sensor, and it changes no code or event definition.

## 1. Bottom line
- The evidence does **not** show that either channel is the more accurate one, and it cannot (there is no reference glucose in the
  released data, and the channel audit is a reconciliation, not a validation).
- The two label-independent, checkable, non-performance criteria I could find point in different directions, and both are weak:
  *source precedent and completeness* favour **Libre GL**; *native sampling resolution* favours **Dexcom GL** but rests on blueprint-reported,
  unverified intervals.
- Because the evidence does not pick a channel on validity, I propose a **neutral, prespecified rule** (section 6) that selects
  **Libre GL as primary** and **Dexcom GL as a full-pipeline sensitivity analysis**, with the explicit statement that this is a
  convention for the analysis, **not a claim that Libre is more accurate**. Every result must be reported as conditional on the channel.
- **Not strong enough to lock yet.** One open item could override it (the dataset's data dictionary, H3), and the label itself is
  channel-dependent (kappa about 0.50). Lock only after you have read section 8.

This corrects an earlier note of mine in the blueprint-gap review, which suggested Dexcom primary with Libre as the sensitivity check
("Dexcom has more readings per window"). That rested on the blueprint-reported native intervals (5 vs 15 min), which I have not verified,
and on treating denser sampling as automatically preferable. It was a design preference, not a source-supported finding. The default
`--channel "Dexcom GL"` in `build_event_table.py` is likewise a historical default of the scaffolding, **not** a decision.

## 2. Source-supported facts (and where they come from)
| Fact | Source |
|---|---|
| CGMacros has two CGMs per participant; each file holds "the glucose response from two devices" with activity, heart rate, macros and meal photos | official README (PSI-TAMU/CGMacros), read |
| The README names no reference channel, no sensor models, no wear sites, and no sampling interval, and states no validity ranking | same README (what I could read; PhysioNet/Nature pages were unreachable) |
| The authors' own released analysis code uses **only `Libre GL`** for its glucose-response analysis (iAUC/AUC, baseline), sampled every 15 minutes (`index:index+135:15`) | `parse_data.ipynb`, read. A precedent for one task, not an endorsement of validity or a stated reason |
| Researcher-run, primary definition D9: Libre 1,697 extraction-valid / 1,262 core-eligible / 301 positive / 961 negative; Dexcom 1,666 / 1,230 / 534 / 696; 1,706 meal rows; leakage check passed 45/45 on both | your real runs (reported in chat; JSON not committed) |
| Earlier real audit: 2-hour post-meal window completeness Libre 99.24%, Dexcom 97.64% | your real audit (reported in chat) |
| Matched primary core events 1,229 (45 participants). Libre positive 23.596%, Dexcom 43.450%; label disagreement 284/1,229 = 23.108%; kappa about 0.503; window-max difference (Libre minus Dexcom) mean about -34.51 mg/dL, mean absolute about 38.39; Pearson of window maxima about 0.867; disagreements overwhelmingly Dexcom-positive / Libre-negative; forcing a common 5-minute baseline lag did not materially change label disagreement | your real reconciliation run (reported in chat) |

**Derived by arithmetic from those reported rates (not your exact cells; the exact table is in your local JSON):** about 290 Libre-positive
and 534 Dexcom-positive of 1,229; Libre+/Dexcom- about 20 and Libre-/Dexcom+ about 264; both positive about 270, both negative about 675;
"positive in either channel" about 554 (45.1%). These reproduce the reported kappa (0.5035), which is the check that they are consistent.
Of the 1,262 and 1,230 core events, about 33 are core-eligible only in Libre and about 1 only in Dexcom (given 1,229 matched).

## 3. Methodological inference (reasoned, not verified from sources)
1. **The difference is mostly a systematic shift, not scatter.** The mean signed difference (34.5) is about 90% of the mean absolute
   difference (38.4), and correlation is high (0.867): the channels rise and fall together, but Dexcom's window maximum sits about
   35 mg/dL higher on average. A near-constant shift is exactly what a fixed threshold turns into very different prevalences.
2. **Why 180 mg/dL makes this consequential.** The label is a dichotomisation of the window maximum at a fixed threshold. A shift of
   about 35 mg/dL moves many events across the line, giving 23.6% vs 43.5% positives. The same shift would matter much less for a
   continuous outcome (peak rise, MAE) than for the binary label, though a level shift can still affect baselines and rises.
3. **The 5-minute common-lag result is uninformative about the cause.** The label depends only on the window maximum, not on the
   baseline, so changing the baseline lag can alter the label only through eligibility. "No material change" was expected by
   construction and does not rule in or out any explanation.
4. **Completeness is a weak, confounded criterion.** The Libre advantage is small (99.47% vs 97.66% of meal rows extraction-valid; about 32
   more core events). The released grid is reportedly interpolated, and interpolation can fill sensor outages, so completeness on the
   released grid is not evidence of sensor reliability.
5. **Sampling density can inflate a maximum.** A window maximum over more native samples is at least as large as over a subset of them. If
   Dexcom is natively sampled every 5 minutes and Libre every 15, part of the gap in maxima could be sampling density, independent of
   accuracy. This is plausible but cannot explain the full 35 mg/dL for slowly varying post-meal curves, and it depends on the unverified
   native intervals. It is testable without native timestamps (see section 7, diagnostic).
6. **Selecting by positive rate is not neutral.** Choosing Dexcom because it gives more positives (a base rate with higher variance, 0.246 vs
   0.180) would be selecting the label definition by its outcome distribution. I reject outcome prevalence, and of course model
   performance, as selection criteria. Note the label rates were already known when this review was written, so the choice is not
   blind to prevalence; the criteria used are the ones that do not depend on the labels.
7. **Libre as primary costs power.** About 290 positives (23.6%) is fewer than about 534 (43.5%) and per-group counts will be smaller. That is a cost of the
   convention and must be handled by feasibility gates stated in advance (section 6, item 5), never by switching channels afterwards.
8. **The blueprint's own wording is a composite.** The blueprint target is written as the maximum over "Libre or Dexcom" (as extracted
   earlier; the PDF was not re-readable in this environment). Taking the higher of two sensors on different body sites is
   upward-biased (about 45% positive here) and has no source justification, so I do not adopt it. For the same reason I do not
   average or otherwise merge the channels.

## 4. Unresolved uncertainty
- Which channel (if either) tracks true glucose better in this cohort: **unknowable from the released data**.
- Sensor models, wear sites, calibration and the exact native sampling intervals: blueprint-reported or undocumented in what I read
  (H3, the data dictionary, is still open).
- Whether the released grid is interpolated, and how (audited separately; native readings are not recoverable from the grid).
- Why the authors used Libre only in their notebook (convenience, 15-minute grid, availability, or accuracy).
- Whether the shift varies by participant, glycaemic group, device order or time of day: no per-participant breakdown was available to me.
- How close the disagreements are to the 180 line (`threshold_proximity` is in your JSON; I did not have those numbers).
- Whether files lacking one channel exist (R5); the matched set has all 45 participants, so none lacks both.

## 5. Does the evidence support either channel as primary?
**No, not on validity.** Source precedent (Libre) and completeness (Libre) are real but weak and cannot speak to accuracy. Native resolution
(Dexcom) is the only argument for the other side and is unverified. A rule that is honest about this is a **convention chosen before any
model result**, with the other channel analysed in full.

## 6. PROPOSED prespecification (D14)
1. **Primary channel: Libre GL.** Rule, applied in this order and written down before any model run: (a) if the data dictionary or other
   dataset documentation designates one channel as primary or reference, use that; (b) otherwise use the channel the dataset authors use
   in their released analysis code (`Libre GL`); (c) completeness is recorded as a consistent secondary observation, not a decider.
   Prevalence, power, correlation with activity and any model metric are **not** criteria.
2. **Sensitivity channel: Dexcom GL**, a full re-run, not a spot check: the same D9 definition, same gap and lag defaults, same models,
   same prespecified comparisons, same participant fold manifest and seeds. Tuning, if any, follows the same inner-CV procedure within the
   sensitivity channel and does not use the primary channel's results.
3. **Which events:** run the sensitivity channel on (S1) the matched core-eligible events (same events in both channels), so any difference is
   channel and not population; and report (S2) the sensitivity channel's own core-eligible events descriptively.
4. **Reading the sensitivity analysis, fixed in advance:** *robust to channel* only if the key contrasts have the same sign and overlapping
   intervals in both channels; *channel-dependent* if the signs differ or one interval excludes zero while the other is clearly on the other
   side; in that case report it as channel-dependent and do not name a winner. Never pool, average, take the better, or report one channel's
   result without the other's.
5. **Feasibility gates stated now, applied to counts only:** the placeholder minimums (participants, events per participant, positives,
   negatives) apply to the primary channel and are confirmed or revised by you before any model run (H8; the power simulation suggested
   raising events per participant). If the primary channel fails a gate, the response is a stated fallback (for example the blueprint's 140 mg/dL threshold, decided before
   model results), **not** a switch of channel.
6. **Language:** every claim says "using the Libre channel (sensitivity: Dexcom)" and "relative to the logged meal-row time". No sentence may
   say a channel is more or less accurate.
7. **Not recommended:** averaging channels, "positive in either channel", offset-matching the threshold between channels (no reference
   standard to justify it), or choosing the channel per participant.

## 7. Optional diagnostics that do not select a channel (no code written now)
- **Sampling-density-matched comparison:** recompute the Dexcom window maximum from every 15th minute (each of the 5 phases) and compare
  with Libre; this estimates how much of the shift is sampling density alone.
- **Shift structure:** by participant and glycaemic group (counts only), and as a function of glucose level (is it constant or proportional?).
- **Threshold proximity:** the number of disagreements within 10 mg/dL of 180 (already in `compare_cgm_channels.py` output).
- **Continuous secondary outcome:** report peak rise (and MAE) alongside the binary label so conclusions are not only threshold-driven.

## 8. Is this strong enough to lock?
**No.** To lock D14 you should:
1. Read the dataset's `DataDictionary` for `Libre GL` and `Dexcom GL` (H3). If it designates a primary/reference channel, that overrides section 6(b).
2. Accept that Libre-primary is a **convention** and that results are channel-conditional (the labels agree only moderately, kappa about 0.50).
3. Confirm or revise the feasibility minimums (H8) knowing the primary channel has about 290 positives in 1,229 events.
4. Confirm the decision rules for reading the sensitivity analysis (6.4).
Until then D14 stays PROPOSED and no model is run.
