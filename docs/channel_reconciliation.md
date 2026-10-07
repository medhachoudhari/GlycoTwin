# Libre vs Dexcom: channel-reconciliation audit

**What this is.** A read-only comparison of the two released CGM channels (`Libre GL`, `Dexcom GL`) on the *same* meal
events, run by `scripts/compare_cgm_channels.py`. It asks why the two channels give different 180 mg/dL event labels.

**What this is not.** It is **not a validation of either sensor** against a clinical reference standard (there is no
reference glucose in the released data), it does not say which channel is closer to true glucose, and it does not
test interpolation of the released grid (audited separately). Agreement between two sensors is not accuracy;
disagreement is not error in one of them.

## Researcher-reported context (not committed output)
Real extraction by the researcher on both channels with the primary definition (D9): Libre 1,697 extraction-valid windows,
1,262 core-eligible, 301 positive, 961 negative; Dexcom 1,666, 1,230, 534, 696. Leakage check passed 45/45 participants on
both channels. The positive rate therefore differs markedly (about 24% vs 43% of core-eligible events); the audit exists to
separate possible causes. These numbers were reported in chat; the JSON outputs are local and not committed.

## Real-data result (researcher-reported, JSON not committed)
45 participants; 1,229 matched core-eligible events. Libre positive 23.596%, Dexcom 43.450%; label disagreement 284/1,229 (23.108%),
overwhelmingly Dexcom-positive / Libre-negative; kappa about 0.503; window maximum (Libre minus Dexcom) mean about -34.51 mg/dL, mean
absolute about 38.39, Pearson about 0.867; a common 5-minute baseline lag did not materially change label disagreement (expected by
construction, since the label does not use the baseline). Interpretation and the proposed primary/sensitivity rule:
`docs/primary_channel_decision.md` (PROPOSED).

## Definition (reused, not re-implemented)
Events come from `glycotwin.data.events.build_event_table` with the same defaults as `build_event_table.py`: anchor = `Meal Type`
row timestamp, window = (t0, t0 + 120 min], target = maximum available glucose >= 180, leading/internal gap <= 15 min,
trailing gap <= 5 min, isolated meals, `keep_first` on duplicate timestamps, each channel's own baseline lag guard
(Libre 15 min, Dexcom 5 min). A test asserts the per-channel counts equal what `build_event_table.py` reports for the same files.
Events are matched on participant + meal-row ordinal; matched anchors must be the identical timestamp (mismatches are counted and dropped).

## Populations kept apart
| Name | Meaning |
|---|---|
| extraction-valid | the 120-minute window passed the gap checks for that channel |
| core-eligible | extraction-valid and a past-only baseline exists and carbs are present and the meal is isolated |
| activity-eligible | core-eligible and usable pre-meal activity |
"Matched core-eligible" (the primary comparison) requires core-eligibility in **both** channels; the report also gives the
extraction-valid and activity-eligible matched sets and how many events are core-eligible in one channel only.

## What is reported (aggregate only)
Availability over all meal rows (valid in both / one / neither); exclusion reasons per channel; the 2x2 confusion matrix
(rows = Libre, columns = Dexcom); disagreement counts by direction; Cohen's kappa; signed and absolute differences of the
window maximum and the baseline (Libre minus Dexcom) with Pearson/Spearman correlation; threshold proximity (disagreements whose
maxima are within `--delta` mg/dL, default 10, and disagreements by distance of the nearer channel's maximum to 180); window
completeness of each channel; and how concentrated the disagreements are across participants (counts only).
No participant identifiers, timestamps, meal rows, image paths or per-event records are printed.

## Cautions when reading the result
- **Baseline lag differs by channel by default**, so a baseline difference mixes sensor difference with the 15 vs 5 minute lag. Re-run with `--baseline-lag-minutes 5` (or 15) to remove that asymmetry.
- The label uses the maximum *available* reading; a channel with lower window completeness can only under-report its maximum.
- A systematic offset between channels, different smoothing, or different sampling would all show up as the same kind of disagreement; this audit cannot tell them apart.
- Choosing a primary channel from this audit would be a scientific decision for the researcher, not a result of the audit.
