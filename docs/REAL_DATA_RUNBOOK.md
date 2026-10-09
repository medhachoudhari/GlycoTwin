# Real-data validation runbook (Windows PowerShell)

**Status: nothing in this file has been run.** The dataset and the local forecast files are not available to the engineering environment; every command below is for the researcher's machine.
Every argument was read from the scripts' `argparse` definitions (`scripts/build_event_table.py`, `check_leakage_on_data.py`, `audit_bio_groups.py`, `run_model_a.py`, `run_model_b.py`,
`run_model_c.py`, `compare_models_b_c.py`, `replay_participant.py`). Not clinically validated; no medical advice.

## Protocol (fixed; sensitivity analyses never replace it)
**Primary:** channel Libre GL; CGM gap limit 15 minutes; the locked event definition (anchor = `Meal Type` row timestamp, window (t0, t0+120 min], label = max available glucose >= 180 mg/dL);
isolated meals required; empirical-Bayes priors; fold seed 0; participant-level 5-fold folds stratified by glycaemic group; no imputation.
**Exploratory, prespecified (D-10):** active vs sedentary = above / at-or-below the participant's own median pre-meal activity (`docs/activity_definition.md`).
**Sensitivity (separate analyses, S1-S4):** S1 gap 30; S2 blueprint prior; S3 gamma width 0.25 / 0.5 / 1 / 2 (blueprint prior, Model C only); S4 Dexcom GL.
**Prior-versus-prior contrast:** `scripts\compare_priors.py` (section 3b, rule in `docs/prior_comparison.md`). It is a prespecified screen that triggers human review, not proof; the blueprint prior stays opt-in.

## Folder convention (one folder per run, so no file name is ambiguous and nothing existing is overwritten)
All run folders live under `data\interim\runs\` (git-ignored). Existing outputs in `data\processed` and `data\interim\audit_local` are not touched by anything below.

| Run folder | What |
|---|---|
| `primary_Libre_gap15` | primary analysis: table, Models A/B/C, paired comparison, replay |
| `S1_Libre_gap30` | S1: 30-minute gap limit |
| `S2S3_Libre_gap15_blueprint` | S2/S3: blueprint prior and the four gamma widths, on the PRIMARY event table |
| `S4_Dexcom_gap15` | S4: Dexcom GL, full pipeline |

## 0. One-time setup per session
```powershell
cd C:\path\to\GlycoTwin
.venv\Scripts\Activate.ps1
$env:GLYCOTWIN_DATA_ROOT = "D:\data\CGMacros"          # outside the repository
python -m pytest -p no:cacheprovider -q                  # all tests must pass before real runs
git rev-parse HEAD; git status --short                   # record the code revision and whether the tree is dirty (manifests record both)
git check-ignore -v data\interim\runs\x.json data\processed\x.csv   # both lines must print a rule (ignored)

# fingerprint your EXISTING outputs so you can prove afterwards that nothing was touched
New-Item -ItemType Directory -Force data\interim\runs | Out-Null
Get-ChildItem data\processed, data\interim\audit_local -File -ErrorAction SilentlyContinue | Get-FileHash -Algorithm SHA256 |
  Select-Object Hash, Path | Export-Csv data\interim\runs\existing_outputs_before.csv -NoTypeInformation -Encoding ascii
```

## 1. Primary analysis (Libre GL, gap 15)
```powershell
$RUN = "data\interim\runs\primary_Libre_gap15"
if (Test-Path "$RUN\event_table_Libre_GL.csv") { throw "$RUN already holds a run; choose a new folder name (never reuse one)" }
New-Item -ItemType Directory -Force $RUN | Out-Null

# 1a. group mapping must be VERIFIED (not positional) before anything else
python scripts\audit_bio_groups.py --report-out "$RUN\bio_groups.json"

# 1b. leakage unit test on the real files (exit code 0 required)
python scripts\check_leakage_on_data.py --channel "Libre GL" --max-gap-minutes 15
echo "leakage exit code: $LASTEXITCODE"

