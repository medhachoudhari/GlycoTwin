"""Regression tests for the audit fixes (replay validation and atomicity, legacy summary, softened wording, what-if extrapolation)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.twin import demo as demo_mod
from glycotwin.twin import insight
from glycotwin.twin import replay as replay_mod
from glycotwin.twin.replay import replay_lifecycle, validate_replay_events
from glycotwin.twin.state import TwinStore

ROOT = Path(__file__).resolve().parents[1]
PID = demo_mod.DEMO_PARTICIPANT_ID


def fresh(n=6):
    return demo_mod.build_demo_store(0), demo_mod.demo_events(0, n)


def untouched(store):
    tw = store.current_twin(PID)
    return tw.version == 0 and len(store.twin_history(PID)) == 1 and len(store._forecasts) == 0 and len(store._observations) == 0


# ------------------------------------------------------------------ F1: validation before anything happens

@pytest.mark.parametrize("col", ["carbs_g", "baseline_glucose", "activity_level", "peak_glucose_rise"])
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_values_are_refused_before_the_store_is_touched(col, bad):
    store, ev = fresh()
    ev.loc[ev.index[3], col] = bad
    with pytest.raises(ValueError, match=col):
        replay_lifecycle(store, PID, ev)
    assert untouched(store)


def test_other_bad_inputs_are_refused_before_the_store_is_touched():
    store, ev = fresh()
    cases = {
        "meal_time": ev.assign(meal_time=[pd.NaT] + list(ev["meal_time"].iloc[1:])),
        "negative carbs": ev.assign(carbs_g=[-5.0] + list(ev["carbs_g"].iloc[1:])),
        "label not 0/1": ev.assign(label_exceeds_180=[2] + list(ev["label_exceeds_180"].iloc[1:])),
        "label missing": ev.assign(label_exceeds_180=[np.nan] + list(ev["label_exceeds_180"].iloc[1:])),
        "label inconsistent": ev.assign(label_exceeds_180=1 - ev["label_exceeds_180"]),
        "empty": ev.iloc[0:0],
    }
    for name, bad in cases.items():
        with pytest.raises(ValueError):
            replay_lifecycle(store, PID, bad)
        assert untouched(store), name
    with pytest.raises(KeyError):
        replay_lifecycle(store, "nobody", ev)


def test_validation_returns_a_sorted_numeric_copy_and_does_not_modify_the_input():
    _, ev = fresh()
    shuffled = ev.sample(frac=1.0, random_state=2).assign(carbs_g=lambda d: d["carbs_g"].astype(str))
    snapshot = shuffled.copy()
    out = validate_replay_events(shuffled)
    pd.testing.assert_frame_equal(shuffled, snapshot)
    assert out["meal_time"].is_monotonic_increasing and out["carbs_g"].dtype.kind == "f" and set(out["label_exceeds_180"]) <= {0, 1}
    np.testing.assert_allclose(out["carbs_g"].to_numpy(), ev.sort_values("meal_time")["carbs_g"].to_numpy())


# ------------------------------------------------------------------ F1: atomic rollback if anything still fails midway

def test_a_failure_midway_restores_the_store_exactly(monkeypatch):
    store, ev = fresh()
    real, calls = replay_mod.reconcile_forecast, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated failure")
        return real(*a, **k)
    monkeypatch.setattr(replay_mod, "reconcile_forecast", flaky)
    with pytest.raises(RuntimeError):
        replay_lifecycle(store, PID, ev)
    assert untouched(store) and store.pending_forecasts(PID) == []


def test_rollback_keeps_earlier_work_that_was_done_before_the_call(monkeypatch):
    store, ev = fresh(6)
    replay_lifecycle(store, PID, ev.head(2))
    version, n_forecasts = store.current_twin(PID).version, len(store._forecasts)
    later = ev.iloc[2:].copy()
    real, calls = replay_mod.reconcile_forecast, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(replay_mod, "reconcile_forecast", flaky)
    with pytest.raises(RuntimeError):
        replay_lifecycle(store, PID, later)
    assert store.current_twin(PID).version == version and len(store._forecasts) == n_forecasts and len(store.twin_history(PID)) == version + 1


def test_a_non_finite_forecast_stops_and_rolls_back(monkeypatch):
    store, ev = fresh()
    real = replay_mod.forecast_meal

    def nan_forecast(st, pid, row):
        rec = real(st, pid, row)
        rec.model_c_forecast.probability_exceeds_180 = float("nan")
        return rec
    monkeypatch.setattr(replay_mod, "forecast_meal", nan_forecast)
    with pytest.raises(ValueError, match="not finite"):
        replay_lifecycle(store, PID, ev)
    assert untouched(store)


def test_non_atomic_mode_is_available_but_still_validates_up_front(monkeypatch):
    store, ev = fresh()
    bad = ev.copy(); bad.loc[bad.index[2], "activity_level"] = np.nan
    with pytest.raises(ValueError):
        replay_lifecycle(store, PID, bad, atomic=False)
    assert untouched(store)                                                                              # validation, not rollback, protected it
    real, calls = replay_mod.reconcile_forecast, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("x")
        return real(*a, **k)
    monkeypatch.setattr(replay_mod, "reconcile_forecast", flaky)
    with pytest.raises(RuntimeError):
        replay_lifecycle(store, PID, ev, atomic=False)
    assert not untouched(store)                                                                          # documents what atomic=False means


def test_replay_log_carries_data_quality_columns_when_present():
    store, ev = fresh(3)
    ev = ev.assign(data_quality_flag="ok", activity_coverage=0.9, window_completeness=1.0)
    fc = [s for s in replay_lifecycle(store, PID, ev) if s["action"].startswith("forecast")]
    assert all(s["data_quality"] == {"data_quality_flag": "ok", "activity_coverage": 0.9, "window_completeness": 1.0} for s in fc)
    assert all(s["data_quality"] == {} for s in [s for s in replay_lifecycle(demo_mod.build_demo_store(0), PID, demo_mod.demo_events(0, 2)) if s["action"].startswith("forecast")])


# ------------------------------------------------------------------ F2: the legacy summary is documented and unchanged in value

def test_legacy_carb_sensitivity_summary_keeps_its_values_and_now_carries_an_interpretation_warning():
    store, _ = fresh()
    tw = store.current_twin(PID)
    s = tw.carb_sensitivity_summary()
    assert s["model_c_carb_sensitivity"]["mean"] == pytest.approx(tw.model_c.mean[0]) and s["model_b_carb_sensitivity"]["mean"] == pytest.approx(tw.model_b.mean[0])
    assert s["model_c_activity_interaction"]["mean"] == pytest.approx(tw.model_c.mean[1]) and s["model_c_reference_activity"] == 0.0 and s["version"] == 0
    assert "LEGACY" in s["interpretation"] and "activity = 0" in s["interpretation"] and "not comparable" in s["interpretation"] and "twin_insight" in s["interpretation"]
    like_for_like = insight.effective_sensitivity(tw.model_c, 0.5)["mean"]
    assert abs(s["model_c_carb_sensitivity"]["mean"] - like_for_like) > 1e-3                              # the legacy number is not the sensitivity at a typical activity
    assert "LEGACY" in type(tw).carb_sensitivity_summary.__doc__ and "twin_insight" in type(tw).carb_sensitivity_summary.__doc__


def test_legacy_summary_for_a_centred_state_names_the_prior_centre():
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from synthetic import make_hierarchical_meals
    from glycotwin.models.bayesian import MODEL_B_FEATURES, MODEL_C_FEATURES, fit_population_prior
    df = make_hierarchical_meals(12, 20, seed=7)
    s = TwinStore()
    s.initialize_twin("p000", fit_population_prior(df, MODEL_B_FEATURES, exclude_participants=("p000",)),
                      fit_population_prior(df, MODEL_C_FEATURES, exclude_participants=("p000",)))
    summ = s.current_twin("p000").carb_sensitivity_summary()
    assert 0 < summ["model_c_reference_activity"] < 1 and "prior's centre" in summ["interpretation"]


# ------------------------------------------------------------------ F3: wording

def test_overconfident_identifiability_wording_is_gone_from_code_and_docs():
    bad = "weakly identified in the real-data evaluation"
    for f in ("src/glycotwin/twin/insight.py", "docs/model_b_vs_c_report.md", "docs/INNOVATION_ROADMAP.md", "docs/model_c.md"):
        assert bad not in (ROOT / f).read_text(encoding="utf-8"), f
    assert any("may be weakly identified" in g for g in insight.GUARDRAILS)
    assert "inconclusive-to-negative" not in (ROOT / "docs" / "model_b_vs_c_report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ F4: what-if extrapolation checks

def test_what_if_flags_scenarios_outside_the_supplied_ranges_and_says_when_no_check_was_made():
    store, ev = fresh()
    tw = store.current_twin(PID)
    ranges = {"carbs_g": (20.0, 110.0), "activity_level": (0.0, 1.0)}
    res = insight.what_if(tw, [{"label": "ok", "carbs_g": 60.0, "activity_level": 0.5},
                               {"label": "absurd", "carbs_g": 5000.0, "activity_level": 50.0}], baseline_glucose=100.0, reference_ranges=ranges)
    ok, absurd = res["scenarios"]
    assert ok["extrapolation_warnings"] == [] and ok["extrapolation_check"].startswith("performed")
    assert len(absurd["extrapolation_warnings"]) == 2 and "extrapolates" in absurd["extrapolation_warnings"][0]
    nocheck = insight.what_if(tw, [{"carbs_g": 5000.0, "activity_level": 50.0}], baseline_glucose=100.0)["scenarios"][0]
    assert nocheck["extrapolation_check"].startswith("NOT performed") and nocheck["extrapolation_warnings"] == []
    lo = insight.what_if(tw, [{"carbs_g": 10.0, "activity_level": 0.5}], baseline_glucose=100.0, reference_ranges=ranges)["scenarios"][0]
    assert len(lo["extrapolation_warnings"]) == 1                                                        # below the carbohydrate range
    assert untouched_after_what_if(store)


def untouched_after_what_if(store):
    return len(store._forecasts) == 0 and store.current_twin(PID).version == 0


# ------------------------------------------------------------------ additive TwinState fields keep every old behaviour

def test_profile_and_parent_version_are_additive_carried_forward_and_default_empty():
    store = demo_mod.build_demo_store(0)
    assert store.current_twin(PID).profile == {} and store.current_twin(PID).parent_version is None
    s2 = TwinStore()
    tw0 = store.current_twin(PID)
    s2.initialize_twin("X", tw0.model_b, tw0.model_c, profile={"glycaemic_group": "pre-diabetes"})
    replay_lifecycle(s2, "X", demo_mod.demo_events(0, 3))
    hist = s2.twin_history("X")
    assert [t.parent_version for t in hist] == [None, 0, 1, 2] and all(t.profile == {"glycaemic_group": "pre-diabetes"} for t in hist)
    assert hist[0].profile is not hist[1].profile                                                         # copies, not shared mutable state
    s3 = TwinStore(); s3.initialize_twin("Y", tw0.model_b, tw0.model_c)                                   # the old two-argument call still works
    assert s3.current_twin("Y").profile == {}
