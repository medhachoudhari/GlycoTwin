"""Twin insight, parameter history, what-if, lifecycle replay and the synthetic demo. SYNTHETIC data only; no research claim."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.models.bayesian import BayesianLinearState, conjugate_update, forecast_exceeds_180
from glycotwin.twin import demo as demo_mod
from glycotwin.twin import insight
from glycotwin.twin.replay import replay_lifecycle
from glycotwin.twin.state import TwinStore, forecast_meal, reconcile_forecast

ROOT = Path(__file__).resolve().parents[1]
PID = demo_mod.DEMO_PARTICIPANT_ID
REF = 0.5


def fresh(seed=0, n_events=6):
    return demo_mod.build_demo_store(seed), demo_mod.demo_events(seed, n_events)


def mean_cov(state):
    return state.mean.copy(), state.covariance.copy()


# ------------------------------------------------------------------ effective sensitivity and insight

def test_effective_sensitivity_includes_the_beta_gamma_covariance():
    cov = np.array([[0.04, -0.01], [-0.01, 0.0225]])
    c = BayesianLinearState(["carbs_g", "carbs_x_activity"], np.array([1.0, -0.4]), cov, 100.0)
    s = insight.effective_sensitivity(c, 0.75)
    assert s["mean"] == pytest.approx(1.0 - 0.4 * 0.75)
    assert s["sd"] ** 2 == pytest.approx(0.04 + 0.75 ** 2 * 0.0225 + 2 * 0.75 * (-0.01))            # var(beta) + a^2 var(gamma) + 2a cov
    assert s["interval90"] == pytest.approx([s["mean"] - 1.6448536 * s["sd"], s["mean"] + 1.6448536 * s["sd"]], rel=1e-6)
    at0 = insight.effective_sensitivity(c, 0.0)
    assert at0["mean"] == 1.0 and at0["sd"] == pytest.approx(0.2)                                    # un-centred beta = sensitivity at activity 0
    with pytest.raises(ValueError, match="activity"):
        insight.effective_sensitivity(c)
    centred = BayesianLinearState(["intercept", "carbs_g", "carbs_x_activity"], np.array([5.0, 0.9, -0.3]), np.diag([50.0, 0.04, 0.01]), 100.0, activity_center=2.0)
    assert insight.effective_sensitivity(centred, 3.0)["mean"] == pytest.approx(0.9 - 0.3 * 1.0)      # legacy centred form is handled too
    b = BayesianLinearState(["carbs_g"], np.array([0.8]), np.array([[0.09]]), 100.0)
    sb = insight.effective_sensitivity(b)
    assert sb["mean"] == 0.8 and sb["sd"] == pytest.approx(0.3) and sb["activity"] is None
    assert insight.effective_sensitivity(b, 99.0)["mean"] == 0.8                                      # Model B never uses activity


def test_twin_insight_exposes_b_sensitivity_c_reference_sensitivity_interaction_uncertainty_and_version():
    store, events = fresh()
    twin = store.current_twin(PID)
    ins = insight.twin_insight(store, PID, REF)
    assert ins["twin_version"] == 0 and ins["participant_label"] == PID and ins["n_reconciled_observations"] == 0
    b, c = ins["model_b"]["carb_sensitivity"], ins["model_c"]
    assert b["mean"] == pytest.approx(twin.model_b.mean[0]) and b["sd"] == pytest.approx(np.sqrt(twin.model_b.covariance[0, 0]))
    assert c["beta_carb_sensitivity"]["mean"] == pytest.approx(twin.model_c.mean[0])
    assert c["gamma_activity_interaction"]["mean"] == pytest.approx(twin.model_c.mean[1]) and c["activity_center"] == 0.0
    s = c["sensitivity_at_reference_activity"]
    assert s["reference_activity"] == REF and s["mean"] == pytest.approx(twin.model_c.mean[0] + REF * twin.model_c.mean[1])
    w = np.array([1.0, REF])
    assert s["sd"] == pytest.approx(np.sqrt(w @ twin.model_c.covariance @ w))
    assert -1.0 <= c["beta_gamma_posterior_correlation"] <= 1.0
    assert ins["difference_c_minus_b_at_reference_activity"]["mean"] == pytest.approx(s["mean"] - b["mean"])
    assert ins["noise_sd_mg_dl"]["model_c"] == pytest.approx(np.sqrt(twin.model_c.noise_variance))
    assert isinstance(c["gamma_activity_interaction"]["interval90_excludes_zero"], bool) and ins["guardrails"] and "mg/dL" in ins["units"]["carb_sensitivity"]
    with pytest.raises(ValueError, match="reference_activity"):
        insight.twin_insight(store, PID)                                                             # un-centred beta must not be shown as "the" sensitivity
    with pytest.raises(KeyError):
        insight.twin_insight(store, "nobody")


def test_insight_reports_the_new_version_and_smaller_uncertainty_after_reconciliation_and_never_mutates_the_twin():
    store, events = fresh()
    before = insight.twin_insight(store, PID, REF)
    state_before = mean_cov(store.current_twin(PID).model_c)
    insight.twin_insight(store, PID, REF); insight.parameter_history(store, PID, REF)
    np.testing.assert_array_equal(state_before[0], store.current_twin(PID).model_c.mean)
    row = events.iloc[0]
    rec = forecast_meal(store, PID, row)
    reconcile_forecast(store, rec.forecast_id, float(row["peak_glucose_rise"]), bool(row["label_exceeds_180"]), observed_through=row["meal_time"] + pd.Timedelta(hours=2))
    after = insight.twin_insight(store, PID, REF)
    assert after["twin_version"] == before["twin_version"] + 1 and after["n_reconciled_observations"] == 1
    assert after["model_c"]["gamma_activity_interaction"]["sd"] < before["model_c"]["gamma_activity_interaction"]["sd"]
    assert after["model_b"]["carb_sensitivity"]["sd"] < before["model_b"]["carb_sensitivity"]["sd"]
    assert after["model_c"]["n_observations_used"] == 1 and before["model_c"]["n_observations_used"] == 0


def test_reconciliation_log_is_per_participant_and_in_version_order():
    store, events = fresh()
    pop_prior_b, pop_prior_c = store.current_twin(PID).model_b, store.current_twin(PID).model_c
    store.initialize_twin("DEMO-OTHER", pop_prior_b, pop_prior_c)
    replay_lifecycle(store, PID, events.head(3))
    replay_lifecycle(store, "DEMO-OTHER", events.head(2))
    mine, other = store.reconciliation_log(PID), store.reconciliation_log("DEMO-OTHER")
    assert [o.twin_version_after_update for o in mine] == [1, 2, 3] and [o.twin_version_after_update for o in other] == [1, 2]
    assert store.reconciliation_log("nobody") == []
    assert {o.forecast_id for o in mine}.isdisjoint({o.forecast_id for o in other})


# ------------------------------------------------------------------ parameter history

def test_parameter_history_has_one_row_per_version_links_each_to_its_observation_and_preserves_old_versions():
    store, events = fresh(n_events=5)
    v0 = store.current_twin(PID)
    v0_snapshot = (v0.model_b.mean.copy(), v0.model_c.mean.copy(), v0.model_c.covariance.copy(), v0.version)
    replay_lifecycle(store, PID, events)
    hist = insight.parameter_history(store, PID, REF)
    rows = hist["versions"]
    assert [r["version"] for r in rows] == list(range(6)) and hist["summary"]["n_versions"] == 6
    assert rows[0]["triggering_observation"] is None and "change_since_previous_version" not in rows[0]
    obs = store.reconciliation_log(PID)
    ordered = events.sort_values("meal_time").reset_index(drop=True)
    for i, r in enumerate(rows[1:], start=0):
        assert r["triggering_observation"]["forecast_id"] == obs[i].forecast_id
        assert r["triggering_observation"]["observed_peak_rise"] == pytest.approx(ordered.loc[i, "peak_glucose_rise"])
        assert r["triggering_observation"]["kind"].startswith("OBSERVED")
        assert r["n_observations_model_c"] == i + 1
    history = store.twin_history(PID)                                                                  # old versions are stored objects, untouched
    np.testing.assert_array_equal(history[0].model_b.mean, v0_snapshot[0]); np.testing.assert_array_equal(history[0].model_c.mean, v0_snapshot[1])
    np.testing.assert_array_equal(history[0].model_c.covariance, v0_snapshot[2]); assert history[0].version == 0 and len(history) == 6
    for prev, cur in zip(rows, rows[1:]):
        assert cur["change_since_previous_version"]["c_gamma_mean"] == pytest.approx(cur["c_gamma_mean"] - prev["c_gamma_mean"])
        assert cur["sd_ratio_to_previous_version"]["c_gamma_sd"] == pytest.approx(cur["c_gamma_sd"] / prev["c_gamma_sd"])
        assert cur["c_gamma_sd"] <= prev["c_gamma_sd"] + 1e-12 and cur["b_sensitivity_sd"] <= prev["b_sensitivity_sd"] + 1e-12   # uncertainty only shrinks
    s = hist["summary"]
    assert s["prior_to_current_change"]["c_gamma_mean"] == pytest.approx(rows[-1]["c_gamma_mean"] - rows[0]["c_gamma_mean"])
    assert s["current_over_prior_sd"]["c_gamma_sd"] == pytest.approx(rows[-1]["c_gamma_sd"] / rows[0]["c_gamma_sd"])
    assert s["current_over_prior_sd"]["c_gamma_sd"] < 1.0


def test_history_values_equal_the_stored_posterior_at_each_version():
    store, events = fresh(n_events=4)
    replay_lifecycle(store, PID, events)
    rows = insight.parameter_history(store, PID, REF)["versions"]
    for tw, r in zip(store.twin_history(PID), rows):
        assert r["c_beta_mean"] == pytest.approx(tw.model_c.mean[0]) and r["c_gamma_mean"] == pytest.approx(tw.model_c.mean[1])
        assert r["c_gamma_sd"] == pytest.approx(np.sqrt(tw.model_c.covariance[1, 1])) and r["b_sensitivity_mean"] == pytest.approx(tw.model_b.mean[0])
        assert r["c_sensitivity_at_reference_mean"] == pytest.approx(tw.model_c.mean[0] + REF * tw.model_c.mean[1])
    with pytest.raises(KeyError):
        insight.parameter_history(store, "nobody", REF)


# ------------------------------------------------------------------ what-if

SCEN = [{"label": "base", "carbs_g": 60.0, "activity_level": 0.1}, {"label": "more activity", "carbs_g": 60.0, "activity_level": 0.9},
        {"label": "more carbs", "carbs_g": 90.0, "activity_level": 0.1}]


def test_what_if_is_pure_hypothetical_and_cannot_be_reconciled_or_learned_from():
    store, events = fresh(n_events=3)
    replay_lifecycle(store, PID, events)
    twin = store.current_twin(PID)
    snap = (twin.version, len(store.twin_history(PID)), len(store._forecasts), len(store._observations), mean_cov(twin.model_b), mean_cov(twin.model_c))
    res = insight.what_if(twin, SCEN, baseline_glucose=110.0)
    after = store.current_twin(PID)
    assert (after.version, len(store.twin_history(PID)), len(store._forecasts), len(store._observations)) == snap[:4]
    np.testing.assert_array_equal(after.model_b.mean, snap[4][0]); np.testing.assert_array_equal(after.model_c.covariance, snap[5][1])
    assert store.pending_forecasts(PID) == []
    assert res["label"].startswith("WHAT-IF SIMULATION") and "nothing here was observed" in res["label"] and res["twin_version_used"] == twin.version
    assert all(s["kind"].startswith("HYPOTHETICAL") and s["twin_version_used"] == twin.version for s in res["scenarios"])
    with pytest.raises(KeyError):
        store.get_forecast("what-if")                                                                  # no forecast record exists to reconcile


def test_what_if_distribution_matches_the_posterior_predictive_and_propagates_uncertainty():
    store, events = fresh(n_events=3)
    replay_lifecycle(store, PID, events)
    twin = store.current_twin(PID)
    res = insight.what_if(twin, SCEN, baseline_glucose=110.0)
    for sc, out in zip(SCEN, res["scenarios"]):
        row = pd.Series({"carbs_g": sc["carbs_g"], "activity_level": sc["activity_level"]})
        for name, state in (("model_b", twin.model_b), ("model_c", twin.model_c)):
            f = forecast_exceeds_180(state, row, 110.0)
            d = out[name]["distribution"]
            assert d["mean_rise_mg_dl"] == pytest.approx(f.mean_rise) and d["sd_mg_dl"] == pytest.approx(f.predictive_std)
            assert out[name]["p_peak_at_least_180"] == pytest.approx(f.probability_exceeds_180) and d["family"] == "normal"
            assert d["interval90_mg_dl"][0] < d["mean_rise_mg_dl"] < d["interval90_mg_dl"][1]
        x = np.array([sc["carbs_g"], sc["carbs_g"] * sc["activity_level"]])
        assert out["model_c"]["distribution"]["sd_mg_dl"] ** 2 == pytest.approx(twin.model_c.noise_variance + x @ twin.model_c.covariance @ x)   # sigma^2 + x'Sigma x
        assert out["model_c"]["distribution"]["sd_mg_dl"] > np.sqrt(twin.model_c.noise_variance)
        assert out["model_c"]["distribution"]["mean_rise_mg_dl"] == pytest.approx((twin.model_c.mean[0] + twin.model_c.mean[1] * sc["activity_level"]) * sc["carbs_g"])
    base, act, carbs = res["scenarios"]
    assert "difference_from_first_scenario" not in base
    assert act["difference_from_first_scenario"]["model_c"]["mean_rise_mg_dl"] == pytest.approx(act["model_c"]["distribution"]["mean_rise_mg_dl"] - base["model_c"]["distribution"]["mean_rise_mg_dl"])
    assert carbs["model_b"]["distribution"]["mean_rise_mg_dl"] > base["model_b"]["distribution"]["mean_rise_mg_dl"]          # more carbohydrate, bigger predicted rise (beta > 0)
    assert res["scenarios"][0]["model_b"]["distribution"]["mean_rise_mg_dl"] == res["scenarios"][1]["model_b"]["distribution"]["mean_rise_mg_dl"]  # Model B ignores activity


def test_what_if_zero_carbohydrate_gives_zero_rise_and_bad_scenarios_are_rejected():
    store, _ = fresh()
    twin = store.current_twin(PID)
    zero = insight.what_if(twin, [{"label": "no carbs", "carbs_g": 0.0, "activity_level": 0.9}], baseline_glucose=100.0)["scenarios"][0]
    assert zero["model_c"]["distribution"]["mean_rise_mg_dl"] == 0.0 and zero["model_b"]["distribution"]["mean_rise_mg_dl"] == 0.0
    assert zero["model_c"]["distribution"]["sd_mg_dl"] == pytest.approx(np.sqrt(twin.model_c.noise_variance))
    for bad in ({"carbs_g": -1.0, "activity_level": 0.5}, {"carbs_g": float("nan"), "activity_level": 0.5}, {"carbs_g": 50.0},
                {"carbs_g": 50.0, "activity_level": float("inf")}, {"carbs_g": 50.0, "activity_level": 0.5, "baseline_glucose": float("nan")}):
        with pytest.raises(ValueError):
            insight.what_if(twin, [bad], baseline_glucose=100.0)
    with pytest.raises(ValueError, match="baseline_glucose"):
        insight.what_if(twin, [{"carbs_g": 50.0, "activity_level": 0.5}])                              # no baseline given anywhere
    with pytest.raises(ValueError, match="at least one"):
        insight.what_if(twin, [], baseline_glucose=100.0)


# ------------------------------------------------------------------ lifecycle replay: forecast before update, versions, leakage

def test_each_forecast_uses_the_posterior_before_its_own_observation_and_matches_an_independent_recomputation():
    store, events = fresh(n_events=6)
    log = replay_lifecycle(store, PID, events)
    ordered = events.sort_values("meal_time").reset_index(drop=True)
    fc = [s for s in log if s["action"].startswith("forecast")]
    state_b, state_c = demo_mod.build_demo_store(0).current_twin(PID).model_b, demo_mod.build_demo_store(0).current_twin(PID).model_c
    for i, step in enumerate(fc):
        assert step["twin_version_at_forecast"] == i                                                     # exactly i earlier outcomes incorporated
        row = ordered.iloc[i]
        fb = forecast_exceeds_180(state_b, row, float(row["baseline_glucose"])); fcm = forecast_exceeds_180(state_c, row, float(row["baseline_glucose"]))
        assert step["model_b"]["p_peak_at_least_180"] == pytest.approx(fb.probability_exceeds_180)
        assert step["model_c"]["p_peak_at_least_180"] == pytest.approx(fcm.probability_exceeds_180)
        assert step["model_c"]["sd_mg_dl"] == pytest.approx(fcm.predictive_std)                         # uncertainty carried into the logged forecast
        state_b = conjugate_update(state_b, ordered.iloc[[i]]); state_c = conjugate_update(state_c, ordered.iloc[[i]])
    actions = [s["action"].split()[0] for s in log]
    assert actions == ["forecast", "reconcile"] * 6                                                      # forecast, then its observation, then the next forecast
    rec = [s for s in log if s["action"].startswith("reconcile")]
    assert [(s["twin_version_before"], s["twin_version_after"]) for s in rec] == [(i, i + 1) for i in range(6)]
    assert store.current_twin(PID).version == 6 and len(store.twin_history(PID)) == 7 and store.pending_forecasts(PID) == []


def test_changing_an_events_own_or_later_outcome_never_changes_an_earlier_forecast():
    base_store, events = fresh(n_events=6)
    base = [s for s in replay_lifecycle(base_store, PID, events) if s["action"].startswith("forecast")]
    ordered = events.sort_values("meal_time").reset_index(drop=True)
    for k in (0, 2, 5):
        mod = ordered.copy()
        mod.loc[k:, "peak_glucose_rise"] = mod.loc[k:, "peak_glucose_rise"] + 300.0                        # event k's own outcome and every later one
        mod.loc[k:, "label_exceeds_180"] = 1
        mod.loc[k + 1:, ["carbs_g", "activity_level"]] = [5.0, 0.99]                                       # and the later inputs
        store = demo_mod.build_demo_store(0)
        got = [s for s in replay_lifecycle(store, PID, mod) if s["action"].startswith("forecast")]
        for i in range(k + 1):
            assert got[i]["model_b"]["p_peak_at_least_180"] == base[i]["model_b"]["p_peak_at_least_180"]
            assert got[i]["model_c"]["p_peak_at_least_180"] == base[i]["model_c"]["p_peak_at_least_180"]
        if k < 5:
            assert got[k + 1]["model_c"]["p_peak_at_least_180"] != base[k + 1]["model_c"]["p_peak_at_least_180"]


def test_an_event_inside_an_earlier_events_open_window_cannot_use_that_outcome_and_unsorted_input_is_ordered():
    store, events = fresh(n_events=3)
    ev = events.copy()
    t0 = ev["meal_time"].iloc[0]
    ev["meal_time"] = [t0, t0 + pd.Timedelta(minutes=90), t0 + pd.Timedelta(minutes=300)]
    log = replay_lifecycle(store, PID, ev.iloc[::-1])                                                    # latest event first, on purpose
    fc = [s for s in log if s["action"].startswith("forecast")]
    assert [s["meal_time"] for s in fc] == sorted(s["meal_time"] for s in fc) and [s["event_index"] for s in fc] == [0, 1, 2]   # replayed in time order
    assert [s["twin_version_at_forecast"] for s in fc] == [0, 0, 2]                                      # 90 min later: window still open; 300 min later: both closed
    assert [s["seq"] for s in log] == list(range(len(log))) and store.current_twin(PID).version == 3


def test_replay_rejects_missing_columns_and_double_use_is_guarded_by_the_existing_reconcile_rules():
    store, events = fresh(n_events=2)
    with pytest.raises(ValueError, match="missing columns"):
        replay_lifecycle(store, PID, events.drop(columns=["activity_level"]))
    bad = events.copy(); bad.loc[bad.index[0], "label_exceeds_180"] = 1 - int(bad["label_exceeds_180"].iloc[0])
    with pytest.raises(ValueError, match="disagrees"):
        replay_lifecycle(store, PID, bad)                                                                # refused up front, before the store is touched
    assert store.current_twin(PID).version == 0 and len(store._forecasts) == 0


# ------------------------------------------------------------------ demo

def _strip(o):
    s = json.dumps(o, default=str)
    import re
    s = re.sub(r'"(forecast_id|created_at|last_forecast_id)": "[^"]*"', r'"\1": "X"', s)
    return re.sub(r'"reconciliation_log_ref": \[[^\]]*\]|"forecasts_awaiting_reconciliation": \[[^\]]*\]', r'"ids": []', s)


def test_demo_is_reproducible_labelled_synthetic_blueprint_form_and_contains_no_real_identifiers():
    a, b, c = demo_mod.run_demo(seed=0), demo_mod.run_demo(seed=0), demo_mod.run_demo(seed=1)
    assert _strip(a) == _strip(b) and _strip(a) != _strip(c)
    text = json.dumps(a, default=str)
    assert a["banner"].startswith("SYNTHETIC DEMONSTRATION") and "NOT CGMacros data" in a["banner"] and a["events_are"] == "SIMULATED"
    assert "CGMacros-" not in text and a["participant_label"] == "DEMO-SYNTHETIC-001" and a["generating_truth_of_simulated_participant"] == demo_mod.DEMO_TRUTH
    store = demo_mod.build_demo_store(0)
    assert store.current_twin(PID).model_b.feature_names == ["carbs_g"] and store.current_twin(PID).model_c.feature_names == ["carbs_g", "carbs_x_activity"]
    assert store.current_twin(PID).model_c.activity_center == 0.0                                       # no intercept, un-centred
    assert a["twin_insight_after"]["twin_version"] == len(demo_mod.demo_events(0, 8)) and a["twin_insight_before"]["twin_version"] == 0
    assert a["what_if"]["label"].startswith("WHAT-IF SIMULATION")
    ev = demo_mod.demo_events(0, 8)
    assert (ev["meal_time"].diff().dropna() >= pd.Timedelta(hours=2)).all() and ev["activity_level"].between(0, 1).all()


def test_demo_script_prints_the_synthetic_banner_and_the_requested_sections(capsys):
    spec = importlib.util.spec_from_file_location("demo_twin_lifecycle", ROOT / "scripts" / "demo_twin_lifecycle.py")
    mod = importlib.util.module_from_spec(spec); sys.modules["demo_twin_lifecycle"] = mod; spec.loader.exec_module(mod)
    assert mod.main(["--events", "4"]) == 0
    out = capsys.readouterr().out
    assert out.count("SYNTHETIC DEMONSTRATION") == 2 and "Parameter evolution" in out and "What-if (HYPOTHETICAL" in out and "reconcile event" in out
    assert mod.main(["--events", "3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["events_are"] == "SIMULATED"


def test_new_modules_have_no_database_or_web_framework_dependency_and_leave_the_models_untouched():
    for f in ("insight.py", "replay.py", "demo.py"):
        src = (ROOT / "src" / "glycotwin" / "twin" / f).read_text(encoding="utf-8")
        assert not any(w in src for w in ("sqlalchemy", "sqlite", "fastapi", "flask", "pydantic", "uvicorn")), f
    for f in ("src/glycotwin/models/bayesian.py", "src/glycotwin/models/model_b_cv.py", "src/glycotwin/models/model_c_cv.py"):
        assert "twin.insight" not in (ROOT / f).read_text(encoding="utf-8"), f
