"""scripts/build_event_table.py end to end on a SYNTHETIC multi-participant tree (software test only)."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_event_table", ROOT / "scripts" / "build_event_table.py")
bet = importlib.util.module_from_spec(_spec)
sys.modules["build_event_table"] = bet
_spec.loader.exec_module(bet)


def _participant(path, n=1500, meals=(400, 1000), with_dexcom=True, hr=True):
    t = pd.date_range("2000-01-01", periods=n, freq="1min")
    g = 100 + 0.04 * np.arange(n)
    mt, cb = [np.nan] * n, [np.nan] * n
    for i in meals:
        mt[i], cb[i] = "Lunch", 40.0
    d = {"Timestamp": t.strftime("%Y-%m-%d %H:%M:%S"), "Libre GL": g, "METs": 1.2, "Meal Type": mt, "Carbs": cb,
         "Amount Consumed": 1.0, "Image path": "x.jpg"}
    if with_dexcom:
        d["Dexcom GL"] = g
    if hr:
        d["HR"] = 70.0
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(d).to_csv(path, index=False)


def _tree(root):
    _participant(root / "CGMacros-001" / "CGMacros-001.csv")
    _participant(root / "CGMacros-002" / "CGMacros-002.csv", meals=(300, 350, 900))
    _participant(root / "CGMacros-003" / "CGMacros-003.csv", with_dexcom=False, hr=False)   # a different column set
    pd.DataFrame({"HbA1c": [5.5]}).to_csv(root / "bio.csv", index=False)                     # not a participant file


def test_end_to_end_counts_schema_privacy_and_read_only(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir(); _tree(root)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}
    out_t, out_r = tmp_path / "t.csv", tmp_path / "r.json"
    assert bet.main(["--data-root", str(root), "--table-out", str(out_t), "--report-out", str(out_r)]) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)

    ev = rep["event_counts"]
    assert ev["n_participants"] == 3 and ev["overall"]["n_meal_rows"] == 7 and ev["reconciles"]
    assert ev["extraction_exclusion_reasons"] == {"cgm_channel_missing": 2}                  # participant 3 has no Dexcom column
    assert ev["overall"]["n_window_valid"] == 5 and ev["overall"]["n_eligible_core"] == 3    # 2 overlapping meals are ineligible
    assert rep["schema"]["n_distinct_column_sets"] == 2
    assert set(rep["schema"]["columns_missing_from_some_files"]) == {"Dexcom GL", "HR"}
    assert rep["schema"]["availability_counts"]["Dexcom GL"] == 2

    for needle in ("CGMacros-00", "2000-01-01", str(root)):
        assert needle not in text, needle
    assert json.loads(out_r.read_text()) == rep
    table = pd.read_csv(out_t)
    assert len(table) == 5 and "Amount Consumed" not in table.columns and not any("image" in c.lower() for c in table.columns)
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")} == before   # dataset untouched


def test_other_channel_and_allow_overlap_change_the_counts(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir(); _tree(root)
    common = ["--data-root", str(root), "--table-out", str(tmp_path / "t.csv"), "--report-out", str(tmp_path / "r.json")]
    assert bet.main(common + ["--allow-overlap"]) == 0
    assert json.loads(capsys.readouterr().out)["event_counts"]["overall"]["n_eligible_core"] == 5
    assert bet.main(common + ["--channel", "Libre GL"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["event_counts"]["overall"]["n_window_valid"] == 7 and not r["event_counts"]["extraction_exclusion_reasons"]


def test_errors_are_clear_and_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GLYCOTWIN_DATA_ROOT", raising=False)
    assert bet.main([]) == 2
    assert bet.main(["--data-root", str(tmp_path / "missing")]) == 2
    empty = tmp_path / "e"; empty.mkdir(); (empty / "x.csv").write_text("a,b\n1,2\n")
    assert bet.main(["--data-root", str(empty)]) == 2
    err = capsys.readouterr().err
    assert "GLYCOTWIN_DATA_ROOT" in err and "no CSV with both" in err


def test_schema_report_groups_by_exact_column_set():
    r = bet.schema_report({"a": ["Timestamp", "X"], "b": ["Timestamp", "X"], "c": ["Timestamp"]})
    assert r["n_distinct_column_sets"] == 2 and r["columns_in_every_file"] == ["Timestamp"]
    assert r["column_set_groups"][0]["n_files"] == 2 and r["availability_counts"]["X"] == 2