# 1c. event table (+ settings sidecar event_table_Libre_GL.settings.json written beside it)
python scripts\build_event_table.py --channel "Libre GL" --max-gap-minutes 15 --seed 0 `
  --table-out "$RUN\event_table_Libre_GL.csv" --report-out "$RUN\event_counts_Libre_GL.json"

# 1c-check. the sidecar must say channel Libre GL, max_cgm_gap_minutes 15, require_isolated true, window 120, threshold 180
Get-Content "$RUN\event_table_Libre_GL.settings.json"
# optional, read-only: are the event ids of the new table the same as your existing primary table? (no output = identical sets)
# This compares ids only; the build is deterministic, so identical settings should reproduce the same ids.
$new = (Import-Csv "$RUN\event_table_Libre_GL.csv").event_id
$old = (Import-Csv "data\processed\event_table_Libre_GL.csv").event_id
Compare-Object ($old | Sort-Object) ($new | Sort-Object)

# 1d. per-group event counts
python scripts\audit_bio_groups.py --event-table "$RUN\event_table_Libre_GL.csv" --report-out "$RUN\bio_groups.json"

# 1e. Model A (all core-eligible events)
python scripts\run_model_a.py --channel "Libre GL" --seed 0 --n-boot 1000 --event-table "$RUN\event_table_Libre_GL.csv" `
  --report-out "$RUN\model_a_Libre_GL.json" --oof-out "$RUN\model_a_oof_Libre_GL.csv" --folds-out "$RUN\model_a_folds_Libre_GL.json"

# 1f. Model B on Model C's exact (activity-eligible) events; --out-dir puts JSON and CSV in the run folder
python scripts\run_model_b.py --channel "Libre GL" --seed 0 --n-boot 1000 --population activity-eligible `
  --event-table "$RUN\event_table_Libre_GL.csv" --out-dir $RUN

# 1g. Model C
python scripts\run_model_c.py --channel "Libre GL" --seed 0 --n-boot 1000 --event-table "$RUN\event_table_Libre_GL.csv" --out-dir $RUN

# 1g-check. every downstream output holds exactly the event ids of the new table's eligible events (no output = identical sets)
$tbl = Import-Csv "$RUN\event_table_Libre_GL.csv"
$act = ($tbl | Where-Object { $_.eligible_core -eq "True" -and $_.eligible_activity -eq "True" }).event_id | Sort-Object
$b   = (Import-Csv "$RUN\model_b_sequential_forecasts_Libre_GL_activity_eligible.csv").event_id | Sort-Object
$c   = (Import-Csv "$RUN\model_c_sequential_forecasts_Libre_GL.csv").event_id | Sort-Object
$a   = (Import-Csv "$RUN\model_a_oof_Libre_GL.csv").event_id | Sort-Object
Compare-Object $b $c; Compare-Object $b $act
$core = ($tbl | Where-Object { $_.eligible_core -eq "True" }).event_id | Sort-Object
Compare-Object $a $core

# 1h. participant -> group file for the subgroup analysis (two columns, ids are pseudonymous file stems; ASCII avoids a BOM)
$f = Get-Content "$RUN\model_a_folds_Libre_GL.json" -Raw | ConvertFrom-Json
$f.groups.PSObject.Properties | ForEach-Object { [pscustomobject]@{participant_id=$_.Name; group=$_.Value} } |
  Export-Csv "$RUN\participant_groups.csv" -NoTypeInformation -Encoding ascii

# 1i. final paired Model A / B / C comparison (ONE invocation; add --expect-events/--expect-participants with the counts from 1c)
python scripts\compare_models_b_c.py --channel "Libre GL" --n-boot 2000 --seed 0 --seed-check 1,2,3 `
  --model-b "$RUN\model_b_sequential_forecasts_Libre_GL_activity_eligible.csv" `
  --model-c "$RUN\model_c_sequential_forecasts_Libre_GL.csv" `
  --model-a "$RUN\model_a_oof_Libre_GL.csv" --groups-file "$RUN\participant_groups.csv" `
  --report-out "$RUN\model_b_vs_c_Libre_GL.json" --svg-out "$RUN\reliability_b_c.svg"

# 1j. replay one participant through the in-memory twin (leave-one-participant-out prior; counts only on screen)
python scripts\replay_participant.py --channel "Libre GL" --event-table "$RUN\event_table_Libre_GL.csv" --participant-index 0 --out-dir $RUN
```
Add `--expect-events 963 --expect-participants 34` to 1i **only** if 1c reproduces those counts (they came from your earlier run with these settings); a refusal means the inputs differ, which must be explained, not silenced.

