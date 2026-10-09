"""Blueprint decision branch "sensor gap -> excluded, no update", the step-wise replay session, side-by-side what-if, twin-history export,
Model A TreeSHAP contributions. SYNTHETIC data only."""
import numpy as np
import pandas as pd
import pytest

from glycotwin.twin import demo as demo_mod
from glycotwin.twin import insight
from glycotwin.twin.replay import ReplaySession, replay_lifecycle, validate_replay_events
from glycotwin.twin.state import TwinStore, exclude_forecast, forecast_meal, reconcile_forecast

PID = demo_mod.DEMO_PARTICIPANT_ID


def fresh(n=6):
    return demo_mod.build_demo_store(0), demo_mod.demo_events(0, n)


def with_exclusion(ev, idx, reason="sensor gap over 30 minutes"):
    ev = ev.copy()
    ev["excluded_reason"] = None
    ev.loc[ev.index[idx], "excluded_reason"] = reason
    ev.loc[ev.index[idx], ["peak_glucose_rise", "label_exceeds_180"]] = np.nan          # no trustworthy outcome exists
    return ev


# ------------------------------------------------------------------ exclusion branch

def test_an_excluded_meal_is_forecast_but_never_updates_the_twin():
    store, ev = fresh(5)
    log = replay_lifecycle(store, PID, with_exclusion(ev, 2))
    acts = [s["action"] for s in log]
    assert acts.count("exclude (outcome untrustworthy; no update)") == 1 and sum(a.startswith("reconcile") for a in acts) == 4
    tw = store.current_twin(PID)
    assert tw.version == 4 and tw.model_c.n_observations_used == 4 and len(store.twin_history(PID)) == 5      # 5 meals, 4 updates
    ex = store.exclusions(PID)
    assert len(ex) == 1 and ex[0].reason == "sensor gap over 30 minutes" and store.is_excluded(ex[0].forecast_id)
    assert store.pending_forecasts(PID) == [] and len(store.reconciliation_log(PID)) == 4
    entry = [s for s in log if s["action"].startswith("exclude")][0]
    assert entry["twin_version_before"] == entry["twin_version_after"] and "reason" in entry


def test_the_posterior_equals_that_of_a_replay_without_the_excluded_meal():
    store, ev = fresh(5)
    replay_lifecycle(store, PID, with_exclusion(ev, 2))
    ref_store, _ = fresh(5)
    replay_lifecycle(ref_store, PID, ev.drop(ev.index[2]))
    a, b = store.current_twin(PID), ref_store.current_twin(PID)
    assert np.allclose(a.model_c.mean, b.model_c.mean) and np.allclose(a.model_c.covariance, b.model_c.covariance)
    assert np.allclose(a.model_b.mean, b.model_b.mean)


def test_exclusion_guards():
    store, ev = fresh(2)
    rec = forecast_meal(store, PID, ev.iloc[0])
    with pytest.raises(ValueError, match="needs a reason"):
        exclude_forecast(store, rec.forecast_id, "  ")
    with pytest.raises(ValueError, match="window not complete"):
        exclude_forecast(store, rec.forecast_id, "gap", observed_through=rec.meal_time + pd.Timedelta(minutes=60))
    exclude_forecast(store, rec.forecast_id, "gap")
    with pytest.raises(ValueError, match="already excluded"):
        exclude_forecast(store, rec.forecast_id, "gap")
    with pytest.raises(ValueError, match="marked excluded"):
        reconcile_forecast(store, rec.forecast_id, 50.0, False)
    rec2 = forecast_meal(store, PID, ev.iloc[1])
    reconcile_forecast(store, rec2.forecast_id, float(ev.iloc[1]["peak_glucose_rise"]), bool(ev.iloc[1]["label_exceeds_180"]))
    with pytest.raises(ValueError, match="already reconciled"):
        exclude_forecast(store, rec2.forecast_id, "gap")
    with pytest.raises(KeyError):
        exclude_forecast(store, "no-such-forecast", "gap")
    assert store.current_twin(PID).version == 1


def test_a_missing_outcome_is_refused_unless_the_event_is_marked_excluded():
    store, ev = fresh(3)
    bad = ev.copy(); bad.loc[bad.index[1], "peak_glucose_rise"] = np.nan
    with pytest.raises(ValueError, match="peak_glucose_rise"):
        validate_replay_events(bad)
    ok = with_exclusion(ev, 1)
    assert len(validate_replay_events(ok)) == 3
    still_bad = with_exclusion(ev, 1); still_bad.loc[still_bad.index[1], "carbs_g"] = np.nan
    with pytest.raises(ValueError, match="carbs_g"):
        validate_replay_events(still_bad)                                  # an exclusion excuses only the outcome, never the inputs
    blank = ev.copy(); blank["excluded_reason"] = "   "; blank.loc[blank.index[0], "peak_glucose_rise"] = np.nan
    with pytest.raises(ValueError, match="peak_glucose_rise"):
        validate_replay_events(blank)                                      # a blank reason is not an exclusion


