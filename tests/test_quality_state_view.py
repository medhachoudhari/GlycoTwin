"""Forecast-time data quality, the blueprint TwinState view and the active/sedentary definition. SYNTHETIC data only."""
import numpy as np
import pandas as pd
import pytest

from glycotwin.models.activity_strata import ACTIVE, EXCLUDED, SEDENTARY, UNKNOWN, prospective_activity_label, within_participant_strata
from glycotwin.twin import demo as demo_mod
from glycotwin.twin import insight
from glycotwin.twin.quality import (COLD_START_MAX_OBSERVATIONS, LOW_ACTIVITY_COVERAGE, STALE_BASELINE_MINUTES, assess_forecast_quality,
                                    assess_observation_quality)
from glycotwin.twin.replay import replay_lifecycle
from glycotwin.twin.state import TwinStore, forecast_meal, reconcile_forecast
from glycotwin.twin.state_view import MIN_ROLLING, twin_state_view

PID = demo_mod.DEMO_PARTICIPANT_ID


def row(**kw):
    base = {"activity_coverage": 1.0, "activity_level": 0.5, "baseline_age_minutes": 5.0, "baseline_glucose": 100.0, "trend_slope_30min": 0.1}
    base.update(kw)
    return pd.Series(base)


# ------------------------------------------------------------------ data-quality assessment

def test_clean_inputs_with_enough_history_raise_no_warning():
    q = assess_forecast_quality(row(), 5)
    assert not q["low_data_quality"] and not q["insufficient_history"] and q["warning"] is None and q["reasons"] == []


@pytest.mark.parametrize("kw, text", [({"activity_coverage": 0.2}, "low pre-meal activity coverage"), ({"activity_coverage": np.nan}, "coverage unknown"),
                                      ({"activity_level": np.nan}, "activity missing"), ({"baseline_age_minutes": 45.0}, "45 minutes old"),
                                      ({"baseline_glucose": np.nan}, "baseline glucose missing"), ({"trend_slope_30min": np.nan}, "trend unavailable")])
def test_each_quality_problem_is_flagged_with_a_reason(kw, text):
    q = assess_forecast_quality(row(**kw), 9)
    assert q["low_data_quality"] and any(text in r for r in q["reasons"]) and q["warning"].startswith("LOW DATA QUALITY")


def test_thresholds_are_boundaries_not_off_by_one():
    assert not assess_forecast_quality(row(activity_coverage=LOW_ACTIVITY_COVERAGE), 9)["low_data_quality"]
    assert assess_forecast_quality(row(activity_coverage=LOW_ACTIVITY_COVERAGE - 0.01), 9)["low_data_quality"]
    assert not assess_forecast_quality(row(baseline_age_minutes=STALE_BASELINE_MINUTES), 9)["low_data_quality"]
    assert assess_forecast_quality(row(baseline_age_minutes=STALE_BASELINE_MINUTES + 0.1), 9)["low_data_quality"]
    assert assess_forecast_quality(row(), COLD_START_MAX_OBSERVATIONS - 1)["insufficient_history"]
    assert not assess_forecast_quality(row(), COLD_START_MAX_OBSERVATIONS)["insufficient_history"]


def test_both_warnings_can_appear_and_the_interval_is_declared_unadjusted():
    q = assess_forecast_quality(row(activity_coverage=0.1), 0)
    assert q["low_data_quality"] and q["insufficient_history"] and len(q["warnings"]) == 2
    assert q["interval_adjusted"] is False and "NOT changed" in q["note"] and q["thresholds"]["status"].startswith("engineering")


def test_outcome_window_columns_never_influence_the_forecast_assessment():
    base = assess_forecast_quality(row(), 5)
    leaky = assess_forecast_quality(row(window_completeness=0.0, data_quality_flag="overlap_next;activity_missing", peak_glucose_rise=999.0), 5)
    assert base == leaky


def test_forecast_record_carries_the_assessment_and_probabilities_are_unchanged_by_quality():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 1).iloc[0]
    good = forecast_meal(store, PID, ev.copy())
    bad_row = ev.copy()
    bad_row["activity_coverage"], bad_row["baseline_age_minutes"] = 0.1, 90.0
    bad = forecast_meal(store, PID, bad_row)
    assert good.data_quality["insufficient_history"] and bad.data_quality["low_data_quality"] and not good.data_quality["low_data_quality"]
    assert good.model_c_forecast.probability_exceeds_180 == bad.model_c_forecast.probability_exceeds_180      # no arbitrary uncertainty change
    assert good.model_c_forecast.interval_90 == bad.model_c_forecast.interval_90
    assert good.model_b_forecast.predictive_std == bad.model_b_forecast.predictive_std