**Verify (primary):**
```powershell
$a = (Get-Content "$RUN\model_a_Libre_GL.json" -Raw | ConvertFrom-Json).manifest
$b = (Get-Content "$RUN\model_b_Libre_GL_activity_eligible.json" -Raw | ConvertFrom-Json).manifest
$c = (Get-Content "$RUN\model_c_Libre_GL.json" -Raw | ConvertFrom-Json).manifest
$a.fold_assignment_sha256; $b.fold_assignment_sha256; $c.fold_assignment_sha256     # all three identical
$a.event_table_file_sha256; $b.event_table_file_sha256; $c.event_table_file_sha256  # all three identical (same table file)
$c.event_table_settings                                                           # channel, max_cgm_gap_minutes = 15, require_isolated = True, window 120, threshold 180
$c.prior; $c.protocol_arguments; $c.git_commit; $c.working_tree_dirty
(Get-Content "$RUN\model_b_vs_c_Libre_GL.json" -Raw | ConvertFrom-Json).integrity   # all true, each participant in exactly one fold
```
`working_tree_dirty = True` means the code differed from `git_commit`; commit (your decision) before the final numbers if you need a clean revision.

## 2. S1: 30-minute gap limit (a different event set; reported separately, never merged into the primary)
```powershell
$RUN1 = "data\interim\runs\S1_Libre_gap30"
New-Item -ItemType Directory -Force $RUN1 | Out-Null
python scripts\check_leakage_on_data.py --channel "Libre GL" --max-gap-minutes 30
python scripts\build_event_table.py --channel "Libre GL" --max-gap-minutes 30 --seed 0 `
  --table-out "$RUN1\event_table_Libre_GL.csv" --report-out "$RUN1\event_counts_Libre_GL.json"
# record the new counts (event_counts_Libre_GL.json) BEFORE running any model, then:
python scripts\run_model_a.py --channel "Libre GL" --seed 0 --n-boot 1000 --event-table "$RUN1\event_table_Libre_GL.csv" `
  --report-out "$RUN1\model_a_Libre_GL.json" --oof-out "$RUN1\model_a_oof_Libre_GL.csv" --folds-out "$RUN1\model_a_folds_Libre_GL.json"
python scripts\run_model_b.py --channel "Libre GL" --seed 0 --n-boot 1000 --population activity-eligible --event-table "$RUN1\event_table_Libre_GL.csv" --out-dir $RUN1
python scripts\run_model_c.py --channel "Libre GL" --seed 0 --n-boot 1000 --event-table "$RUN1\event_table_Libre_GL.csv" --out-dir $RUN1
$f = Get-Content "$RUN1\model_a_folds_Libre_GL.json" -Raw | ConvertFrom-Json
$f.groups.PSObject.Properties | ForEach-Object { [pscustomobject]@{participant_id=$_.Name; group=$_.Value} } | Export-Csv "$RUN1\participant_groups.csv" -NoTypeInformation -Encoding ascii
python scripts\compare_models_b_c.py --channel "Libre GL" --n-boot 2000 --seed 0 --seed-check 1,2,3 `
  --model-b "$RUN1\model_b_sequential_forecasts_Libre_GL_activity_eligible.csv" --model-c "$RUN1\model_c_sequential_forecasts_Libre_GL.csv" `
  --model-a "$RUN1\model_a_oof_Libre_GL.csv" --groups-file "$RUN1\participant_groups.csv" `
  --report-out "$RUN1\model_b_vs_c_Libre_GL.json" --svg-out "$RUN1\reliability_b_c.svg"
```
Do not pass `--expect-*` here unless you wrote down the new counts first. The two gap settings give different samples; report which participants and events entered or left, not a paired test.
Verify `event_table_settings.max_cgm_gap_minutes = 30` in each manifest.

## 3. S2 and S3: blueprint prior and the four gamma widths (primary event table, primary folds)
These runs reuse the PRIMARY event table and Model A output, so the events, folds and seed are identical to the primary run. Only the prior differs.
```powershell
$T   = "data\interim\runs\primary_Libre_gap15\event_table_Libre_GL.csv"
$RUN2 = "data\interim\runs\S2S3_Libre_gap15_blueprint"
New-Item -ItemType Directory -Force $RUN2 | Out-Null