def test_failed_replay_with_an_exclusion_restores_the_exclusion_records_too(monkeypatch):
    from glycotwin.twin import replay as replay_mod
    store, ev = fresh(5)
    real, calls = replay_mod.reconcile_forecast, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(replay_mod, "reconcile_forecast", flaky)
    with pytest.raises(RuntimeError):
        replay_lifecycle(store, PID, with_exclusion(ev, 0))                  # the exclusion happens first, then the failure
    assert store.exclusions(PID) == [] and store.current_twin(PID).version == 0 and store._forecasts == {} and store._observations == {}


# ------------------------------------------------------------------ step-wise replay session

def test_stepping_one_event_at_a_time_equals_the_whole_replay():
    s1, ev = fresh(6)
    full = replay_lifecycle(s1, PID, ev)
    s2, _ = fresh(6)
    sess = ReplaySession(s2, PID, ev)
    steps = []
    while sess.n_remaining:
        steps.append(sess.step())
    steps.append(sess.finish())
    assert [e["action"] for st in steps for e in st] == [e["action"] for e in full] and sess.done
    assert np.allclose(s1.current_twin(PID).model_c.mean, s2.current_twin(PID).model_c.mean)
    assert [round(e["model_c"]["p_peak_at_least_180"], 12) for e in sess.log if "model_c" in e] == [round(e["model_c"]["p_peak_at_least_180"], 12) for e in full if "model_c" in e]


def test_a_step_forecasts_before_it_learns_and_only_resolves_closed_windows():
    store, ev = fresh(3)
    sess = ReplaySession(store, PID, ev)
    first = sess.step()
    assert [e["action"].split()[0] for e in first] == ["forecast"] and store.current_twin(PID).version == 0
    second = sess.step()                                   # events are 6 h apart: meal 1's window closed -> reconcile, then forecast meal 2
    assert [e["action"].split()[0] for e in second] == ["reconcile", "forecast"]
    assert second[1]["twin_version_at_forecast"] == 1 and len(store.pending_forecasts(PID)) == 1


