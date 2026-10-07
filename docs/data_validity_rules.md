# Data validity rules

Status: **living document.** It separates (A) decisions that are implemented and tested, (B) the one
blueprint inconsistency and how it is resolved, (C) rules that are still OPEN and need evidence from the
real data or the official documentation, and (D) claims in existing code that are not backed by anything
committed. Nothing here is a finding about CGMacros unless it cites evidence; everything else is a
decision or a question.

Evidence sources available so far: the committed `data/audit/dataset_inventory_summary.md` (a real run;
aggregate in `data/audit/dataset_aggregate_summary.md`), the project blueprint (`GlycoTwin-Master-Blueprint.pdf`),
and synthetic software tests. **No real participant file has been read in the engineering environment**,
and the official PhysioNet pages and data dictionary were not reachable from it.

## A. Decisions implemented (reversible; each has tests)

| ID | Decision | Where | Why |
|---|---|---|---|
| D1 | The outcome window is `(t0, t0 + 120 min]` where `t0` is the logged meal row time (see section B). **Locked for the primary analysis by D9.** | `data/meals.py`, `data/events.py::compute_outcome` | Section B. |
| D2 | The baseline is the latest valid reading at or before `t0 - lag` (default lag = the channel's documented native interval: Dexcom 5, Libre 15 min), no older than `lag + 15 min`. | `meals.extract_meal_events_detailed` | Conservative guard against interpolated values that blend in later readings (R3/R4/R8 open). |
| D3 | Label = `peak >= 180 mg/dL` where `peak` is the maximum valid reading in the window; the reading at `t0` is excluded. `rise = peak - baseline`. | `events.compute_outcome` | The blueprint says `>= 180`. Excluding `t0` stops a high value at the meal from making the label trivially positive. |
| D4 | A meal is excluded from the event table unless: >= 2 valid readings, leading gap <= 15 min, every internal gap <= 15 min, last valid reading within 5 min of the window end. Every exclusion is logged with a reason; counts reconcile (`n_meal_rows == kept + excluded`). | `meals.py` | Defaults reproduce the earlier 15 min / 115 min behaviour and add the missing leading-gap check. The blueprint says 30 min: R6 open. |
| D5 | Overlapping meals (another logged meal within 120 min before or after) are flagged; the primary set keeps only isolated meals (`--allow-overlap` keeps them). | `meals.py`, `events.build_event_table` | Blueprint section 8. **Caveat:** "isolated" depends on the NEXT meal, i.e. on the future. It is a selection on future behaviour, legitimate for choosing evaluation meals, and must be reported with a sensitivity analysis (R7). |
| D6 | Pre-meal activity = mean `METs` over `[t0 - 4 h, t0)` (strictly before), usable if >= 50% of the minutes have a value. Meals without usable activity stay in Models A/B and leave only the activity comparison. | `events.pre_meal_activity` | Blueprint: rolling METs 4 h pre; missing Fitbit data excludes meals from the activity comparison only. Normalisation to `[0, 1]` is not defined by the blueprint and is fitted on training data later. |
| D7 | `Image path` is never kept. `Amount Consumed` is preserved verbatim as `amount_consumed_raw` for audit but is **never a feature** (it may be recorded after eating); it is in `RETAINED_RAW_COLUMNS`, not `FEATURE_COLUMNS`. | `meals.py`, `events.py`, `tests/test_primary_event_definition.py` | Blueprint section 7, risk 3; amended when the primary definition was locked (D9) so the raw value is not lost. |
| D8 | Minute rows are never treated as independent samples; the unit of analysis is the meal event. | design | Interpolation inflates effective sample size (>= 5x Dexcom, >= 15x Libre if the documented intervals hold). |
| D9 | **PRIMARY ANALYSIS DEFINITION (locked by the researcher after the real photo-pairing audit).** Prediction anchor `t0` = the `Meal Type` row timestamp. Forecast window = `(t0, t0 + 120 min]`. Target = 1 if the **maximum available** glucose in that window is `>= 180 mg/dL`, else 0. The anchor is **not** called `meal_end`; no meal duration is assumed; neither the next photo nor the next meal is used as an end; photo pairing is not used anywhere in the primary target. The blueprint's own `meal_end` definition is kept in section B as the original specification. | `data/meals.py`, `data/events.py`, `tests/test_primary_event_definition.py` | Source support: the authors' released notebook anchors on the meal row (section B2); the real audit (R15) found the official end cannot be reconstructed without an undocumented assumption. |
| D10 | **Missing glucose.** NaN readings are never imputed or interpolated by this project. The peak is the maximum available reading, so it is a lower bound on the true maximum. A meal is excluded (reason logged) unless it passes D4. `window_completeness` = available readings in `(t0, t0 + 120]` / 120 is stored per event and summarised in the count report. Residual risk: a label of 0 can hide a short peak inside a permitted gap (<= 15 min). | `events.compute_outcome`, `meals.py` | Keeps the target traceable to observed values only. Sensitivity (R6): repeat with stricter gap limits. |
| D11 | **Meal-type normalisation.** `breakfast`, `lunch`, `dinner`, and `snack` (also `snacks`, `snack 1`, `Snack2`) after trimming and lower-casing; any other non-missing label becomes `unrecognized` and is **counted and reported with its raw value**, never guessed. The raw label is preserved (`label_raw`). | `meals.normalize_meal_type` | A visible bucket is safer than silently merging unknown labels. |
| D12 | **Pre-meal activity features** use only METs rows strictly before `t0` (the meal row's own value is excluded): `activity_level` (4 h, primary, D6), `activity_1h`, `activity_24h`, each with its coverage. The 1 h and 24 h windows were chosen as simple descriptive spans before looking at any outcome; they are exploratory and are not inputs to Models A/B/C until the researcher decides. | `events.pre_meal_activity`, tests | R10 (activity definition) stays open; HR and steps are not used because their column names are unverified. |
| D13 | **Glycaemic group (PROPOSED, not locked; needs the real-data audit and your confirmation).** Group from `bio.csv` column `A1c PDL (Lab)`: healthy `< 5.7`; pre-diabetes `5.7 <= A1c <= 6.4`; T2D `> 6.4`. Source: the authors' released notebook (`parse_data.ipynb`, PSI-TAMU/CGMacros) uses exactly this rule; the README gives the cohort sizes 15 / 16 / 14. **Not established:** that this equals an official per-participant label (none was read); that bio.csv rows align with participant files (the notebook links them by position, which is undocumented). | `scripts/audit_bio_groups.py` (39 synthetic tests; **not run on the real bio.csv**) | The blueprint plans participant CV stratified by glycaemic group (15/16/14). The audit reports the mapping as verified only when bio.csv has an identifier column that matches the participant files; otherwise `POSITIONAL, UNVERIFIED`. |
| D14 | **Primary CGM channel (PROPOSED, not locked).** Primary = `Libre GL` by a neutral, prespecified rule (data-dictionary designation if one exists, else the channel used in the authors' released analysis code); `Dexcom GL` = full-pipeline sensitivity analysis on the matched events; never averaged, never "either channel". This is a convention, **not** a claim that either sensor is more accurate. | `docs/primary_channel_decision.md` (docs only; no code or definition changed) | Real reconciliation: label disagreement 23.1%, kappa about 0.50, Dexcom window maxima about 35 mg/dL higher on average; no reference standard exists. Open: H3 data dictionary, H8 minimums. |

## B. The blueprint inconsistency, resolved explicitly

**Original blueprint specification (kept for the record):** anchor = `meal_end`; window = `(meal_end, meal_end + 120]`; target = glucose
>= 180 in the window. **Source-supported operationalisation for CGMacros (decision D9):** anchor = the `Meal Type` row timestamp,
window = `(t0, t0 + 120]`. The released CSV has no `meal_end`, so the original definition cannot be reproduced; this is recorded as a
**data limitation**, not as a solved problem: the project does not know whether `t0` is the start, the before-photo time, or a logging
time, and any claim must say "after the logged meal-row time", not "after the end of the meal".

Blueprint section 8 states: prediction time = `meal_start`; forecast horizon = 120 min **from meal_start**
"regardless of how long the meal itself took"; but the event window = `(meal_end, meal_end + 120]`, and
the lifecycle (T4) reconciles at `meal_end + 120`. These differ by the meal duration. The verified
column list contains **no meal-end field**; the blueprint's fallback is `meal_start + 20 min`.

**Adopted:** forecast at `t0` (using only information available then); outcome window `(t0, t0 + 120]`.
Reasons: (1) no `meal_end` exists, so the alternative needs an assumed 20 min duration; (2) the horizon
sentence states the intent; (3) forecast time and window start coincide, so no unobserved interval lies
between them; (4) it does not hard-code an unverified duration.

**Sensitivity plan:** repeat with `(t0 + 20, t0 + 140]` once R1/R2 are settled. **Needs your scientific
confirmation (Human Action H1).** If `t0` turns out to be a later logging time rather than a start (R1),
part of the response precedes `t0` and this decision must be revisited.

### B2. Evidence on `meal_end` from the authors' own repository (inspected; real-data pairing NOT yet run)

Source: `PSI-TAMU/CGMacros` (README and `parse_data.ipynb`, fetched read-only; the PhysioNet and Nature pages were not
reachable from this environment). Findings, stated as read, not inferred:

- The README describes the CSV as holding "macros and the associated meal photos" and defines no `meal_end`, no
  before/after photo convention and no pairing rule.
- The authors' own analysis code never uses a meal end. For every meal row it takes the glucose values from the meal row
  index onward (`index : index+135 : 15`, i.e. 9 Libre samples at 0, 15, ... 120 min on the 1-minute grid) and the macros
  stored on that same row. The reference anchor is therefore **the meal row itself**, which is what decision D1 uses.
- Nothing found says that photo rows after a meal row are "after eating" photos. The blueprint's claim that the dataset
  "provides ground truth for meal start and end through photographs" is **not confirmed by anything I could read**.

Consequence: until the data dictionary or the pairing audit (rule R15) shows otherwise, `meal_end` cannot be reconstructed
without an assumption, and the blueprint's `(meal_end, meal_end + 120]` target is **not implementable as written**. D1
(anchor at the meal row) is the only definition the authors' released code supports. This does not change D1; it records
that its support is "matches the authors' code", not "proven to be the photographed meal start".

## C. Open rules (status OPEN until the stated evidence is committed)

| ID | Question | Evidence required | Tool | Decision rule | Status |
|---|---|---|---|---|---|
| R1 | Is a `Meal Type` row a meal start, an end, or a logging time? | Verbatim data-dictionary rows for `Timestamp`/`Meal Type`; the median glucose change around the row (is the rise already underway before it?). | `scripts/audit_meal_event_semantics.py` (not yet run on real data), dictionary text from the human | Rise begins after the row and the pre-row slope is flat: treat `t0` as start. Otherwise run the +-15/30 min shift sensitivity and revisit D1. | **OPEN** |
| R2 | Does a meal-end timestamp exist? | A dictionary check; the committed column list has none. | dictionary | None found: keep D1; the +20 min fallback appears only in the sensitivity analysis. | **OPEN** (leaning: none) |
| R3 | Can native sampling times be inferred from the interpolated grid? | Second-difference concentration and phase stability on 5 participants, then all 45. The pushed audit's hard-coded text is not evidence (section D). | `scripts/audit_cgm_sampling_phase.py` (synthetic-tested only) | Fingerprint on >= 90% of evaluated participants on every channel and enough detectable slope changes: provisional use for gap checks only. Otherwise lag guard only. Never recover "native timestamps" from integers or row positions. | **OPEN** |
| R4 | Lag-guard policy for CGM-derived features. | R3 result; the mutation tests already enforce it for baseline and trend. | tests | Default stays: use only values at least one native interval old. | Implemented as default; value **OPEN** |
| R5 | Do participants differ in schema? | Committed fact: participant files have 13 / 14 / 15 columns (2 / 32 / 11). Which columns differ, and who lacks Dexcom, Libre, HR or METs, is unknown. | `scripts/build_event_table.py` prints `schema` (names and counts, no ids) | An explicit eligibility set per analysis; files lacking the channel are logged exclusions, never silent. | **OPEN** (exclusion logging implemented) |
| R6 | Gap and window thresholds (blueprint 30 min vs code 15). | Distribution of gap lengths and window completeness per channel. | `build_event_table.py` exclusion counts, `audit_cgm_sampling_phase.py` | Choose before looking at model results; report the other value as sensitivity. | **OPEN** |
| R7 | Overlapping meals: how many are lost, and does isolation bias the evaluation? | Counts of meals with overlap flags; results with and without isolation. | `build_event_table.py` | Primary = isolated; report `--allow-overlap` as sensitivity. | **OPEN** |
| R8 | Is the lag-guarded baseline materially different from the grid value at `t0`? | Paired difference on real events. | to be added after R3 | Keep the guard unless shown unnecessary. | **OPEN** |
| R9 | Are there enough >= 180 mg/dL events, per glycaemic group, for the planned comparisons? | Event counts by class and by group (`bio.csv` not ingested yet). | `build_event_table.py` (overall counts now; groups need `bio.csv`) | Too sparse (especially healthy): the blueprint's 140 mg/dL fallback or per-group reporting, **decided before any model results**. | **OPEN** |
| R10 | Activity covariate: coverage of METs/HR before meals; definition of an "active day". | Coverage distribution; the blueprint normalises METs without defining how. | to be added | Define the cut from training data only; keep unusable-activity meals in Models A/B. | **OPEN** |
| R11 | Duplicate timestamps in a file. | Count of files and rows affected. | `build_event_table.py` prints `duplicate_timestamp_rows_dropped` | Currently `keep_first` with the count reported, or `raise`. Not validated. | **OPEN** |
| R12 | Does the date shift preserve time of day? | Hour-of-day distribution by meal label. | `audit_meal_event_semantics.py` | Decides whether time-of-day features are allowed. | **OPEN** |
| R13 | Which clinical variables exist and are safe to use? | The `bio.csv` header names (24 columns) and the glycaemic-group column. | `scripts/audit_bio_groups.py` prints the column names, candidate identifier / A1c / group / medication columns and the mapping status (not yet run on the real file) | Use only variables the blueprint lists and the file actually contains. | **OPEN (blocked on human)** |
| R14 | Is the Bayesian model's observation/prior structure defensible on real data? | Residual diagnostics on real events: variance vs carbs, skew of the peak rise. See `docs/modelling_assumptions.md`. | after the event table exists | Gaussian, constant-variance, known noise variance are assumptions, not findings. | **OPEN** |
| R15 | Can the official meal end be reconstructed from the `Image path` rows without an assumption? | Per meal row: number of candidate photos before the next meal row (0 / 1 / many); minutes from the meal row to them; whether image FILE NAMES carry an explicit before/after marker; data-dictionary text. | `scripts/audit_meal_photo_pairing.py` (11 synthetic tests; run on the real data by the researcher) | Reconstructable only if (a) the dictionary or file names state which photo is the end photo, or (b) a documented, verified rule pairs them. A fixed duration or "next photo" or "next meal" is an assumption and must be recorded as a sensitivity analysis, never as ground truth. | **ANSWERED: NO (researcher-run audit, 45 files, 1,706 meal rows). 1,194 (69.99%) have exactly one later non-meal photo candidate; 140 (8.21%) have several; 372 (21.81%) have none; 62 meal rows have no image of their own; no file-name token reliably marks before/after; candidate timing is highly variable (median 15 min, maximum 915 min). Reported to me in chat; the JSON output is local and not committed.** Consequence: the primary analysis does not use photos (D9). |

## D. Claims in existing code with no committed evidence

- `scripts/audit_meal_events.py` (pushed) prints `[DOCUMENTED FACT] Meal Type indicates a meal start and
  identifies the meal` and `Amount Consumed is an estimated percentage of the meal consumed` as constant
  strings. The data dictionary is not in the repository. Treat them as **claims** until the verbatim
  dictionary rows are committed under R1.
- `scripts/audit_cgm_interpolation.py` (pushed) prints fixed conclusions ("~35-48%", "~40-60%", "phase NOT
  fixed") whatever the data are. The numbers are not reproducible from the repository.
- The blueprint says native-interval CGM files exist ("use native sensor timestamps, not the interpolated
  release file"). The README describes only `CGMacros-#.csv` per participant; no native export has been
  found. **Native readings are not available unless the human confirms an additional source** (H3).

## E. Structural facts committed so far (observed, causes not established)

From `data/audit/dataset_aggregate_summary.md` (derived from the committed real-run inventory):
45 participant CSVs, 687,580 rows in total; per-file rows 5,655 / 14,805 / 18,735 (min / median / max);
column counts 13 / 14 / 15 in 2 / 32 / 11 files; 7 files shorter than 14,400 rows; **all 45 row counts are
divisible by 5 and 44 of 45 by 15.** Consistent with a regular time grid built from 5- and 15-minute
devices; not evidence of how values were produced.