def test_history_warning_disappears_once_enough_meals_were_observed():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 6)
    log = replay_lifecycle(store, PID, ev)
    flags = [s["quality_assessment"]["insufficient_history"] for s in log if s["action"].startswith("forecast")]
    assert flags == [True, True, True, False, False, False]
    first = [s for s in log if s["action"].startswith("forecast")][0]
    assert first["quality_warning"].startswith("INSUFFICIENT HISTORY")


def test_observation_quality_is_recorded_at_reconciliation():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 2).assign(window_completeness=[1.0, 0.6], data_quality_flag="ok")
    replay_lifecycle(store, PID, ev)
    obs = store.reconciliation_log(PID)
    assert obs[0].observation_quality["partial_window"] is False and obs[1].observation_quality["partial_window"] is True
    assert "lower bound" in obs[1].observation_quality["note"]
    assert assess_observation_quality(None)["window_completeness"] is None and assess_observation_quality(float("nan"))["partial_window"] is False


# ------------------------------------------------------------------ blueprint TwinState view

def test_state_view_on_a_fresh_twin_lists_what_is_unavailable_and_invents_nothing():
    v = twin_state_view(demo_mod.build_demo_store(0), PID, 0.5)
    assert v["current_glucose_state"]["last_value_mg_dl"] is None and v["prediction_state"] == {"last_forecast_id": None}
    assert v["meal_state"]["carbs_on_board"] is None and v["recent_activity_state"]["step_count_today"] is None
    assert v["recent_hr_state"]["current_hr"] is None and v["historical_response_state"]["parent_version_id"] is None
    assert v["historical_response_state"]["version_number"] == 0 and v["uncertainty"]["calibration_score_rolling"]["model_c"] is None
    assert any("calibration_score_rolling" in u for u in v["unavailable"]) and any("carbs_on_board" in u for u in v["unavailable"])


def test_state_view_after_replay_matches_the_store():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 6).assign(trend_slope_30min=0.2, baseline_age_minutes=3.0, activity_coverage=0.9, time_since_last_meal_min=360.0)
    replay_lifecycle(store, PID, ev)
    v = twin_state_view(store, PID, 0.5)
    last = ev.sort_values("meal_time").iloc[-1]
    g = v["current_glucose_state"]
    assert g["last_value_mg_dl"] == pytest.approx(last["baseline_glucose"]) and g["trend_slope_mg_dl_per_min"] == 0.2 and g["time_since_last_meal_min"] == 360.0
    assert v["recent_activity_state"]["rolling_mets_4h"] == pytest.approx(last["activity_level"]) and v["recent_activity_state"]["coverage_4h"] == 0.9
    tw = store.current_twin(PID)
    assert v["historical_response_state"]["version_number"] == 6 == tw.version and v["historical_response_state"]["parent_version_id"] == 5
    assert len(v["historical_response_state"]["reconciliation_log_ref"]) == 6
    assert v["personalized_parameters"]["n_meals_observed"] == 6
    assert v["personalized_parameters"]["carb_sensitivity_model_b"]["mean"] == pytest.approx(tw.model_b.mean[0])
    ref = insight.effective_sensitivity(tw.model_c, 0.5)
    assert v["personalized_parameters"]["carb_sensitivity_model_c_at_reference_activity"]["variance"] == pytest.approx(ref["sd"] ** 2)
    assert v["prediction_state"]["reconciled"] is True and v["prediction_state"]["horizon_minutes"] == 120.0
    assert v["uncertainty"]["calibration_score_rolling"]["n_reconciled_in_window"] == 6
    assert v["uncertainty"]["posterior_band_width_90"]["model_b"] == pytest.approx(2 * 1.6448536269514722 * ref_b_sd(tw))


def ref_b_sd(tw):
    return insight.effective_sensitivity(tw.model_b)["sd"]


