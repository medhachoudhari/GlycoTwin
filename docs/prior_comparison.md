# Prior-versus-prior comparison (sensitivity analyses S2 and S3)

Tool: `scripts/compare_priors.py` (logic in `src/glycotwin/models/prior_compare.py`). It is a dedicated tool: the existing B-versus-C comparison (`scripts/compare_models_b_c.py`) is not reused or relabelled.
Status: **no real-data run exists.** The blueprint prior is opt-in; the empirical-Bayes prior remains the primary protocol and the default.

## What is compared
Four arms from the same runners, the same event table, the same participant-level folds and the same seed:
`b_eb` Model B empirical Bayes, `b_bp` Model B blueprint prior, `c_eb` Model C empirical Bayes, `c_bp` Model C blueprint prior (with its gamma relative sd).
Contrasts (all metrics are lower-is-better, differences are second-named minus first-named, so negative favours the blueprint prior or Model C):
1. Model B: blueprint minus empirical Bayes.
2. Model C: blueprint minus empirical Bayes.
3. Model C minus Model B under empirical Bayes.
4. Model C minus Model B under the blueprint prior.
5. The change in the C-minus-B contrast between priors: (C_bp - B_bp) - (C_eb - B_eb).
Metrics: Brier score, log loss, 10-bin and 5-bin ECE, rise MAE (mg/dL). Intervals: participant-clustered percentile bootstrap, one common resample of participants for all four arms
(events of a participant stay together), seed 0, 2000 resamples by default. An interval containing 0 is inconclusive, not "no difference".

## What is checked before anything is compared (the tool refuses, it never aligns or drops)
Same event identifiers (no missing, no duplicate), same participant for every event, same fold for every event and each participant in exactly one fold, same labels and observed rises,
same personal-observation counts, finite forecasts, labels 0/1, probabilities in [0, 1]; and in the run manifests: Model B/C identity, prior scheme per arm, a declaration that the prior was fitted on
training folds only, one blueprint prior per held-out participant, the gamma relative sd (one of 0.25 / 0.5 / 1 / 2, present for the blueprint Model C arm only, optionally pinned with `--expect-gamma`),
the same fold seed, fold hash, CGM channel, event-table file hash and event-table settings, and Model B run on Model C's activity-eligible events.
Limitation: the tool cannot re-derive from forecasts that priors were learned from training folds only. That property is enforced and tested inside the runners
(`tests/test_prior_scheme_runners.py`); this tool checks the manifests' declarations and refuses if they disagree.

## Prespecified decision rule (adoption screen)
PRESPECIFIED SCREEN (fixed before any real run; changing it afterwards is a protocol change). The blueprint prior becomes a CANDIDATE default, for human review only, if for BOTH Model B and Model C:
(1) the Brier difference (blueprint minus empirical Bayes) has a 95% interval entirely below 0, (2) the log-loss difference has a 95% interval entirely below 0, and (3) the 10-bin ECE difference does NOT have an interval entirely above 0.
Each gamma width is screened separately; the best-looking width is never selected. Meeting the screen does not establish superiority; failing it does not establish equivalence; neither says anything about clinical use.
The empirical-Bayes prior stays the default until the researcher decides. The screen is not proof of anything: it only decides whether a human review is warranted.

## Reading the C-minus-B rows
Rows 3 to 5 answer a different question: does the conclusion about activity conditioning depend on the prior? If the interval of row 5 contains 0, the data do not show that it does.
No row in this report shows that Model C is better than Model B.
