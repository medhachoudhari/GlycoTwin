"""Tests for scripts/audit_cgm_sampling_phase.py using CONTROLLED SYNTHETIC SERIES.

Everything here is software-test data with a KNOWN generating process (native readings every P
minutes at a known offset, linear interpolation or forward-fill, optional rounding, optional
gaps). It is not clinical data and carries no information about CGMacros.

WHAT THESE TESTS CAN SHOW: given a series that really was generated that way, the estimator
recovers the known period/offset, flags known gaps, and stays quiet on controls that lack the
structure.

WHAT THEY CANNOT SHOW: that the released CGMacros files were generated that way. Real data can
differ: manufacturer smoothing, timestamp jitter or sub-minute native times, clock drift,
resampling or alignment applied by the dataset authors, much smoother glucose (small slope
changes, hence low power), and rounding. The synthetic random walks below have large slope
changes, which makes detection EASIER than for real glucose. test_smooth_rounded_signal_is_
never_confidently_wrong is the one test that probes the hard direction, and it checks only that
the tool does not report a wrong phase with confidence. Only a run on real files can say
whether the fingerprint is present.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_cgm_sampling_phase.py"
_spec = importlib.util.spec_from_file_location("audit_cgm_sampling_phase", _SCRIPT)
aci = importlib.util.module_from_spec(_spec)
sys.modules["audit_cgm_sampling_phase"] = aci
_spec.loader.exec_module(aci)

CONSISTENT = "consistent_with_linear_interpolation_on_fixed_grid"
N_MIN = 4320  # 3 days of one-minute rows


# ----------------------------------------------------------------------------- generators

def native_readings(period, offset, n_minutes=N_MIN, seed=0, step_sd=8.0, start=120.0, jitter=False):
    rng = np.random.default_rng(seed)
    if jitter:
        gaps = rng.choice([period - 1, period, period + 1], size=n_minutes // (period - 1) + 2)
        times = offset + np.cumsum(np.r_[0, gaps])
        times = times[times < n_minutes]
    else:
        times = np.arange(offset, n_minutes, period)
    vals = start + np.cumsum(rng.normal(0.0, step_sd, len(times)))
    return times, vals


def linear_grid(times, vals, n_minutes=N_MIN, round_to=None):
    m = np.arange(n_minutes)
    v = np.interp(m, times, vals)
    v[(m < times[0]) | (m > times[-1])] = np.nan
    return np.round(v / round_to) * round_to if round_to else v


def hold_grid(times, vals, n_minutes=N_MIN):
    m = np.arange(n_minutes)
    v = vals[np.clip(np.searchsorted(times, m, side="right") - 1, 0, None)].astype(float)
    v[m < times[0]] = np.nan
    return v


def analyze(v, period, seed=0, n_perm=200, scan_perms=30):
    return aci.analyze_channel(v, period, n_perm, scan_perms, np.random.default_rng(seed))


# ----------------------------------------------------------------------------- recovery

@pytest.mark.parametrize("offset", [0, 1, 2, 3, 4])
def test_exact_linear_interpolation_recovers_every_offset_dexcom_like(offset):
    t, x = native_readings(5, offset)
    r = analyze(linear_grid(t, x), 5)
    assert r["dominant_residue_offset_from_file_start"] == offset
    assert r["documented_period_test"]["concentration"] > 0.95
    assert r["documented_period_test"]["p_value"] <= 0.01
    assert r["knots"]["share_on_dominant_residue_exact"] > 0.99
    assert r["knots"]["spacing"]["share_equal_to_period"] > 0.99
    assert r["verdict"] == CONSISTENT


def test_exact_linear_interpolation_libre_like_period_15():
    t, x = native_readings(15, 7, seed=3)
    r = analyze(linear_grid(t, x), 15)
    assert r["dominant_residue_offset_from_file_start"] == 7
    assert r["verdict"] == CONSISTENT
    assert r["exploratory_period_scan"]["estimated_fundamental_period"] == 15


def test_period_scan_finds_the_fundamental_not_a_divisor_or_multiple():
    for true_p in (5, 10, 15):
        t, x = native_readings(true_p, 1, seed=true_p)
        r = analyze(linear_grid(t, x), true_p)
        assert r["exploratory_period_scan"]["estimated_fundamental_period"] == true_p


def test_wrong_documented_period_is_not_supported():
    t, x = native_readings(5, 2)
    r = analyze(linear_grid(t, x), 7)   # documented period 7 is false for this series
    assert r["verdict"] != CONSISTENT
    assert r["exploratory_period_scan"]["estimated_fundamental_period"] == 5


def test_integer_rounding_still_recovers_phase_when_slope_changes_are_large():
    t, x = native_readings(5, 3, seed=5, step_sd=10.0)
    v = linear_grid(t, x, round_to=1.0)
    assert aci.estimate_resolution(v) == 1.0
    r = analyze(v, 5)
    assert r["dominant_residue_offset_from_file_start"] == 3
    assert r["verdict"] == CONSISTENT


# ----------------------------------------------------------------------------- controls / honesty

def test_no_interpolation_control_is_not_supported():
    rng = np.random.default_rng(11)
    v = 120 + np.cumsum(rng.normal(0, 1.5, N_MIN))     # independent 1-minute noise, no native grid
    r = analyze(v, 5)
    assert r["documented_period_test"]["concentration"] < 0.35
    assert r["verdict"] == "not_supported"


def test_forward_fill_is_flagged_as_step_hold_not_linear():
    t, x = native_readings(5, 1, seed=2)
    r = analyze(hold_grid(t, x), 5)
    assert r["first_difference_test"]["concentration"] > 0.9
    assert r["verdict"] == "periodic_but_step_hold_like_not_linear"


def test_smooth_rounded_signal_is_never_confidently_wrong():
    """Real glucose is smoother than a random walk: slope changes at native readings can be
    smaller than the rounding step, so knots are invisible. The tool must then say 'low power'
    (or at least not report a WRONG phase as consistent)."""
    m = np.arange(N_MIN)
    smooth = 130 + 30 * np.sin(2 * np.pi * m / 190) + 12 * np.sin(2 * np.pi * m / 71)
    t = np.arange(2, N_MIN, 5)
    rng = np.random.default_rng(4)
    x = np.interp(t, m, smooth) + rng.normal(0, 0.3, len(t))
    r = analyze(linear_grid(t, x, round_to=1.0), 5)
    if r["verdict"] == CONSISTENT:
        assert r["dominant_residue_offset_from_file_start"] == 2
    else:
        assert r["verdict"] in {"inconclusive_low_power", "not_supported"}
    easy_t, easy_x = native_readings(5, 2, seed=4, step_sd=10.0)
    easy = analyze(linear_grid(easy_t, easy_x, round_to=1.0), 5)
    assert r["knots"]["detected_per_expected_native_interval"] < easy["knots"]["detected_per_expected_native_interval"]


def test_timestamp_jitter_degrades_concentration_and_is_not_called_consistent():
    exact = analyze(linear_grid(*native_readings(5, 2, seed=8)), 5)
    jit = analyze(linear_grid(*native_readings(5, 2, seed=8, jitter=True)), 5)
    assert jit["documented_period_test"]["concentration"] < exact["documented_period_test"]["concentration"] - 0.2
    assert jit["verdict"] != CONSISTENT


def test_phase_shift_midway_is_detected_and_not_called_consistent():
    n = 6 * 1440
    t1 = np.arange(2, 3 * 1440, 5)
    t2 = np.arange(3 * 1440 + 4, n, 5)     # offset changes from 2 to 4
    t = np.r_[t1, t2]
    x = 120 + np.cumsum(np.random.default_rng(9).normal(0, 8, len(t)))
    r = analyze(linear_grid(t, x, n_minutes=n), 5)
    s = r["phase_stability"]
    assert s["agreement_exact"] < aci.MIN_PHASE_AGREEMENT
    assert s["phase_shift_events"] >= 1
    assert r["verdict"] != CONSISTENT


# ----------------------------------------------------------------------------- gaps

def test_nan_gaps_are_counted_and_do_not_move_the_phase():
    t, x = native_readings(5, 2)
    v = linear_grid(t, x)
    v[1000:1012] = np.nan
    v[2000:2040] = np.nan
    r = analyze(v, 5)
    g = r["nan_gaps"]
    assert g["n_missing_gaps"] == 2         # leading NaNs (before the first native reading) lie outside the span
    assert g["longest_gap_minutes"] == 40
    assert g["gap_length_buckets_minutes"][">30"] == 1
    assert g["gap_length_buckets_minutes"]["6-30"] == 1
    assert r["dominant_residue_offset_from_file_start"] == 2
    assert r["verdict"] == CONSISTENT


def test_interpolation_filled_outage_appears_as_a_long_sloped_straight_run():
    t, x = native_readings(5, 2, seed=6)
    keep = (t < 1500) | (t > 1530)          # native outage of ~30 minutes, released file filled linearly
    filled = analyze(linear_grid(t[keep], x[keep]), 5)
    clean = analyze(linear_grid(t, x), 5)
    assert filled["straight_runs"]["n_long_sloped_runs"] >= 1
    assert filled["straight_runs"]["longest_sloped_run_points"] >= 30
    assert clean["straight_runs"]["n_long_sloped_runs"] == 0


def test_filled_outage_is_still_detected_when_values_are_rounded_to_integers():
    """Rounding makes a straight line wobble (second difference up to +-2). The zero tolerance
    must absorb that, otherwise filled gaps in integer-valued data would go unnoticed."""
    t, x = native_readings(5, 2, seed=6)
    keep = (t < 1500) | (t > 1530)
    r = analyze(linear_grid(t[keep], x[keep], round_to=1.0), 5)
    assert r["value_resolution"] == 1.0 and r["zero_tolerance"] == 2.0
    assert r["straight_runs"]["n_long_sloped_runs"] >= 1
    assert r["straight_runs"]["longest_sloped_run_points"] >= 30


def test_zero_d2_share_meets_the_exact_linear_expectation_under_rounding():
    t, x = native_readings(5, 2, seed=6)
    r = analyze(linear_grid(t, x, round_to=1.0), 5)
    assert r["zero_d2_share"] >= r["zero_d2_share_expected_if_exact_linear_at_least"]


def test_flat_plateau_is_counted_as_flat_not_as_a_filled_gap():
    t, x = native_readings(5, 2, seed=6)
    x = x.copy()
    x[(t >= 1000) & (t <= 1100)] = x[(t >= 1000)][0]       # constant for ~100 minutes
    r = analyze(linear_grid(t, x), 5)
    assert r["straight_runs"]["n_long_flat_runs"] >= 1
    assert r["straight_runs"]["longest_flat_run_points"] >= 90


def test_second_differences_hand_computed_and_nan_propagation():
    d2 = aci.second_differences(np.array([1.0, 2.0, 4.0, 7.0, np.nan, 3.0, 1.0]))
    assert d2[1] == 1.0 and d2[2] == 1.0
    assert np.isnan(d2[0]) and np.isnan(d2[3]) and np.isnan(d2[4]) and np.isnan(d2[5]) and np.isnan(d2[6])


def test_too_little_data_is_reported_as_insufficient_not_guessed():
    t, x = native_readings(5, 2, n_minutes=60)
    r = analyze(linear_grid(t, x, n_minutes=60), 5)
    assert r["verdict"] == "insufficient_data"


# ----------------------------------------------------------------------------- grid QC / helpers

def _frame(minutes, values):
    ts = pd.Timestamp("2000-01-01") + pd.to_timedelta(minutes, unit="s")
    return pd.Series(ts), pd.Series(values)


def test_grid_qc_flags_non_minute_timestamps():
    ts, val = _frame(np.arange(0, 600, 30), np.arange(20.0))      # every 30 seconds
    v, qc = aci.to_minute_series(ts, val)
    assert v is None and qc["reason"] == "not_one_minute_aligned"


def test_grid_qc_handles_duplicates_disorder_and_bad_timestamps():
    ts = pd.Series(["2000-01-01 00:00", "2000-01-01 00:02", "2000-01-01 00:01", "2000-01-01 00:01", "garbage"])
    v, qc = aci.to_minute_series(ts, pd.Series([1.0, 3.0, 2.0, 99.0, 5.0]))
    assert qc["usable"] and qc["timestamp_unparseable_rows"] == 1
    assert qc["duplicate_minute_rows"] == 1 and qc["rows_out_of_order"] >= 1
    assert list(v) == [1.0, 2.0, 3.0]                              # first duplicate kept, order fixed


def test_estimate_resolution():
    assert aci.estimate_resolution(np.array([100.0, 101.0, 130.0])) == 1.0
    assert aci.estimate_resolution(np.array([100.1, 101.3, 130.7])) == 0.1
    assert aci.estimate_resolution(np.array([100.123457, 101.31415926])) == 0.0
    assert aci.estimate_resolution(np.array([np.nan])) is None


def test_permutation_test_is_valid_on_shuffled_structure():
    t, x = native_readings(5, 2)
    absd2 = np.abs(aci.second_differences(linear_grid(t, x)))
    shuffled = absd2.copy()
    fin = np.flatnonzero(np.isfinite(shuffled))
    shuffled[fin] = np.random.default_rng(0).permutation(shuffled[fin])
    real = aci.concentration_test(absd2, 5, 200, np.random.default_rng(1))
    null = aci.concentration_test(shuffled, 5, 200, np.random.default_rng(1))
    assert real["p_value"] <= 0.01 and null["p_value"] > 0.01
    assert 0 < null["p_value"] <= 1 and null["null95"] >= 1 / 5


def test_permutation_count_is_raised_so_a_strong_signal_can_reach_alpha():
    """With only 5 shuffles the smallest possible p is 1/6; the script must enforce a minimum."""
    t, x = native_readings(5, 2)
    absd2 = np.abs(aci.second_differences(linear_grid(t, x)))
    assert aci.concentration_test(absd2, 5, 5, np.random.default_rng(0))["p_value"] <= aci.ALPHA


def test_analysis_is_deterministic_for_a_fixed_seed():
    t, x = native_readings(5, 2)
    v = linear_grid(t, x)
    assert json.dumps(aci._py(analyze(v, 5, seed=3)), sort_keys=True) == json.dumps(aci._py(analyze(v, 5, seed=3)), sort_keys=True)


# ----------------------------------------------------------------------------- decision rule

def _agg(share, detected):
    return {"x": {"participants_evaluated": 5, "share_consistent_among_evaluated": share,
                  "median_detected_per_expected_interval": detected}}


def test_decision_rule_is_provisional_on_a_pilot_and_falls_back_otherwise():
    ok = aci.decide(_agg(1.0, 0.9), n_participants=5, n_total_files=45)
    assert ok["rule_met"] and ok["scope"].startswith("pilot_only") and ok["recommendation"].startswith("PROVISIONAL")
    assert "native timestamps" in ok["never_claimed"]
    bad = aci.decide(_agg(0.6, 0.9), 5, 45)
    assert not bad["rule_met"] and bad["recommendation"].startswith("FALLBACK") and "lag guard" in bad["recommendation"]
    low = aci.decide(_agg(1.0, 0.1), 5, 45)
    assert not low["rule_met"]
    assert aci.decide(_agg(1.0, 0.9), 45, 45)["scope"] == "all selected files"


# ----------------------------------------------------------------------------- end to end

def _write_fake_dataset(root, n_files=7):
    """Synthetic multi-participant tree: exact-linear Dexcom (P=5) and Libre (P=15) channels."""
    digests = {}
    for i in range(n_files):
        d = root / f"CGMacros-0{i:02d}"
        d.mkdir()
        td, xd = native_readings(5, i % 5, seed=100 + i)
        tl, xl = native_readings(15, (i * 2) % 15, seed=200 + i)
        df = pd.DataFrame({
            "Timestamp": pd.date_range("2000-01-01 00:00", periods=N_MIN, freq="1min").strftime("%Y-%m-%d %H:%M:%S"),
            "Libre GL": linear_grid(tl, xl), "Dexcom GL": linear_grid(td, xd),
            "HR": 70.0, "Meal Type": np.nan, "Image path": np.nan})
        p = d / f"CGMacros-0{i:02d}.csv"
        df.to_csv(p, index=False)
        digests[p] = hashlib.sha256(p.read_bytes()).hexdigest()
    return digests


def test_cli_end_to_end_is_aggregate_only_deterministic_and_read_only(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    before = _write_fake_dataset(data)
    out = tmp_path / "report.json"
    argv = ["--data-root", str(data), "--n-participants", "3", "--seed", "1", "--n-perm", "100",
            "--scan-perms", "10", "--out", str(out)]
    assert aci.main(argv) == 0
    first = capsys.readouterr().out
    report = json.loads(first)

    assert set(report["per_participant_qc"]) == {"P1", "P2", "P3"}
    assert set(report["aggregate_by_channel"]) == {"Dexcom GL", "Libre GL"}
    for chan in ("Dexcom GL", "Libre GL"):
        assert report["aggregate_by_channel"][chan]["verdict_counts"] == {CONSISTENT: 3}
    assert report["decision"]["scope"].startswith("pilot_only")
    assert "never_claimed" in report["decision"] and "not_established" in report["epistemic_status"]

    for needle in ("CGMacros-0", "2000-01-01", str(data), "00:00"):       # no ids, paths or timestamps
        assert needle not in first, needle
    assert json.loads(out.read_text(encoding="utf-8")) == report

    assert aci.main(argv) == 0
    assert capsys.readouterr().out == first                                # same seed, same output
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before   # dataset untouched


def test_cli_selection_respects_n_participants_and_caps_at_available(tmp_path, capsys):
    data = tmp_path / "d"
    data.mkdir()
    _write_fake_dataset(data, n_files=2)
    assert aci.main(["--data-root", str(data), "--n-participants", "9", "--n-perm", "20", "--scan-perms", "5",
                     "--out", str(tmp_path / "o.json")]) == 0
    assert len(json.loads(capsys.readouterr().out)["per_participant_qc"]) == 2


def test_cli_errors_are_clear_and_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GLYCOTWIN_DATA_ROOT", raising=False)
    assert aci.main([]) == 2
    assert aci.main(["--data-root", str(tmp_path / "missing")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert aci.main(["--data-root", str(empty)]) == 2
    assert aci.main(["--data-root", str(empty), "--n-participants", "0"]) == 2
    err = capsys.readouterr().err
    assert "GLYCOTWIN_DATA_ROOT" in err and "no CSV with a 'Timestamp'" in err