def test_rolling_calibration_score_is_the_brier_of_the_recent_forecasts_and_needs_enough_of_them():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 12)
    replay_lifecycle(store, PID, ev.head(MIN_ROLLING - 1))
    assert twin_state_view(store, PID, 0.5)["uncertainty"]["calibration_score_rolling"]["model_c"] is None
    replay_lifecycle(store, PID, ev.iloc[MIN_ROLLING - 1:])
    r = twin_state_view(store, PID, 0.5)["uncertainty"]["calibration_score_rolling"]
    rep = insight.reconciliation_report(store, PID)["reconciled"][-10:]
    assert r["n_reconciled_in_window"] == 10
    assert r["model_c"] == pytest.approx(np.mean([x["model_c"]["brier_component"] for x in rep]))
    assert r["model_b"] == pytest.approx(np.mean([x["model_b"]["brier_component"] for x in rep]))


def test_open_meal_windows_use_only_forecasts_whose_window_is_still_open():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 2)
    ev.loc[ev.index[1], "meal_time"] = ev.loc[ev.index[0], "meal_time"] + pd.Timedelta(minutes=60)       # inside the first window
    r0 = forecast_meal(store, PID, ev.iloc[0])
    r1 = forecast_meal(store, PID, ev.iloc[1])
    m = twin_state_view(store, PID, 0.5)["meal_state"]
    assert [w["forecast_id"] for w in m["open_meal_windows"]] == [r0.forecast_id, r1.forecast_id]
    assert m["carbs_in_open_outcome_windows_g"] == pytest.approx(ev["carbs_g"].sum()) and m["forecasts_awaiting_reconciliation"] == []
    ev2 = demo_mod.demo_events(0, 2)                                                                       # 6 h apart: first window closed, unreconciled
    s2 = demo_mod.build_demo_store(0)
    a = forecast_meal(s2, PID, ev2.iloc[0])
    forecast_meal(s2, PID, ev2.iloc[1])
    m2 = twin_state_view(s2, PID, 0.5)["meal_state"]
    assert m2["forecasts_awaiting_reconciliation"] == [a.forecast_id] and len(m2["open_meal_windows"]) == 1


def test_state_view_is_read_only_and_profile_passes_through():
    store = TwinStore()
    from glycotwin.models.bayesian import MODEL_B_BLUEPRINT_FEATURES, fit_population_prior
    from glycotwin.models.model_c_cv import fit_scale_aware_prior
    pop = demo_mod.demo_population(0)
    store.initialize_twin("X", fit_population_prior(pop, MODEL_B_BLUEPRINT_FEATURES), fit_scale_aware_prior(pop)[0],
                          profile={"glycaemic_group": "prediabetes", "hba1c": 6.0})
    n = len(store.twin_history("X"))
    v = twin_state_view(store, "X", 0.4)
    assert v["static_profile"]["glycaemic_group"] == "prediabetes" and v["static_profile"]["hba1c"] == 6.0 and v["static_profile"]["bmi"] is None
    assert len(store.twin_history("X")) == n and store.pending_forecasts("X") == []
    with pytest.raises(KeyError):
        twin_state_view(store, "nobody")


def test_state_view_without_reference_reports_no_unscaled_sensitivity_for_a_fresh_twin():
    v = twin_state_view(demo_mod.build_demo_store(0), PID)
    assert v["personalized_parameters"]["carb_sensitivity_model_c_at_reference_activity"] is None
    assert v["uncertainty"]["posterior_band_width_90"]["model_c_at_reference_activity"] is None


def test_activity_label_is_prospective_and_needs_history():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 7)
    ev["activity_level"] = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.9]
    replay_lifecycle(store, PID, ev)
    assert twin_state_view(store, PID, 0.5)["recent_activity_state"]["activity_label"] == ACTIVE            # 0.9 > median(0.2..0.7)
    s2 = demo_mod.build_demo_store(0)
    replay_lifecycle(s2, PID, ev.head(3))
    assert twin_state_view(s2, PID, 0.5)["recent_activity_state"]["activity_label"] == UNKNOWN


# ------------------------------------------------------------------ active / sedentary definition