# S2: blueprint prior, Model B and Model C (gamma width defaults to 0.5)
python scripts\run_model_b.py --channel "Libre GL" --seed 0 --n-boot 1000 --population activity-eligible --prior-scheme blueprint --event-table $T --out-dir $RUN2
python scripts\run_model_c.py --channel "Libre GL" --seed 0 --n-boot 1000 --prior-scheme blueprint --event-table $T --out-dir $RUN2

# S3: the four prespecified gamma widths (Model C only; 0.5 repeats the S2 Model C run and must reproduce it exactly)
foreach ($w in 0.25, 0.5, 1, 2) {
  python scripts\run_model_c.py --channel "Libre GL" --seed 0 --n-boot 1000 --prior-scheme blueprint --gamma-relative-sd $w --event-table $T --out-dir $RUN2
}

# B-versus-C (and Model A) under the blueprint prior, one report per gamma width; --groups-file from the primary run
$G = "data\interim\runs\primary_Libre_gap15\participant_groups.csv"
$A = "data\interim\runs\primary_Libre_gap15\model_a_oof_Libre_GL.csv"
foreach ($w in 0.25, 0.5, 1, 2) {
  python scripts\compare_models_b_c.py --channel "Libre GL" --n-boot 2000 --seed 0 `
    --model-b "$RUN2\model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv" `
    --model-c "$RUN2\model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma$w.csv" `
    --model-a $A --groups-file $G --report-out "$RUN2\model_b_vs_c_blueprint_gamma$w.json"
}
```
### 3b. Prior-versus-prior comparison (one report per gamma width; each width is screened separately)
```powershell
$P = "data\interim\runs\primary_Libre_gap15"
foreach ($w in 0.25, 0.5, 1, 2) {
  python scripts\compare_priors.py `
    --b-eb "$P\model_b_sequential_forecasts_Libre_GL_activity_eligible.csv" --b-eb-report "$P\model_b_Libre_GL_activity_eligible.json" `
    --b-bp "$RUN2\model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv" --b-bp-report "$RUN2\model_b_Libre_GL_activity_eligible_prior-blueprint.json" `
    --c-eb "$P\model_c_sequential_forecasts_Libre_GL.csv" --c-eb-report "$P\model_c_Libre_GL.json" `
    --c-bp "$RUN2\model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma$w.csv" --c-bp-report "$RUN2\model_c_Libre_GL_prior-blueprint_gamma$w.json" `
    --expect-gamma $w --report-out "$RUN2\prior_comparison_gamma$w.json"
}
```
Add `--expect-events <n> --expect-participants <n>` with the counts from step 1c. A refusal (exit 3, `REFUSED: ...`) means the four arms are not one evaluation (different table, folds, seed, events, labels or prior metadata); fix the cause, never edit the files.
The report holds the five contrasts (B and C blueprint-minus-empirical-Bayes, C-minus-B under each prior, and the change in the C-minus-B contrast) for Brier, log loss, ECE (10 and 5 bins) and rise MAE, plus the prespecified adoption screen.

Output names: Model B `model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv` (+ `.json`, trajectories); Model C `model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma<w>.csv`. They never overwrite the primary files.
**Verify:** each manifest has `prior.scheme = blueprint`, the intended `prior.gamma_relative_sd`, `prior.n_pooled_fallbacks` (expected 0 with groups of 14-16 participants; a nonzero count means a stratum was too small), the same `fold_assignment_sha256` as the primary run, and the same `event_table_file_sha256`.
Prespecified reading: report B-vs-C under each prior and each width; if the B-vs-C conclusion changes with the prior or the width, say it is prior-dependent. The blueprint prior becomes a candidate default only under the rule in the session report (needs your approval).

## 4. S4: Dexcom GL (full pipeline, reported separately; channels are never averaged)
```powershell
$RUN4 = "data\interim\runs\S4_Dexcom_gap15"
New-Item -ItemType Directory -Force $RUN4 | Out-Null
python scripts\check_leakage_on_data.py --channel "Dexcom GL" --max-gap-minutes 15
python scripts\build_event_table.py --channel "Dexcom GL" --max-gap-minutes 15 --seed 0 `
  --table-out "$RUN4\event_table_Dexcom_GL.csv" --report-out "$RUN4\event_counts_Dexcom_GL.json"
python scripts\run_model_a.py --channel "Dexcom GL" --seed 0 --n-boot 1000 --event-table "$RUN4\event_table_Dexcom_GL.csv" `
  --report-out "$RUN4\model_a_Dexcom_GL.json" --oof-out "$RUN4\model_a_oof_Dexcom_GL.csv" --folds-out "$RUN4\model_a_folds_Dexcom_GL.json"
