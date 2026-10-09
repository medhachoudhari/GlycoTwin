"""Reconciliation report, forecast explanation, population-informed initialisation, event feed, store overview and the replay script.
SYNTHETIC data only (seeded demo population); these tests check mechanics and leakage safeguards, not scientific results."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.twin import demo as demo_mod
from glycotwin.twin import insight
from glycotwin.twin.adapter import initialize_twin_from_population, prepare_participant_events
from glycotwin.twin.replay import replay_lifecycle
from glycotwin.twin.state import TwinStore

ROOT = Path(__file__).resolve().parents[1]
PID = demo_mod.DEMO_PARTICIPANT_ID


def replayed(n=6, seed=0):
    store, ev = demo_mod.build_demo_store(seed), demo_mod.demo_events(seed, n)
    replay_lifecycle(store, PID, ev)
    return store, ev


def event_table(seed=0):
    t = demo_mod.demo_population(seed).copy()
    t["event_id"] = [f"e{i}" for i in range(len(t))]
    t["eligible_core"] = True
    t["eligible_activity"] = True
    return t


# ------------------------------------------------------------------ reconciliation report

def test_reconciliation_report_matches_the_log_and_marks_observed_vs_predicted():
    store, ev = replayed(5)
    r = insight.reconciliation_report(store, PID)
    assert r["summary"]["n_reconciled"] == 5 and r["summary"]["n_pending"] == 0 and r["pending"] == []
    for row, (_, e) in zip(r["reconciled"], ev.iterrows()):
        assert row["observed"]["peak_rise_mg_dl"] == pytest.approx(e["peak_glucose_rise"])
        assert row["observed"]["peak_at_least_180"] == bool(e["label_exceeds_180"])
        assert row["observed"]["kind"].startswith("OBSERVED")
        assert row["twin_version_after_update"] > row["twin_version_at_forecast"]
        for m in ("model_b", "model_c"):
            d = row[m]
            lo, hi = d["forecast_interval90_mg_dl"]
            assert d["observed_inside_interval90"] == (lo <= e["peak_glucose_rise"] <= hi)
            assert d["standardised_error"] == pytest.approx((e["peak_glucose_rise"] - d["forecast_mean_rise_mg_dl"]) / d["forecast_sd_mg_dl"])
            p = d["forecast_p_peak_at_least_180"]
            assert d["brier_component"] == pytest.approx((p - e["label_exceeds_180"]) ** 2)
            assert d["probability_given_to_what_happened"] == pytest.approx(p if e["label_exceeds_180"] else 1 - p)
    assert r["summary"]["model_c"]["mean_brier"] == pytest.approx(np.mean([x["model_c"]["brier_component"] for x in r["reconciled"]]))
    assert "descriptive" in r["note"]


def test_reconciliation_report_lists_unreconciled_forecasts_as_pending_without_outcome():
    from glycotwin.twin.state import forecast_meal
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 2)
    forecast_meal(store, PID, ev.iloc[0])
    r = insight.reconciliation_report(store, PID)
    assert r["reconciled"] == [] and len(r["pending"]) == 1 and r["pending"][0]["status"].startswith("PENDING")
    assert "observed" not in r["pending"][0] and "peak_glucose_rise" not in json.dumps(r["pending"])
    with pytest.raises(KeyError):
        insight.reconciliation_report(store, "nobody")


def test_reconciliation_report_is_read_only():
    store, _ = replayed(4)
    v, n = store.current_twin(PID).version, len(store.twin_history(PID))
    insight.reconciliation_report(store, PID)
    assert store.current_twin(PID).version == v and len(store.twin_history(PID)) == n


# ------------------------------------------------------------------ explain_forecast

@pytest.mark.parametrize("model", ["model_b", "model_c"])
def test_explain_forecast_terms_sum_to_prediction_and_agree_with_the_forecast(model):
    store, _ = replayed(4)
    tw = store.current_twin(PID)
    meal = {"carbs_g": 70.0, "activity_level": 0.4, "baseline_glucose": 110.0}
    x = insight.explain_forecast(tw, meal, model)
    assert sum(t["contribution_mg_dl"] for t in x["terms"].values()) == pytest.approx(x["predicted_rise_mg_dl"])
    st = tw.model_b if model == "model_b" else tw.model_c
    from glycotwin.models.bayesian import forecast_exceeds_180
    f = forecast_exceeds_180(st, pd.Series({"carbs_g": 70.0, "activity_level": 0.4}), 110.0)
    assert x["p_peak_at_least_180"] == pytest.approx(f.probability_exceeds_180)
    assert x["predictive_sd_mg_dl"] == pytest.approx(f.predictive_std)
    v = x["variance"]
    assert v["parameter_uncertainty"] + v["residual_noise"] == pytest.approx(x["predictive_sd_mg_dl"] ** 2)
    assert v["share_parameter_uncertainty"] == pytest.approx(v["parameter_uncertainty"] / x["predictive_sd_mg_dl"] ** 2) and 0 < v["share_parameter_uncertainty"] < 1
    assert f"{100 * v['share_parameter_uncertainty']:.0f}% of the predictive variance" in " ".join(x["plain_language"])
    assert x["margin_to_180_mg_dl"] == pytest.approx(110.0 + x["predicted_rise_mg_dl"] - 180.0)
    assert "not a causal claim" in x["kind"] and x["twin_version"] == tw.version
    assert x["plain_language"] and all(isinstance(s, str) for s in x["plain_language"])


def test_explain_forecast_model_b_has_no_activity_term_and_model_c_does():
    tw = demo_mod.build_demo_store(0).current_twin(PID)
    meal = {"carbs_g": 50.0, "activity_level": 0.9, "baseline_glucose": 100.0}
    assert list(insight.explain_forecast(tw, meal, "model_b")["terms"]) == ["carbs_g"]
    assert "carbs_x_activity" in insight.explain_forecast(tw, meal, "model_c")["terms"]


@pytest.mark.parametrize("meal, msg", [
    ({"carbs_g": float("nan"), "activity_level": 0.5, "baseline_glucose": 100.0}, "finite"),
    ({"carbs_g": 50.0, "activity_level": float("inf"), "baseline_glucose": 100.0}, "finite"),
    ({"carbs_g": 50.0, "activity_level": 0.5}, "baseline_glucose"),
    ({"carbs_g": -5.0, "activity_level": 0.5, "baseline_glucose": 100.0}, "negative"),
])
def test_explain_forecast_rejects_bad_inputs(meal, msg):
    tw = demo_mod.build_demo_store(0).current_twin(PID)
    with pytest.raises(ValueError, match=msg):
        insight.explain_forecast(tw, meal)
    with pytest.raises(ValueError, match="model"):
        insight.explain_forecast(tw, {"carbs_g": 1.0, "activity_level": 0.1, "baseline_glucose": 100.0}, "model_z")


def test_explain_forecast_is_read_only():
    store = demo_mod.build_demo_store(0)
    tw = store.current_twin(PID)
    before = (tw.model_c.mean.copy(), tw.model_c.covariance.copy())
    insight.explain_forecast(tw, {"carbs_g": 60.0, "activity_level": 0.3, "baseline_glucose": 100.0})
    assert np.array_equal(tw.model_c.mean, before[0]) and np.array_equal(tw.model_c.covariance, before[1])
    assert store.pending_forecasts(PID) == []


# ------------------------------------------------------------------ population-informed initialisation (leakage)

def test_population_init_excludes_own_events_and_counts_them():
    t = event_table()
    pid = "p003"
    store = TwinStore()
    tw = initialize_twin_from_population(store, pid, t, profile={"channel": "test"})
    meta = tw.profile["population_prior"]
    own = int((t["participant_id"] == pid).sum())
    assert meta["own_events_excluded_from_prior"] == own > 0
    assert meta["n_training_events"] == len(t) - own and meta["n_training_participants"] == t["participant_id"].nunique() - 1
    assert tw.profile["channel"] == "test" and tw.version == 0


def test_population_prior_does_not_depend_on_the_participants_own_outcomes():
    t = event_table()
    pid = "p003"
    t2 = t.copy()
    m = t2["participant_id"] == pid
    t2.loc[m, "peak_glucose_rise"] = t2.loc[m, "peak_glucose_rise"] * 5 + 300
    a, b = TwinStore(), TwinStore()
    ta = initialize_twin_from_population(a, pid, t)
    tb = initialize_twin_from_population(b, pid, t2)
    assert np.array_equal(ta.model_b.mean, tb.model_b.mean) and np.array_equal(ta.model_c.mean, tb.model_c.mean)
    assert np.array_equal(ta.model_c.covariance, tb.model_c.covariance)
    other = t.copy()
    mo = other["participant_id"] == "p004"
    other.loc[mo, "peak_glucose_rise"] += 100                      # perturbing someone ELSE must change the prior
    tc = initialize_twin_from_population(TwinStore(), pid, other)
    assert not np.allclose(ta.model_b.mean, tc.model_b.mean)


def test_population_init_rejects_bad_populations():
    t = event_table()
    with pytest.raises(ValueError, match="missing columns"):
        initialize_twin_from_population(TwinStore(), "p001", t.drop(columns=["activity_level"]))
    with pytest.raises(ValueError, match="at least two"):
        initialize_twin_from_population(TwinStore(), "p001", t[t["participant_id"].isin(["p001", "p002"])])
    bad = t.copy()
    bad.loc[bad["participant_id"] == "p005", "activity_level"] = np.nan
    with pytest.raises(ValueError, match="missing or non-numeric"):
        initialize_twin_from_population(TwinStore(), "p001", bad)


# ------------------------------------------------------------------ prepare_participant_events

def test_prepare_participant_events_filters_eligibility_sorts_and_validates():
    t = event_table()
    t.loc[(t["participant_id"] == "p002") & (t.index % 3 == 0), "eligible_activity"] = False
    ev = prepare_participant_events(t.sample(frac=1, random_state=1), "p002")
    assert (ev["meal_time"].diff().dropna() >= pd.Timedelta(0)).all()
    assert len(ev) == int(((t["participant_id"] == "p002") & t["eligible_activity"]).sum())
    with pytest.raises(ValueError, match="no core-eligible"):
        prepare_participant_events(t, "ghost")
    with pytest.raises(ValueError, match="eligible_activity"):
        prepare_participant_events(t.drop(columns=["eligible_activity"]), "p002")
    bad = t.copy()
    bad.loc[bad["participant_id"] == "p002", "baseline_glucose"] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        prepare_participant_events(bad, "p002")


def test_population_init_then_full_replay_on_a_held_out_participant():
    t = event_table()
    pid = "p007"
    store = TwinStore()
    initialize_twin_from_population(store, pid, t)
    ev = prepare_participant_events(t, pid)
    log = replay_lifecycle(store, pid, ev)
    n = len(ev)
    assert sum(s["action"].startswith("forecast") for s in log) == n and sum(s["action"].startswith("reconcile") for s in log) == n
    assert store.current_twin(pid).version == n and store.pending_forecasts(pid) == []


# ------------------------------------------------------------------ store overview and TwinStore.participants

def test_store_overview_lists_every_twin_with_counts_and_no_forecast_side_effects():
    store, _ = replayed(3)
    initialize_twin_from_population(store, "p001", event_table())
    assert store.participants() == sorted([PID, "p001"])
    o = insight.store_overview(store, reference_activity=0.5)
    assert o["n_twins"] == 2 and [r["participant_label"] for r in o["twins"]] == store.participants()
    row = {r["participant_label"]: r for r in o["twins"]}
    assert row[PID]["n_reconciled"] == 3 and row[PID]["n_pending_forecasts"] == 0 and row[PID]["twin_version"] == 3
    assert row["p001"]["twin_version"] == 0 and row["p001"]["n_reconciled"] == 0
    ref = row[PID]["model_c_sensitivity_at_reference_activity"]
    assert ref["reference_activity"] == 0.5 and ref["sd"] > 0
    assert o["guardrails"]
    assert len(store.twin_history(PID)) == 4


def test_store_overview_omits_c_sensitivity_without_reference_activity():
    store = demo_mod.build_demo_store(0)
    row = insight.store_overview(store)["twins"][0]
    assert row["model_c_sensitivity_at_reference_activity"] is None
    assert "model_c_activity_interaction" in row


def test_empty_store_overview():
    assert insight.store_overview(TwinStore())["n_twins"] == 0


# ------------------------------------------------------------------ replay_participant script

def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_replay_script_prints_counts_only_and_writes_local_trajectory(tmp_path, capsys):
    t = event_table()
    path = tmp_path / "event_table_Libre_GL.csv"
    t.to_csv(path, index=False)
    out = tmp_path / "out"
    rc = load_script("replay_participant").main(["--event-table", str(path), "--participant-index", "1", "--out-dir", str(out)])
    assert rc == 0
    shown = capsys.readouterr().out
    summary = json.loads(shown)
    assert summary["n_events_replayed"] > 0 and summary["n_forecasts"] == summary["n_reconciliations"] == summary["n_events_replayed"]
    assert "p001" not in shown and "carbs" not in shown                  # no participant identifiers or values on screen
    assert (out / "twin_replay_Libre_GL_participant1.json").exists()


def test_replay_script_error_paths(tmp_path, capsys):
    mod = load_script("replay_participant")
    assert mod.main(["--event-table", str(tmp_path / "event_table_Libre_GL.csv")]) == 2
    t = event_table()
    path = tmp_path / "event_table_Libre_GL.csv"
    t.to_csv(path, index=False)
    assert mod.main(["--event-table", str(path), "--participant-index", "999", "--out-dir", str(tmp_path)]) == 2
    wrong = tmp_path / "event_table_Dexcom_GL.csv"
    t.to_csv(wrong, index=False)
    assert mod.main(["--event-table", str(wrong), "--channel", "Libre GL"]) == 2
    capsys.readouterr()


# ------------------------------------------------------------------ participant-ID normalisation (leakage regression)

def _int_id_table():
    t = event_table()
    t["participant_id"] = t["participant_id"].str[1:].astype(int)               # integer identifiers, as a CSV would give
    return t


def test_integer_ids_with_string_participant_exclude_the_own_events():
    t = _int_id_table()
    tw = initialize_twin_from_population(TwinStore(), "3", t)                    # string "3" vs integer column
    meta = tw.profile["population_prior"]
    assert meta["own_events_excluded_from_prior"] == int((t["participant_id"] == 3).sum()) > 0 and meta["participant_seen_in_population"]
    tw_int = initialize_twin_from_population(TwinStore(), 3, t)
    assert np.array_equal(tw.model_b.mean, tw_int.model_b.mean) and np.array_equal(tw.model_c.covariance, tw_int.model_c.covariance)


def test_string_ids_with_integer_participant_exclude_the_own_events():
    t = event_table()
    tw = initialize_twin_from_population(TwinStore(), 3, t.assign(participant_id=t["participant_id"].str[1:].str.lstrip("0")))
    assert tw.profile["population_prior"]["own_events_excluded_from_prior"] > 0


def test_float_ids_from_a_nan_padded_column_match_the_integer_participant():
    t = _int_id_table()
    t["participant_id"] = t["participant_id"].astype(float)
    tw = initialize_twin_from_population(TwinStore(), 3, t)
    assert tw.profile["population_prior"]["own_events_excluded_from_prior"] == int((t["participant_id"] == 3.0).sum()) > 0


def test_own_outcomes_cannot_reach_the_prior_through_an_id_type_mismatch():
    t = _int_id_table()
    t2 = t.copy()
    m = t2["participant_id"] == 3
    t2.loc[m, "peak_glucose_rise"] = t2.loc[m, "peak_glucose_rise"] * 7 + 500
    a = initialize_twin_from_population(TwinStore(), "3", t)
    b = initialize_twin_from_population(TwinStore(), "3", t2)
    assert np.array_equal(a.model_b.mean, b.model_b.mean) and np.array_equal(a.model_c.mean, b.model_c.mean)
    assert np.array_equal(a.model_c.covariance, b.model_c.covariance) and a.model_c.noise_variance == b.model_c.noise_variance


def test_a_participant_with_no_matching_rows_is_refused_unless_explicitly_new():
    t = _int_id_table()
    with pytest.raises(ValueError, match="no rows"):
        initialize_twin_from_population(TwinStore(), "999", t)
    with pytest.raises(ValueError, match="no rows"):
        initialize_twin_from_population(TwinStore(), "P3", t)                    # a mismatch of spelling, not a new person
    tw = initialize_twin_from_population(TwinStore(), "999", t, allow_unseen_participant=True)
    assert tw.profile["population_prior"]["own_events_excluded_from_prior"] == 0 and not tw.profile["population_prior"]["participant_seen_in_population"]


def test_ambiguous_identifier_spellings_are_refused():
    t = event_table()
    t.loc[t["participant_id"] == "p003", "participant_id"] = "p003 "              # same person written two ways
    t.loc[t.index[0], "participant_id"] = "p003"
    with pytest.raises(ValueError, match="more than one spelling"):
        initialize_twin_from_population(TwinStore(), "p003", t)
    num = _int_id_table()
    num["participant_id"] = num["participant_id"].astype(object)
    num.loc[num.index[0], "participant_id"] = "3.0"                                 # 3 and "3.0" in one column
    with pytest.raises(ValueError, match="more than one spelling"):
        initialize_twin_from_population(TwinStore(), 3, num)


def test_case_is_not_folded_and_whitespace_around_the_argument_is_ignored():
    t = event_table()
    tw = initialize_twin_from_population(TwinStore(), " p003 ", t)
    assert tw.profile["population_prior"]["own_events_excluded_from_prior"] > 0
    with pytest.raises(ValueError, match="no rows"):
        initialize_twin_from_population(TwinStore(), "P003", t)


def test_prepare_participant_events_uses_canonical_ids():
    t = _int_id_table()
    assert len(prepare_participant_events(t, "3")) == len(prepare_participant_events(t, 3)) > 0


# ------------------------------------------------------------------ blueprint section 21 twin-specific metrics: convergence and hit-rate trend

def test_posterior_convergence_reports_per_version_sds_ratios_and_monotonicity():
    store, _ = replayed(6)
    r = insight.posterior_convergence(store, PID, 0.5)
    assert r["n_versions"] == 7 and r["n_observations"] == list(range(7))
    for name, sd in r["sd"].items():
        assert len(sd) == 7 and sd[0] > 0
        assert r["ratio_to_prior"][name][0] == pytest.approx(1.0) and r["monotone_non_increasing"][name]
        assert r["current_over_prior"][name] == pytest.approx(sd[-1] / sd[0]) and sd[-1] <= sd[0]
    assert r["sd"]["model_b_sensitivity_sd"][-1] < r["sd"]["model_b_sensitivity_sd"][0]            # the carbohydrate sd really fell


def test_posterior_convergence_needs_a_reference_activity_for_the_unscaled_model():
    store, _ = replayed(2)
    with pytest.raises(ValueError, match="reference_activity"):
        insight.posterior_convergence(store, PID)


def test_posterior_convergence_detects_a_widening_series(monkeypatch):
    store, _ = replayed(3)
    real = insight.parameter_history

    def widening(*a, **k):
        h = real(*a, **k)
        h["versions"][2]["b_sensitivity_sd"] = h["versions"][0]["b_sensitivity_sd"] * 2                  # inject a sd that grew
        return h
    monkeypatch.setattr(insight, "parameter_history", widening)
    r = insight.posterior_convergence(store, PID, 0.5)
    assert r["monotone_non_increasing"]["model_b_sensitivity_sd"] is False and r["monotone_non_increasing"]["model_c_beta_sd"]


def test_hit_rate_trend_uses_the_50_percent_threshold_and_matches_the_reconciliation_report():
    store, ev = replayed(8)
    r = insight.hit_rate_trend(store, PID, window=3)
    rep = insight.reconciliation_report(store, PID)["reconciled"]
    assert r["n_reconciled"] == 8
    for name in ("model_b", "model_c"):
        expect = [bool((x[name]["forecast_p_peak_at_least_180"] >= 0.5) == x["observed"]["peak_at_least_180"]) for x in rep]
        assert r[name]["hits"] == expect
        assert r[name]["cumulative_hit_rate"][-1] == pytest.approx(np.mean(expect)) == pytest.approx(r[name]["overall_hit_rate"])
        assert r[name]["rolling_hit_rate"][2] == pytest.approx(np.mean(expect[:3])) and r[name]["rolling_hit_rate"][-1] == pytest.approx(np.mean(expect[-3:]))
        assert r[name]["first_half_hit_rate"] == pytest.approx(np.mean(expect[:4])) and r[name]["second_half_hit_rate"] == pytest.approx(np.mean(expect[4:]))
    assert "chance" in r["note"]


def test_hit_rate_trend_edge_cases():
    store = demo_mod.build_demo_store(0)
    empty = insight.hit_rate_trend(store, PID)
    assert empty["n_reconciled"] == 0 and empty["model_c"]["overall_hit_rate"] is None and empty["model_c"]["second_half_hit_rate"] is None
    with pytest.raises(ValueError):
        insight.hit_rate_trend(store, PID, window=0)
    s1, _ = replayed(1)
    assert insight.hit_rate_trend(s1, PID)["model_c"]["second_half_hit_rate"] is None             # one forecast cannot be halved


def test_hit_threshold_boundary_counts_p_equal_to_half_as_positive():
    from glycotwin.twin.state import forecast_meal, reconcile_forecast
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 1).iloc[0]
    rec = forecast_meal(store, PID, ev)
    reconcile_forecast(store, rec.forecast_id, float(ev["peak_glucose_rise"]), bool(ev["label_exceeds_180"]))
    p = rec.model_c_forecast.probability_exceeds_180
    hit_at_p = insight.hit_rate_trend(store, PID, threshold=p)["model_c"]["hits"][0]               # threshold == p -> predicted positive
    assert hit_at_p == bool(ev["label_exceeds_180"])


# ------------------------------------------------------------------ blueprint section 18: contributing factors

def test_contributing_factors_cover_carbs_activity_trend_and_own_history():
    store, ev = replayed(6)
    meal = {"carbs_g": float(ev["carbs_g"].iloc[0]), "activity_level": 0.1, "baseline_glucose": 110.0, "trend_slope_30min": 0.8}
    x = insight.explain_forecast_in_context(store, PID, meal)
    kinds = [f["factor"] for f in x["contributing_factors"]]
    assert kinds == ["carbohydrate", "activity", "glucose_trend", "own_history"]
    f = {f["factor"]: f for f in x["contributing_factors"]}
    assert "rising" in f["glucose_trend"]["text"] and "does not use the trend" in f["glucose_trend"]["text"]
    assert f["carbohydrate"]["contribution_mg_dl"] == pytest.approx(x["terms"]["carbs_g"]["contribution_mg_dl"])
    h = f["own_history"]
    done = [(store.get_forecast(o.forecast_id), o) for o in store.reconciliation_log(PID)]
    close = [o for fc, o in done if abs(fc.meal_row["carbs_g"] - meal["carbs_g"]) <= 0.25 * meal["carbs_g"]]
    assert h["n_similar_earlier_meals"] == len(close) >= 1                       # the meal itself was one of the six
    assert h["mean_observed_rise_mg_dl"] == pytest.approx(np.mean([o.observed_peak_rise for o in close]))
    assert h["share_reached_180"] == pytest.approx(np.mean([o.observed_exceeds_180 for o in close]))


def test_contributing_factors_without_trend_or_history_say_so():
    store = demo_mod.build_demo_store(0)
    x = insight.explain_forecast_in_context(store, PID, {"carbs_g": 60.0, "activity_level": 0.5, "baseline_glucose": 100.0})
    assert [f["factor"] for f in x["contributing_factors"]] == ["carbohydrate", "activity", "own_history"]
    assert x["contributing_factors"][-1]["n_similar_earlier_meals"] == 0 and "none yet" in x["contributing_factors"][-1]["text"]
    assert x["contributing_factors"][-1]["mean_observed_rise_mg_dl"] is None
    for slope, word in ((-0.5, "falling"), (0.05, "flat")):
        t = insight.explain_forecast_in_context(store, PID, {"carbs_g": 60.0, "activity_level": 0.5, "baseline_glucose": 100.0, "trend_slope_30min": slope})
        assert word in [f for f in t["contributing_factors"] if f["factor"] == "glucose_trend"][0]["text"]
    nan = insight.explain_forecast_in_context(store, PID, {"carbs_g": 60.0, "activity_level": 0.5, "baseline_glucose": 100.0, "trend_slope_30min": float("nan")})
    assert "glucose_trend" not in [f["factor"] for f in nan["contributing_factors"]]


def test_contributing_factors_model_b_has_no_activity_factor_and_store_is_untouched():
    store, _ = replayed(3)
    v, n = store.current_twin(PID).version, len(store._forecasts)
    x = insight.explain_forecast_in_context(store, PID, {"carbs_g": 50.0, "activity_level": 0.9, "baseline_glucose": 100.0}, "model_b")
    assert "activity" not in [f["factor"] for f in x["contributing_factors"]]
    assert store.current_twin(PID).version == v and len(store._forecasts) == n
    with pytest.raises(KeyError):
        insight.explain_forecast_in_context(store, "nobody", {"carbs_g": 50.0, "activity_level": 0.9, "baseline_glucose": 100.0})