def test_session_misuse_and_atomic_steps(monkeypatch):
    from glycotwin.twin import replay as replay_mod
    store, ev = fresh(3)
    sess = ReplaySession(store, PID, ev)
    with pytest.raises(ValueError, match="not been stepped"):
        sess.finish()
    sess.step()
    real = replay_mod.reconcile_forecast
    monkeypatch.setattr(replay_mod, "reconcile_forecast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        sess.step()                                        # would reconcile meal 1 then forecast meal 2
    assert sess.n_remaining == 2 and store.current_twin(PID).version == 0 and len(store._forecasts) == 1 and len(sess.log) == 1
    monkeypatch.setattr(replay_mod, "reconcile_forecast", real)
    sess.step(); sess.step(); sess.finish()
    assert sess.done and store.current_twin(PID).version == 3
    with pytest.raises(StopIteration):
        sess.step()
    assert sess.finish() == []
    with pytest.raises(KeyError):
        ReplaySession(TwinStore(), "nobody", ev)


# ------------------------------------------------------------------ side-by-side what-if (blueprint Part 20)

def test_side_by_side_what_if_matches_the_example_structure_and_carries_the_verbatim_label():
    store, ev = fresh(4)
    replay_lifecycle(store, PID, ev)
    tw = store.current_twin(PID)
    r = insight.what_if_side_by_side(tw, {"carbs_g": 60.0, "activity_level": 0.1}, {"carbs_g": 40.0, "activity_level": 0.1}, baseline_glucose=110.0)
    assert r["screen_label"] == ("This is a research simulation based on this patient's learned model. It is not a diet prescription, "
                                 "treatment recommendation, or insulin dosing suggestion.")
    for m in ("model_b", "model_c"):
        cur, sc, d = r["current"][m], r["scenario"][m], r["difference_scenario_minus_current"][m]
        assert d["p_peak_at_least_180"] == pytest.approx(sc["p_peak_at_least_180"] - cur["p_peak_at_least_180"])
        assert d["mean_rise_mg_dl"] == pytest.approx(sc["distribution"]["mean_rise_mg_dl"] - cur["distribution"]["mean_rise_mg_dl"])
        assert d["mean_rise_mg_dl"] < 0 and d["p_peak_at_least_180"] <= 0                       # less carbohydrate -> smaller rise
    assert r["twin_version_used"] == tw.version and r["current"]["model_c"]["p_peak_at_least_180"] == insight.what_if(tw, [{"carbs_g": 60.0, "activity_level": 0.1}], 110.0)["scenarios"][0]["model_c"]["p_peak_at_least_180"]
    assert len(store.twin_history(PID)) == 5 and store.pending_forecasts(PID) == []            # nothing stored or learned


def test_the_main_what_if_output_also_carries_the_verbatim_label():
    tw = demo_mod.build_demo_store(0).current_twin(PID)
    assert "not a diet prescription" in insight.what_if(tw, [{"carbs_g": 50.0, "activity_level": 0.2}], 100.0)["screen_label"]


# ------------------------------------------------------------------ twin history export (blueprint Part 23, optional)

def test_twin_history_rows_cover_every_version_and_link_to_the_parent():
    store, ev = fresh(4)
    replay_lifecycle(store, PID, ev)
    rows = insight.twin_history_rows(store, PID, reference_activity=0.5)
    assert [r["version_id"] for r in rows] == [0, 1, 2, 3, 4] and rows[0]["parent_version_id"] is None
    assert [r["parent_version_id"] for r in rows[1:]] == [0, 1, 2, 3] and [r["n_meals_observed"] for r in rows] == [0, 1, 2, 3, 4]
    hist = store.twin_history(PID)
    for r, tw in zip(rows, hist):
        assert r["beta_mean"] == pytest.approx(tw.model_c.mean[0]) and r["gamma_var"] == pytest.approx(tw.model_c.covariance[1, 1])
        assert r["beta_gamma_covariance"] == pytest.approx(tw.model_c.covariance[0, 1]) and r["model_b_sensitivity_mean"] == pytest.approx(tw.model_b.mean[0])
    csv = insight.twin_history_csv(store, PID, 0.5)
    lines = csv.strip().splitlines()
    assert len(lines) == 6 and lines[0].startswith("version_id,parent_version_id") and "DEMO" not in csv.splitlines()[1]


# ------------------------------------------------------------------ Model A TreeSHAP contributions (blueprint Part 14/18: SHAP for Model A only)

def test_model_a_contributions_are_exact_additive_and_for_the_population_model_only():
    from glycotwin.models.baseline import BASELINE_FEATURE_COLUMNS, PopulationBaselineModel
    pop = demo_mod.demo_population(0)
    m = PopulationBaselineModel().fit(pop)
    c = m.contributions(pop.head(40))
    assert list(c.columns) == BASELINE_FEATURE_COLUMNS + ["bias"] and len(c) == 40
    p = m.predict_proba(pop.head(40))
    logit = np.log(p / (1 - p))
    assert np.allclose(c.sum(axis=1).to_numpy(), logit, atol=1e-4)                        # contributions + bias = the model's log-odds
    assert m.contributions(pop.head(40)).equals(c)                                          # deterministic
    with pytest.raises(RuntimeError):
        PopulationBaselineModel().contributions(pop.head(3))
    with pytest.raises(ValueError):
        m.contributions(pop.head(3).drop(columns=["carbs_g"]))


# ------------------------------------------------------------------ boundary cases pinned by the mutation checks

def test_a_failed_second_replay_keeps_an_exclusion_recorded_by_the_first(monkeypatch):
    from glycotwin.twin import replay as replay_mod
    store, ev = fresh(6)
    replay_lifecycle(store, PID, with_exclusion(ev, 1).head(3))
    assert len(store.exclusions(PID)) == 1
    later = ev.iloc[3:].copy()
    later["meal_time"] = later["meal_time"] + pd.Timedelta(days=1)
    real = replay_mod.reconcile_forecast
    n = {"i": 0}

    def flaky(*a, **k):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("boom")
        return real(*a, **k)
    monkeypatch.setattr(replay_mod, "reconcile_forecast", flaky)
    with pytest.raises(RuntimeError):
        replay_lifecycle(store, PID, later)
    assert len(store.exclusions(PID)) == 1 and store.current_twin(PID).version == 2          # the earlier exclusion and updates survive the rollback


def test_a_step_that_fails_after_logging_part_of_its_work_leaves_the_log_unchanged(monkeypatch):
    from glycotwin.twin import replay as replay_mod
    store, ev = fresh(3)
    sess = ReplaySession(store, PID, ev)
    sess.step()
    n_log = len(sess.log)
    real = replay_mod.forecast_meal
    monkeypatch.setattr(replay_mod, "forecast_meal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("late failure")))
    with pytest.raises(RuntimeError):
        sess.step()                          # reconciles meal 1 (a log entry is written), then the forecast of meal 2 fails
    assert len(sess.log) == n_log and store.current_twin(PID).version == 0 and len(store.reconciliation_log(PID)) == 0
    monkeypatch.setattr(replay_mod, "forecast_meal", real)
    sess.step()
    assert [e["action"].split()[0] for e in sess.log[n_log:]] == ["reconcile", "forecast"]