def test_prospective_label_rules():
    assert prospective_activity_label([1, 2, 3, 4], 5) == ACTIVE and prospective_activity_label([1, 2, 3, 4], 2.5) == SEDENTARY
    assert prospective_activity_label([1, 2, 3, 4], 2.5 + 0.0) == SEDENTARY and prospective_activity_label([1, 2, 3], 9) == UNKNOWN
    assert prospective_activity_label([1, 2, 3, np.nan, 4], np.nan) == UNKNOWN
    assert prospective_activity_label([2, 2, 2, 2], 2.0) == SEDENTARY                                       # equal to the median is not active


def test_within_participant_strata_split_each_person_at_their_own_median():
    pid = ["a"] * 6 + ["b"] * 6
    act = [1, 2, 3, 4, 5, 6] + [10, 20, 30, 40, 50, 60]                                                       # b is far more active than a, in absolute terms
    s = within_participant_strata(pid, act)
    assert list(s[:6]) == [SEDENTARY] * 3 + [ACTIVE] * 3 and list(s[6:]) == [SEDENTARY] * 3 + [ACTIVE] * 3     # relative, not an absolute threshold


def test_participants_without_both_strata_are_excluded():
    pid = ["a"] * 4 + ["b"] * 3 + ["c"] * 5
    act = [1, 2, 3, 4] + [5, 5, 5] + [1, 2, 3, 4, 5]
    s = within_participant_strata(pid, act)
    assert list(s[4:7]) == [EXCLUDED] * 3                                                                     # b is constant: nothing is above its median
    assert set(s[:4]) == {ACTIVE, SEDENTARY} and ACTIVE in set(s[7:])
    s2 = within_participant_strata(pid, act, min_per_side=3)
    assert set(s2[:4]) == {EXCLUDED}                                                                           # a has only 2 active events


def test_strata_input_validation_and_order_independence():
    with pytest.raises(ValueError, match="finite"):
        within_participant_strata(["a", "a"], [1.0, np.nan])
    pid, act = ["a", "b", "a", "b", "a", "b", "a", "b"], [1, 9, 2, 8, 3, 7, 4, 6]
    s = within_participant_strata(pid, act)
    perm = [3, 0, 7, 1, 5, 2, 6, 4]
    s2 = within_participant_strata([pid[i] for i in perm], [act[i] for i in perm])
    assert [s[i] for i in perm] == list(s2)


# ------------------------------------------------------------------ boundary cases pinned by the mutation checks

def test_ties_at_the_median_are_sedentary():
    s = within_participant_strata(["a"] * 5, [1, 2, 2, 3, 5], min_per_side=1)
    assert list(s) == [SEDENTARY, SEDENTARY, SEDENTARY, ACTIVE, ACTIVE]                  # strictly above the median 2 is active; 2 itself is not


def test_a_window_that_closes_exactly_at_the_latest_meal_is_not_open():
    store = demo_mod.build_demo_store(0)
    ev = demo_mod.demo_events(0, 2)
    ev.loc[ev.index[1], "meal_time"] = ev.loc[ev.index[0], "meal_time"] + pd.Timedelta(minutes=120)
    a = forecast_meal(store, PID, ev.iloc[0])
    b = forecast_meal(store, PID, ev.iloc[1])
    m = twin_state_view(store, PID, 0.5)["meal_state"]
    assert [w["forecast_id"] for w in m["open_meal_windows"]] == [b.forecast_id] and m["forecasts_awaiting_reconciliation"] == [a.forecast_id]


def test_rolling_calibration_score_appears_at_exactly_the_minimum_number_of_reconciled_forecasts():
    store = demo_mod.build_demo_store(0)
    replay_lifecycle(store, PID, demo_mod.demo_events(0, MIN_ROLLING))
    r = twin_state_view(store, PID, 0.5)["uncertainty"]["calibration_score_rolling"]
    assert r["n_reconciled_in_window"] == MIN_ROLLING and r["model_c"] is not None and r["model_b"] is not None


def test_trend_wording_boundaries():
    store = demo_mod.build_demo_store(0)
    base = {"carbs_g": 60.0, "activity_level": 0.5, "baseline_glucose": 100.0}
    word = lambda slope: [f for f in insight.explain_forecast_in_context(store, PID, {**base, "trend_slope_30min": slope})["contributing_factors"]
                          if f["factor"] == "glucose_trend"][0]["text"]
    assert "flat" in word(0.1) and "flat" in word(-0.1) and "rising" in word(0.1001) and "falling" in word(-0.1001)
