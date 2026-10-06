"""scripts/audit_meal_event_semantics.py on SYNTHETIC participant files with a KNOWN glucose pattern.

This script is the planned evidence for rule R1 (does a Meal Type row mark a meal start or a later
point?). The tests show it separates the two cases when the pattern is present, counts labels,
overlaps and missing values correctly, never prints identifiers, and never modifies the data.
They do NOT show which case holds in CGMacros: that needs the real run.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("audit_meal_event_semantics", ROOT / "scripts" / "audit_meal_event_semantics.py")
sem = importlib.util.module_from_spec(_spec)
sys.modules["audit_meal_event_semantics"] = sem
_spec.loader.exec_module(sem)


def participant(path, mode="start", n=1500, meals=(300, 700, 1100), labels=None, extra=None):
    """mode 'start': glucose rises AFTER the row. mode 'end': the rise began 40 minutes BEFORE the row."""
    t = pd.date_range("2000-01-01 06:00", periods=n, freq="1min")
    g = np.full(n, 100.0)
    for m in meals:
        k = np.arange(n) - (m if mode == "start" else m - 40)
        g += np.where((k > 0) & (k < 90), 0.8 * k, 0) + np.where(k >= 90, 72 * np.exp(-(k - 90) / 60), 0)
    mt, cb = [np.nan] * n, [np.nan] * n
    for j, m in enumerate(meals):
        mt[m] = (labels or ["Lunch"] * len(meals))[j]
        cb[m] = 40.0
    d = {"Timestamp": t.strftime("%Y-%m-%d %H:%M:%S"), "Libre GL": g, "Dexcom GL": g, "HR": 70.0, "METs": 1.2, "Meal Type": mt,
         "Calories": np.where(pd.notna(cb), 300.0, np.nan), "Carbs": cb, "Protein": np.nan, "Fat": np.nan, "Fiber": np.nan,
         "Amount Consumed": np.where(pd.notna(cb), 100.0, np.nan), "Image path": "secret_photo.jpg"}
    d.update(extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(d).to_csv(path, index=False)


def run(root, tmp_path, capsys):
    assert sem.main(["--data-root", str(root), "--out", str(tmp_path / "o.json")]) == 0
    text = capsys.readouterr().out
    return json.loads(text), text


def probe(rep, chan="Dexcom GL"):
    return rep["glucose_change_vs_meal_row_median_mg_dl"][chan]


def test_a_meal_start_pattern_rises_after_the_row(tmp_path, capsys):
    participant(tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv", "start")
    p = probe(run(tmp_path / "ds", tmp_path, capsys)[0])
    assert p["share_rising_in_30min_after_row"] >= 0.9 and p["share_rising_in_30min_before_row"] <= 0.1
    assert p["median_delta_by_offset_min"]["60"] > 30 and abs(p["median_delta_by_offset_min"]["-30"]) < 2


def test_a_later_logging_pattern_is_already_rising_before_the_row(tmp_path, capsys):
    participant(tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv", "end")
    p = probe(run(tmp_path / "ds", tmp_path, capsys)[0])
    assert p["share_rising_in_30min_before_row"] >= 0.9
    assert p["median_delta_by_offset_min"]["-30"] < -10         # glucose 30 min before the row is well below its value AT the row


def test_the_two_patterns_are_clearly_distinguishable(tmp_path, capsys):
    participant(tmp_path / "a" / "x" / "CGMacros-001.csv", "start")
    participant(tmp_path / "b" / "x" / "CGMacros-001.csv", "end")
    a = probe(run(tmp_path / "a", tmp_path, capsys)[0]); b = probe(run(tmp_path / "b", tmp_path, capsys)[0])
    assert b["share_rising_in_30min_before_row"] - a["share_rising_in_30min_before_row"] >= 0.8


def test_label_spellings_are_counted_raw_and_normalised(tmp_path, capsys):
    participant(tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv", labels=["Lunch", "lunch ", "LUNCH"])
    rep, _ = run(tmp_path / "ds", tmp_path, capsys)
    ml = rep["meal_type_labels"]
    assert ml["distinct_raw"] == 3 and ml["distinct_after_strip_lower"] == 1 and ml["normalised_counts_top"] == {"lunch": 3}


def test_overlap_and_exact_duplicate_meal_times_are_counted(tmp_path, capsys):
    participant(tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv", meals=(300, 330, 900))
    rep, _ = run(tmp_path / "ds", tmp_path, capsys)
    mt = rep["meal_timing"]
    assert mt["consecutive_meal_pairs"] == 2 and mt["pairs_closer_than_120min"] == 1
    assert mt["gap_minutes_bucket_counts"]["[30,60)"] == 1 and mt["gap_minutes_bucket_counts"][">=240"] == 1
    assert mt["participant_days_by_meals_that_day"] == {"3": 1}


def test_missing_and_orphan_macros_are_separated_from_meal_rows(tmp_path, capsys):
    f = tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv"
    participant(f)
    df = pd.read_csv(f)
    df.loc[300, ["Calories", "Carbs"]] = np.nan                  # a meal row with no macros
    df.loc[50, "Carbs"] = 20.0                                   # macros on a row with no meal label
    df.to_csv(f, index=False)
    m = run(tmp_path / "ds", tmp_path, capsys)[0]["macros"]
    assert m["meal_rows_without_any_macro"] == 1 and m["macro_rows_without_meal_label"] == 1 and m["meal_rows_with_any_macro"] == 2


def test_feasibility_counts_use_the_inclusive_180_threshold(tmp_path, capsys):
    f = tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv"
    participant(f, meals=(300,))
    df = pd.read_csv(f)
    df["Dexcom GL"] = 100.0; df.loc[330:340, "Dexcom GL"] = 180.0           # peak exactly 180.0 after the meal
    df.to_csv(f, index=False)
    feas = run(tmp_path / "ds", tmp_path, capsys)[0]["descriptive_outcome_feasibility_NOT_a_target_decision"]["Dexcom GL"]
    assert feas["eligible_with_peak_ge_180_in_2h"] == 1 and feas["baseline_already_ge_180"] == 0


def test_a_file_without_one_channel_does_not_crash_and_omits_its_probe(tmp_path, capsys):
    f = tmp_path / "ds" / "CGMacros-001" / "CGMacros-001.csv"
    participant(f)
    pd.read_csv(f).drop(columns=["Dexcom GL"]).to_csv(f, index=False)
    rep, _ = run(tmp_path / "ds", tmp_path, capsys)
    assert "Libre GL" in rep["glucose_change_vs_meal_row_median_mg_dl"] and "Dexcom GL" not in rep["glucose_change_vs_meal_row_median_mg_dl"]


def test_output_has_no_identifiers_timestamps_or_image_paths_and_data_is_untouched(tmp_path, capsys):
    f = tmp_path / "ds" / "CGMacros-007" / "CGMacros-007.csv"
    participant(f)
    before = hashlib.sha256(f.read_bytes()).hexdigest()
    rep, text = run(tmp_path / "ds", tmp_path, capsys)
    for needle in ("CGMacros-007", "2000-01-01", "secret_photo", str(tmp_path)):
        assert needle not in text, needle
    assert rep["image_path_presence_counts_only"] == {"on_meal_rows": 3, "on_nonmeal_rows": 1497}
    assert hashlib.sha256(f.read_bytes()).hexdigest() == before
    assert json.loads((tmp_path / "o.json").read_text()) == rep


def test_errors_are_clear_and_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GLYCOTWIN_DATA_ROOT", raising=False)
    assert sem.main([]) == 2 and sem.main(["--data-root", str(tmp_path / "missing")]) == 2
    (tmp_path / "e").mkdir(); (tmp_path / "e" / "x.csv").write_text("a,b\n1,2\n")
    assert sem.main(["--data-root", str(tmp_path / "e")]) == 2
    assert "no CSV with both" in capsys.readouterr().err