python scripts\run_model_b.py --channel "Dexcom GL" --seed 0 --n-boot 1000 --population activity-eligible --event-table "$RUN4\event_table_Dexcom_GL.csv" --out-dir $RUN4
python scripts\run_model_c.py --channel "Dexcom GL" --seed 0 --n-boot 1000 --event-table "$RUN4\event_table_Dexcom_GL.csv" --out-dir $RUN4
$f = Get-Content "$RUN4\model_a_folds_Dexcom_GL.json" -Raw | ConvertFrom-Json
$f.groups.PSObject.Properties | ForEach-Object { [pscustomobject]@{participant_id=$_.Name; group=$_.Value} } | Export-Csv "$RUN4\participant_groups.csv" -NoTypeInformation -Encoding ascii
python scripts\compare_models_b_c.py --channel "Dexcom GL" --n-boot 2000 --seed 0 --seed-check 1,2,3 `
  --model-b "$RUN4\model_b_sequential_forecasts_Dexcom_GL_activity_eligible.csv" --model-c "$RUN4\model_c_sequential_forecasts_Dexcom_GL.csv" `
  --model-a "$RUN4\model_a_oof_Dexcom_GL.csv" --groups-file "$RUN4\participant_groups.csv" `
  --report-out "$RUN4\model_b_vs_c_Dexcom_GL.json" --svg-out "$RUN4\reliability_b_c.svg"
```

## 4b. Prove that no existing output was touched
```powershell
Get-ChildItem data\processed, data\interim\audit_local -File -ErrorAction SilentlyContinue | Get-FileHash -Algorithm SHA256 |
  Select-Object Hash, Path | Export-Csv data\interim\runs\existing_outputs_after.csv -NoTypeInformation -Encoding ascii
Compare-Object (Import-Csv data\interim\runs\existing_outputs_before.csv | ForEach-Object { "$($_.Hash) $($_.Path)" }) `
               (Import-Csv data\interim\runs\existing_outputs_after.csv  | ForEach-Object { "$($_.Hash) $($_.Path)" })
```
No output means every pre-existing file in `data\processed` and `data\interim\audit_local` is byte-identical to before.

## 5. Privacy and Git rules
* Everything above writes under `data\interim\runs\` or reads `data\interim`; both are git-ignored, as are all `*.csv` files. `*.json` and `*.svg` are NOT ignored outside `data\`; never point `--svg-out` or `--report-out` outside `data\interim\`.
* Never write into `data\audit` (tracked). Never use `git add -A` / `git add .`; stage named files only and read `git status` first.
* Screen output of these scripts is aggregate-only. The `*_trajectories_*.json`, `*_folds_*.json`, forecast CSVs, `participant_groups.csv` and replay JSON are participant-level (pseudonymous ids): local only.
* Keep a text record of the commands run, `git rev-parse HEAD`, the test count and `Get-FileHash -Algorithm SHA256` of the table and each forecast file.

## 6. What the reports mean
Differences in `model_b_vs_c_*.json` are C minus B (negative favours C for Brier, log loss, ECE, MAE); an interval containing 0 is inconclusive. The active-versus-sedentary,
cold-start (first 3 meals) versus experienced (10+), glycaemic-group and tertile sections are exploratory and descriptive; there is no multiplicity adjustment. No result in any
of these files may be described as showing that Model C outperforms Model B unless the prespecified rules in `docs/INNOVATION_ROADMAP.md` section 3 are met.
