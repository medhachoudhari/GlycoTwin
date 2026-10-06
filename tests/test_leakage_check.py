"""The real-data leakage check must PASS on the real pipeline and FAIL when the pipeline leaks."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import glycotwin.data.events as events
from glycotwin.data.leakage_check import check_feature_leakage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("check_leakage_on_data", ROOT / "scripts" / "check_leakage_on_data.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def frame(n=1200, meals=(400,)):
    t = pd.date_range("2000-01-01", periods=n, freq="1min")
    g = 100 + 0.05 * np.arange(n)
    mt, cb = [np.nan] * n, [np.nan] * n
    for i in meals:
        mt[i], cb[i] = "Lunch", 45.0
    return pd.DataFrame({"Timestamp": t, "Dexcom GL": g, "Libre GL": g, "HR": 70.0, "METs": 1.4,
                         "Meal Type": mt, "Carbs": cb, "Calories": np.nan, "Protein": np.nan, "Fat": np.nan, "Fiber": np.nan})


def test_real_pipeline_passes_both_checks():
    r = check_feature_leakage(frame(), "P1")
    assert r["checked"] and r["passed"] and r["blueprint_mismatched_columns"] == [] and r["lag_guard_mismatched_columns"] == []


def test_no_window_valid_event_is_reported_not_passed():
    g = frame(); g["Dexcom GL"] = np.nan
    assert check_feature_leakage(g, "P1") == {"checked": False, "reason": "no_window_valid_event"}


def test_a_pipeline_that_reads_the_future_is_caught(monkeypatch):
    real = events.pre_meal_activity

    def leaky(df, t0, col="METs", hours=4.0, min_coverage=0.5):          # peeks 30 minutes past the meal
        return real(df, pd.Timestamp(t0) + pd.Timedelta(minutes=30), col, hours, min_coverage)
    monkeypatch.setattr(events, "pre_meal_activity", leaky)
    r = check_feature_leakage(frame(), "P1")
    assert not r["passed"] and "activity_level" in r["blueprint_mismatched_columns"]


def test_a_baseline_that_ignores_the_lag_guard_passes_the_blueprint_test_but_not_the_stronger_one(monkeypatch):
    """A pipeline that uses the reading AT t0 as its baseline never reads past t0, so the blueprint's test
    passes; the lag guard exists precisely because the reading at t0 may blend in later readings."""
    real = events.extract_meal_events_detailed
    monkeypatch.setattr(events, "extract_meal_events_detailed", lambda df, **kw: real(df, **{**kw, "baseline_lag_minutes": 0}))
    r = check_feature_leakage(frame(), "P1")
    assert r["blueprint_test_passed"] and not r["lag_guard_test_passed"] and not r["passed"]
    assert "baseline_glucose" in r["lag_guard_mismatched_columns"]


def test_cli_reports_aggregate_only_and_exit_codes(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir()
    for pid in ("CGMacros-001", "CGMacros-002"):
        d = root / pid; d.mkdir()
        f = frame(); f["Timestamp"] = f["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        f.to_csv(d / f"{pid}.csv", index=False)
    assert cli.main(["--data-root", str(root)]) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)
    assert rep["result"] == {"passed": 2} and rep["all_checked_participants_pass"]
    assert "CGMacros-00" not in text and "2000-01-01" not in text
    assert cli.main(["--data-root", str(tmp_path / "missing")]) == 2
