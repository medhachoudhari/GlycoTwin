# Innovation audit and roadmap

Written because no earlier innovation audit existed in this repository (an expected
`docs/INNOVATION_ROADMAP.md` was not found). It is an audit of the *claim*, not a plan to build features.
It is synchronised with `docs/PROJECT_STATUS.md`; where they disagree, the evidence listed in
PROJECT_STATUS wins, and one of the two files is wrong and must be fixed.

**Bottom line today: the innovation is implemented in code and demonstrated on simulated data only. There is
no evidence, for or against it, from CGMacros.** Nothing in this repository supports a claim that the
activity-conditioned model improves calibration on real people.

## 1. The claim, stated precisely

From the blueprint (sections 1, 5, 22): an **online Bayesian carbohydrate-sensitivity model whose sensitivity
depends on same-day activity**, for non-insulin-managed prediabetes and type 2 diabetes, **calibrates better**
than an otherwise identical personalised model without the activity term.

What the blueprint itself says is *not* novel: personalisation, Bayesian updating, the "digital twin" label,
CGM forecasting, XGBoost, uncertainty bands, dashboards. A "digital twin" label proves nothing. The only
candidate contribution is the **activity interaction on the personal sensitivity, evaluated on a population that
existing diabetes twins do not target**. I have not searched the literature; the blueprint's statements about
ReplayBG, TWIN and GlyTwin, and the novelty of the gap, are **unverified by me**. Using activity as a predictor
of post-meal glucose is common, so novelty cannot rest on "uses activity".

## 2. What would have to be demonstrated (claim ladder)

Each rung needs the one below. A rung is "demonstrated" only with a committed real-data result.

| Rung | What must be shown | Where it is tested | Status |
|---|---|---|---|
| C0 | Meal events can be built faithfully from the real files (meal-row meaning, outcome window, baseline without leakage, eligible counts). | Gate 2; `build_event_table.py`, `check_leakage_on_data.py`, `audit_meal_event_semantics.py`, `audit_cgm_sampling_phase.py` | **Not demonstrated** (no real run) |
| C1 | Personal updating helps: B beats the frozen population prior, the shuffled-history control and the simple personal baseline, with participant-clustered intervals excluding 0. | `run_experiment.py`: `B vs frozen_B`, `B vs B_shuffled`, `B vs personal_rate` | Simulation only |
| C2 | The activity term is identifiable: enough within-person variation in carbohydrate and activity for the personal interaction to be learned. | to be added after real events exist (posterior width of the interaction vs prior) | Not assessed |
| C3 | Personal activity learning adds something beyond a **population-level** activity effect. | `C vs frozen_C`, `frozen_C vs frozen_B` (added to the pre-listed comparisons) | Simulation only |
| C4 | The gain appears where it should: C beats B on active meals, and does not do worse on sedentary meals; and it disappears when activity is permuted. | `C vs B` (active / sedentary), `C vs C_perm_activity` | Simulation only |
| C5 | The result is calibration, not only ranking: reliability curves, calibration slope, ECE with caution at small n. | `models/evaluation.py` (metrics exist; plots not built) | Partial |
| C6 | Robust to the unresolved choices: threshold (180 vs 140), device (Dexcom vs Libre), window anchor (t0 vs +20 min), meal isolation, interpolation handling. | flags exist (`--channel`, `--allow-overlap`, `--max-gap-minutes`, `--baseline-lag-minutes`); sensitivity runs not done | Not demonstrated |
| C7 | Honest reporting: a negative or inconclusive result is reported as such. | `run_experiment.py` prints reading rules; intervals containing 0 are "inconclusive" | Built in |

## 3. Decision rules, fixed before any real run

These are written now so the outcome cannot be reinterpreted afterwards. They are proposals for the
researcher to confirm (Human Action H8).

- **Supported (this dataset, this definition):** C beats B on active meals with an interval excluding 0 **and**
  C beats `frozen_C` (personal learning, not just population activity) **and** the permuted-activity control
  loses the gain **and** C is not worse than B on sedentary meals beyond a stated margin **and** the sign
  survives at least two of the sensitivity variants in C6.
- **Inconclusive:** the interval for C vs B on active meals contains 0 (state the interval and the number of
  participants and events; do not say "no effect").
- **Not supported:** C is worse than B, or the gain is explained by the population-level activity effect or by
  the permuted control.
- Never claim clinical utility. Never report a single comparison out of the pre-listed set.

## 4. Implemented versus demonstrated

| Component | Implemented | Demonstrated on real data |
|---|---|---|
| Activity-conditioned Bayesian personalisation (`models/bayesian.py`, Model C) | Yes; closed form verified (17 tests, 16 injected bugs caught) | No |
| Forecast, observe, update lifecycle (`twin/state.py`) | Yes, in memory: idempotent, window-guarded, order-independent | No |
| Uncertainty (posterior-predictive probability and interval) | Yes; probability matches Monte Carlo, interval has 90% coverage in simulation | No |
| Leakage safeguards (`data/events.py`, `data/leakage_check.py`) | Yes; mutation test passes on synthetic frames and fails when a pipeline leaks | No |
| Prequential comparison with controls (`models/experiment.py`) | Yes; detects a simulated effect, stays inconclusive when none is simulated | No |
| State history and replay | History in memory only; **replay not built** | No |

## 5. Threats to the claim (each needs evidence, not argument)

