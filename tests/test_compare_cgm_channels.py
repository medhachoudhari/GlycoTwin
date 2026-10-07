"""scripts/compare_cgm_channels.py on SYNTHETIC files only (software test; says nothing about CGMacros)."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.data.events import build_event_table

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ccc = _load("compare_cgm_channels")
bet = _load("build_event_table")
N = 1500


def make(path, libre=None, dexcom=None, meals=(400, 900), dexcom_col=True, dexcom_base=103.0):
    """Libre flat 100 and Dexcom flat `dexcom_base`, plus {row: value} overrides."""
    t = pd.date_range("2000-01-01", periods=N, freq="1min")
    lib = np.full(N, 100.0)
    dex = np.full(N, dexcom_base)
    for r, v in (libre or {}).items():
        lib[r] = v
    for r, v in (dexcom or {}).items():
        dex[r] = v
    mt, cb = [np.nan] * N, [np.nan] * N
    for i in meals:
        mt[i], cb[i] = "Lunch", 40.0
    d = {"Timestamp": t.strftime("%Y-%m-%d %H:%M:%S"), "Libre GL": lib, "METs": 1.2, "Meal Type": mt, "Carbs": cb,
         "Amount Consumed": 1.0, "Image path": "x.jpg"}
    if dexcom_col:
        d["Dexcom GL"] = dex
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(d).to_csv(path, index=False)


def tree(root):
    f = lambda k: root / f"CGMacros-00{k}" / f"CGMacros-00{k}.csv"
    # P1: meal400 Libre 185 vs Dexcom 175 (Libre+ / Dexcom-, 10 mg/dL apart); meal900 both below
    make(f(1), libre={430: 185.0}, dexcom={430: 175.0})
    # P2: meal400 Libre 150 vs Dexcom 190 (Libre- / Dexcom+, 40 apart); meal900 both 200
    make(f(2), libre={430: 150.0, 930: 200.0}, dexcom={430: 190.0, 930: 200.0})
    # P3: Dexcom has a 26 minute hole in the first window (Dexcom window invalid); meal900 both 181
    d3 = {r: np.nan for r in range(430, 456)}; d3[930] = 181.0
    make(f(3), libre={930: 181.0}, dexcom=d3)
    # P4: no Dexcom column at all
    make(f(4), libre={430: 190.0}, dexcom_col=False)
    pd.DataFrame({"HbA1c": [5.5]}).to_csv(root / "bio.csv", index=False)


@pytest.fixture
def report(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir(); tree(root)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}
    out = tmp_path / "r.json"
    assert ccc.main(["--data-root", str(root), "--report-out", str(out)]) == 0
    text = capsys.readouterr().out
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}   # read-only
    return json.loads(text), text, out, root


# ------------------------------------------------------------------ end to end on a tree with known answers

def test_populations_are_kept_apart_and_availability_is_reconciled(report):
    rep, *_ = report
    assert rep["n_participants"] == 4 and rep["n_meal_rows"] == 8 and rep["meal_row_universe_identical_in_both_channels"]
    w = rep["window_availability_over_all_meal_rows"]
    assert (w["valid_in_both"], w["valid_in_libre_only"], w["valid_in_dexcom_only"], w["valid_in_neither"]) == (5, 3, 0, 0)
    assert w["share_either_channel_missing_or_incomplete"] == pytest.approx(3 / 8)
    assert rep["extraction_exclusion_reasons"]["dexcom"] == {"internal_gap_exceeds_limit": 1, "cgm_channel_missing": 2}
    assert rep["extraction_exclusion_reasons"]["libre"] == {}
    pm = rep["populations_matched"]
    assert pm["extraction_valid_both"] == 5 and pm["core_eligible_both"] == 5 and pm["activity_eligible_both"] == 5
    c = rep["per_channel_counts_same_as_build_event_table"]
    assert c["libre"]["extraction_valid"] == 8 and c["dexcom"]["extraction_valid"] == 5


def test_confusion_matrix_direction_and_close_disagreements(report):
    rep, *_ = report
    p = rep["comparison_core_eligible_matched_PRIMARY"]
    assert p["n_matched_events"] == 5 and p["n_participants"] == 3
    assert p["confusion_libre_rows_dexcom_columns"] == {
        "libre_pos_dexcom_pos": 2, "libre_pos_dexcom_neg": 1, "libre_neg_dexcom_pos": 1, "libre_neg_dexcom_neg": 1}
    lab = p["labels"]
    assert lab["n_disagree"] == 2 and lab["share_disagree"] == pytest.approx(0.4)
    assert lab["libre_positive_dexcom_negative"] == 1 and lab["libre_negative_dexcom_positive"] == 1
    assert lab["libre_positive_rate"] == pytest.approx(3 / 5) and lab["dexcom_positive_rate"] == pytest.approx(3 / 5)
    tp = p["threshold_proximity"]
    assert tp["disagreements_with_abs_max_difference_within_delta"] == 1       # 185 vs 175: exactly 10 apart
    assert tp["disagreements_with_abs_max_difference_beyond_delta"] == 1       # 150 vs 190: 40 apart
    assert tp["share_of_disagreements_within_delta"] == pytest.approx(0.5)
    assert p["disagreement_direction_of_max_difference"] == {
        "libre_higher_max_in_disagreements": 1, "dexcom_higher_max_in_disagreements": 1, "equal_max_in_disagreements": 0}


def test_difference_statistics_use_libre_minus_dexcom(report):
    rep, *_ = report
    p = rep["comparison_core_eligible_matched_PRIMARY"]
    # peaks (L, D): (185,175) (100,103) (150,190) (200,200) (181,181) -> differences 10, -3, -40, 0, 0
    d = p["window_max_difference_libre_minus_dexcom_mg_dl"]
    assert d["n"] == 5 and d["mean"] == pytest.approx(-33 / 5) and d["min"] == -40 and d["max"] == 10
    assert p["window_max_abs_difference_mg_dl"]["max"] == 40
    assert p["window_max_abs_difference_within"]["<=10_mg_dl"] == pytest.approx(4 / 5)
    b = p["baseline_difference_libre_minus_dexcom_mg_dl"]                          # Libre 100 vs Dexcom 103 before every meal
    assert b["mean"] == pytest.approx(-3.0) and b["sd"] == pytest.approx(0.0) and b["n"] == 5
    assert p["window_completeness"]["events_either_channel_below_1"] == 0


def test_output_is_aggregate_only_and_matches_the_local_copy(report):
    rep, text, out, root = report
    for needle in ("CGMacros-00", "2000-01-01", ".jpg", str(root), "meal_time", "event_id", "participant_id"):
        assert needle not in text, needle
    assert json.loads(out.read_text()) == rep
    assert "NOT a validation" in rep["_what_this_is"]
    assert "meal_end" not in text.replace("no meal_end", "")


def test_per_channel_counts_equal_build_event_table_on_the_same_files(report, tmp_path, capsys):
    """The comparison must reuse the event definition, not re-implement it: its per-channel counts have to equal
    what build_event_table.py reports for the same files and defaults."""
    rep, _, _, root = report
    for ch, key in (("Libre GL", "libre"), ("Dexcom GL", "dexcom")):
        capsys.readouterr()
        assert bet.main(["--data-root", str(root), "--channel", ch, "--table-out", str(tmp_path / f"{key}.csv"),
                         "--report-out", str(tmp_path / f"{key}.json")]) == 0
        ov = json.loads(capsys.readouterr().out)["event_counts"]["overall"]
        c = rep["per_channel_counts_same_as_build_event_table"][key]
        assert (c["extraction_valid"], c["core_eligible"], c["activity_eligible"], c["core_eligible_positive"],
                c["core_eligible_negative"]) == (ov["n_window_valid"], ov["n_eligible_core"], ov["n_eligible_activity"],
                                                  ov["n_positive"], ov["n_negative"])


def test_forcing_one_baseline_lag_removes_the_lag_asymmetry(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir()
    # rows 386-395 are raised: Libre's lag-15 baseline reads row 385 (100), Dexcom's lag-5 baseline reads row 395 (120)
    make(root / "CGMacros-001" / "CGMacros-001.csv", libre={i: 120.0 for i in range(386, 396)}, dexcom={i: 120.0 for i in range(386, 396)},
         meals=(400,), dexcom_base=100.0)
    capsys.readouterr()
    assert ccc.main(["--data-root", str(root), "--report-out", str(tmp_path / "a.json")]) == 0
    default = json.loads(capsys.readouterr().out)["comparison_core_eligible_matched_PRIMARY"]
    assert default["baseline_difference_libre_minus_dexcom_mg_dl"]["mean"] == pytest.approx(-20.0)   # Libre lag 15 -> 100, Dexcom lag 5 -> 120
    assert ccc.main(["--data-root", str(root), "--baseline-lag-minutes", "5", "--report-out", str(tmp_path / "b.json")]) == 0
    same = json.loads(capsys.readouterr().out)["comparison_core_eligible_matched_PRIMARY"]
    assert same["baseline_difference_libre_minus_dexcom_mg_dl"]["mean"] == pytest.approx(0.0)


def test_no_dataset_is_an_error(tmp_path, capsys):
    (tmp_path / "e").mkdir()
    assert ccc.main(["--data-root", str(tmp_path / "e")]) == 2


# ------------------------------------------------------------------ eligibility is preserved, not re-decided

def test_valid_in_both_channels_but_core_eligible_in_only_one(tmp_path):
    p = tmp_path / "CGMacros-009.csv"
    make(p, meals=(10,))                                            # a meal 10 minutes into the file: Libre (lag 15) has no baseline, Dexcom (lag 5) does
    from glycotwin.data.meals import load_participant_data
    df = load_participant_data(p)
    tabs = {ch: {"P": build_event_table(df, "P", cgm_col=ch)} for ch in ("Libre GL", "Dexcom GL")}
    rep = ccc.build_report(tabs["Libre GL"], tabs["Dexcom GL"])
    assert rep["populations_matched"] == {"extraction_valid_both": 1, "core_eligible_both": 0, "activity_eligible_both": 0,
                                          "core_eligible_in_one_channel_only": 1}
    assert rep["comparison_core_eligible_matched_PRIMARY"]["n_matched_events"] == 0
    assert rep["comparison_extraction_valid_matched"]["n_matched_events"] == 1
    assert rep["comparison_extraction_valid_matched"]["baseline_missing"] == {"libre": 1, "dexcom": 0, "either": 1}


# ------------------------------------------------------------------ pure comparison logic

def _m(rows):
    cols = {"participant_id": [], "label_exceeds_180_l": [], "label_exceeds_180_d": [], "peak_glucose_l": [], "peak_glucose_d": [],
            "baseline_glucose_l": [], "baseline_glucose_d": [], "window_completeness_l": [], "window_completeness_d": []}
    for pid, ml, md, bl, bd, *rest in rows:
        cols["participant_id"].append(pid)
        cols["label_exceeds_180_l"].append(int(ml >= 180)); cols["label_exceeds_180_d"].append(int(md >= 180))
        cols["peak_glucose_l"].append(ml); cols["peak_glucose_d"].append(md)
        cols["baseline_glucose_l"].append(bl); cols["baseline_glucose_d"].append(bd)
        cols["window_completeness_l"].append(rest[0] if rest else 1.0); cols["window_completeness_d"].append(rest[1] if rest else 1.0)
    return pd.DataFrame(cols)


def test_delta_boundary_is_inclusive_and_threshold_is_inclusive():
    m = _m([("a", 185.0, 175.0, 100, 100), ("b", 180.0, 179.99, 100, 100), ("c", 195.0, 184.0, 100, 100), ("d", 190.0, 170.0, 100, 100)])
    r = ccc.compare_matched(m, delta=10.0)
    # a: 185 vs 175 disagree, exactly 10 apart (inclusive); b: 180.0 vs 179.99 disagree (threshold is >=); c: 195 vs 184 agree; d: 190 vs 170 disagree, 20 apart
    assert r["labels"]["n_disagree"] == 3
    t = r["threshold_proximity"]
    assert t["disagreements_with_abs_max_difference_within_delta"] == 2
    assert t["disagreements_with_abs_max_difference_beyond_delta"] == 1
    assert ccc.compare_matched(m, delta=9.99)["threshold_proximity"]["disagreements_with_abs_max_difference_within_delta"] == 1


def test_kappa_perfect_none_and_chance_levels():
    perfect = ccc.compare_matched(_m([("a", 200.0, 200.0, 1, 1), ("b", 100.0, 100.0, 1, 1)]))
    assert perfect["labels"]["cohen_kappa"] == pytest.approx(1.0) and perfect["labels"]["n_disagree"] == 0
    inverse = ccc.compare_matched(_m([("a", 200.0, 100.0, 1, 1), ("b", 100.0, 200.0, 1, 1)]))
    assert inverse["labels"]["cohen_kappa"] == pytest.approx(-1.0) and inverse["labels"]["share_disagree"] == 1.0
    assert ccc.compare_matched(_m([("a", 100.0, 100.0, 1, 1)]))["labels"]["cohen_kappa"] is None   # all one class: kappa undefined


def test_empty_input_and_missing_baselines_are_handled():
    assert ccc.compare_matched(_m([]))["n_matched_events"] == 0
    r = ccc.compare_matched(_m([("a", 200.0, 100.0, np.nan, 100.0), ("b", 150.0, 150.0, 90.0, 95.0)]))
    assert r["baseline_missing"] == {"libre": 1, "dexcom": 0, "either": 1} and r["baseline_difference_libre_minus_dexcom_mg_dl"]["n"] == 1


def test_disagreements_with_incomplete_windows_and_concentration_are_counted():
    r = ccc.compare_matched(_m([("a", 200.0, 100.0, 1, 1, 0.9, 1.0), ("a", 200.0, 100.0, 1, 1), ("b", 100.0, 100.0, 1, 1, 1.0, 0.8), ("c", 100.0, 100.0, 1, 1)]))
    assert r["window_completeness"]["events_either_channel_below_1"] == 2
    assert r["window_completeness"]["disagreements_where_either_channel_below_1"] == 1
    c = r["disagreement_concentration"]
    assert c["participants_with_at_least_one"] == 1 and c["max_share_from_a_single_participant"] == 1.0


def test_matching_requires_identical_anchor_timestamps():
    base = {c: [1] for c in ccc.KEEP}
    a = pd.DataFrame({**base, "participant_id": ["p"], "event_id": ["p-m000"], "meal_time": [pd.Timestamp("2000-01-01 10:00")]})
    b = a.copy(); b["meal_time"] = pd.Timestamp("2000-01-01 10:05")
    m, integrity = ccc.match_channels(a, b)
    assert len(m) == 0 and integrity == {"anchor_timestamp_mismatches_dropped": 1}
    m, integrity = ccc.match_channels(a, a.copy())
    assert len(m) == 1 and integrity == {"anchor_timestamp_mismatches_dropped": 0}


def test_disagreement_directions_are_not_interchangeable():
    r = ccc.compare_matched(_m([("a", 200.0, 100.0, 1, 1), ("b", 190.0, 120.0, 1, 1), ("c", 100.0, 200.0, 1, 1)]))
    assert r["labels"]["libre_positive_dexcom_negative"] == 2 and r["labels"]["libre_negative_dexcom_positive"] == 1
    assert r["confusion_libre_rows_dexcom_columns"]["libre_pos_dexcom_neg"] == 2
    assert r["confusion_libre_rows_dexcom_columns"]["libre_neg_dexcom_pos"] == 1
    assert r["disagreement_direction_of_max_difference"] == {"libre_higher_max_in_disagreements": 2,
                                                             "dexcom_higher_max_in_disagreements": 1, "equal_max_in_disagreements": 0}


def test_distance_bands_use_the_channel_nearer_to_the_threshold():
    # (Libre, Dexcom) maxima: (200, 179) -> nearer channel is 1 mg/dL from 180; (240, 170) -> 10; (300, 150) -> 30
    r = ccc.compare_matched(_m([("a", 200.0, 179.0, 1, 1), ("b", 240.0, 170.0, 1, 1), ("c", 300.0, 150.0, 1, 1)]), delta=10.0)
    bands = r["threshold_proximity"]["disagreements_by_distance_of_nearer_channel_max_to_threshold"]
    assert bands == {"<5_mg_dl": 1, "<10_mg_dl": 1, "<20_mg_dl": 2, ">=20_mg_dl": 1}
    assert r["threshold_proximity"]["events_with_either_max_within_delta_of_threshold"] == 2      # a (1) and b (10, inclusive)


def test_window_valid_in_neither_channel_is_counted(tmp_path):
    p = tmp_path / "CGMacros-008.csv"
    hole = {r: np.nan for r in range(430, 456)}
    make(p, libre=hole, dexcom=hole, meals=(400,))
    from glycotwin.data.meals import load_participant_data
    df = load_participant_data(p)
    tabs = {ch: {"P": build_event_table(df, "P", cgm_col=ch)} for ch in ("Libre GL", "Dexcom GL")}
    w = ccc.build_report(tabs["Libre GL"], tabs["Dexcom GL"])["window_availability_over_all_meal_rows"]
    assert (w["valid_in_both"], w["valid_in_libre_only"], w["valid_in_dexcom_only"], w["valid_in_neither"]) == (0, 0, 0, 1)
    assert w["share_either_channel_missing_or_incomplete"] == 1.0