1. **Interpolated CGM.** No documented flag separates native from interpolated values; the blueprint's
   native-timestamp plan may be impossible. Mitigation: lag guard; evidence pending (Gate 2).
2. **Meal-row meaning.** Start, end or logging time is unconfirmed (R1). The official `meal_end` cannot be reconstructed (R15, researcher-run audit), so the primary anchor is the meal-row timestamp (D9, locked); every claim is phrased relative to that logged time.
3. **Self-reported macros and activity.** Meal composition is logged by participants; METs come from a wrist
   device. Errors in the covariate the claim depends on can create or hide an effect.
4. **Confounding.** Activity timing correlates with time of day and meal type; the model does not adjust for
   them. A "sensitivity falls with activity" finding could reflect which meals follow activity.
5. **Small samples.** 45 participants, a few hundred isolated meals at best. See the power simulation below.
6. **Selection on the future.** Keeping only isolated meals depends on the next meal (rule R7): report with and
   without it.
7. **Model misspecification.** Gaussian, constant-variance peak rise; known noise variance. Assumptions, not
   findings (R14).
8. **Multiple comparisons.** The comparison list is pre-listed and every row is reported; no row may be promoted
   after the fact.
9. **A weak baseline can flatter B.** The running-mean personal baseline is noisy, so beating it is easy; the
   shuffled-history and `frozen_C` controls are the informative ones.

## 6. Power: what could the planned experiment detect? (SIMULATION)

**This is a simulation, not a result.** It asks: if the world behaved as assumed, how often would the harness report an
interval that excludes zero in the favourable direction? Generated by `python scripts/simulate_power.py --reps 16 --n-boot 300`
(seed 0). Assumed, not estimated from any data: mean sensitivity 0.7 mg/dL per gram, between-person
sd 0.2, interaction sd 0.1, residual noise sd 12.0 mg/dL, activity uniform on [0, 1].

| Participants | Isolated events each | Assumed interaction | P(C beats B on active meals) | P(C beats B, all meals) | P(B beats frozen prior) |
|---|---|---|---|---|---|
| 20 | 8 | 0 (none): false-positive rate | 0.06 | 0.06 | 0.81 |
| 20 | 8 | -0.1 (about a 14% fall in sensitivity, sedentary to very active) | 0.00 | 0.00 | 0.88 |
| 20 | 8 | -0.35 (about a 50% fall) | 0.38 | 0.38 | 0.69 |
| 20 | 15 | 0 (none): false-positive rate | 0.00 | 0.00 | 0.94 |
| 20 | 15 | -0.1 (about a 14% fall in sensitivity, sedentary to very active) | 0.00 | 0.00 | 0.94 |
| 20 | 15 | -0.35 (about a 50% fall) | 0.88 | 0.88 | 0.81 |
| 45 | 8 | 0 (none): false-positive rate | 0.00 | 0.00 | 0.94 |
| 45 | 8 | -0.1 (about a 14% fall in sensitivity, sedentary to very active) | 0.00 | 0.06 | 0.94 |
| 45 | 8 | -0.35 (about a 50% fall) | 0.38 | 0.62 | 0.81 |
| 45 | 15 | 0 (none): false-positive rate | 0.00 | 0.00 | 1.00 |
| 45 | 15 | -0.1 (about a 14% fall in sensitivity, sedentary to very active) | 0.06 | 0.06 | 1.00 |
| 45 | 15 | -0.35 (about a 50% fall) | 1.00 | 1.00 | 1.00 |

**What it shows (conditional on those assumptions)**

- At zero effect the false-positive rate is at or below about 6% in every scenario (with 16 studies per row, one hit is 0.0625).
- A **strong** activity effect (about -0.35) is detected reliably only with many events per person: 1.00 at 45 participants x 15 events,
  0.88 at 20 x 15, but **only 0.38 at 45 x 8 or 20 x 8**.
- A **modest** effect (about -0.1) is essentially **undetectable** in every scenario tried, including 45 x 15 (0.06 at best).
- Events per participant matter more than the number of participants: 20 x 15 outperforms 45 x 8 for the strong effect.
- Personal updating itself (B over the frozen prior) is detected in most scenarios because the simulation assumes real between-person differences.

**Caveats that make real power lower, not higher:** the simulated data follow the analysed model exactly (no misspecification, no
interpolation, no confounding, no measurement error in activity); only 16 studies per row; the effect sizes and heterogeneity are invented.
The only two sample-size values the code ships (`PLACEHOLDER_MINIMUMS`: 20 participants, median 8 events) are therefore **too small to
support a confident negative or positive conclusion for the activity term**, even for a strong effect. This is a recommendation for the
researcher (Human Action H8), not something I changed: consider requiring a median of at least 15 eligible events per participant, and
state in advance that a modest effect cannot be detected with this dataset, so an inconclusive result is the expected outcome in that case.

## 7. Roadmap in dependency order (no blocked feature is built to raise a completion figure)

1. **Gate 2, data validity** (human-run evidence). Nothing below is meaningful before it.
2. **Confirm the pre-registration items:** window anchor (H1), minimum sample sizes (H8), decision rules above.
3. **Run the key experiment once** with the frozen plan; then the sensitivity variants; report all rows.
4. **Only if the evidence supports it**, build the persistent twin, API, replay and dashboard as a demonstration
   of a *validated* mechanism; if the result is inconclusive, the product is still buildable but the story
   must say so.
5. Final: results tables and reliability diagrams from real runs, model card, limitations, safety statement.
