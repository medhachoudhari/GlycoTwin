"""Event table, features, outcomes, eligibility, count reports, and the blueprint's leakage test.

Frames are controlled synthetic software-test inputs (1-minute grid, made-up values).
The leakage test implements blueprint section 7: build the feature vector for a meal with the REAL
pipeline, mutate every CGM / Fitbit / meal reading timestamped after t0, rebuild, and require the
feature vector to be identical (plus a stronger variant for the CGM lag guard).
"""
import numpy as np
import pandas as pd
import pytest

from glycotwin.data.events import (
    ELIGIBILITY_COLUMNS, FEATURE_COLUMNS, OUTCOME_COLUMNS, build_event_table, compute_outcome,
    event_count_report, pre_meal_activity, pre_meal_trend_slope)
from glycotwin.features import MEAL_EVENT_COLUMNS, validate_meal_events

T0 = pd.Timestamp("2000-01-01 00:00")


def frame(n=900, meals=(400,), carbs=50.0, cgm=None, mets=1.5, hr=70.0):
    t = pd.date_range(T0, periods=n, freq="1min")
    g = 100 + 0.05 * np.arange(n) if cgm is None else cgm
    mt = [np.nan] * n
    cb = [np.nan] * n
    for i in meals:
        mt[i], cb[i] = "Lunch", carbs
    return pd.DataFrame({"Timestamp": t, "Dexcom GL": g, "Libre GL": g, "HR": hr, "METs": mets,
                         "Meal Type": mt, "Carbs": cb, "Protein": np.nan, "Fat": np.nan, "Fiber": np.nan,
                         "Calories": np.nan})


def build(df, **kw):
    return build_event_table(df, "P1", **kw)


# ---------------------------------------------------------------- outcome definition

def test_outcome_excludes_the_reading_at_t0_and_uses_ge_180():
    w = [200.0] + [150.0] * 60 + [180.0] + [150.0] * 59                 # high value AT t0 only; peak 180.0 later
    o = compute_outcome(w, baseline=120.0)
    assert o["peak_glucose"] == 180.0 and o["label_exceeds_180"] == 1 and o["peak_glucose_rise"] == 60.0
    w2 = [200.0] + [179.9] * 120
    assert compute_outcome(w2, 120.0)["label_exceeds_180"] == 0         # t0's 200 must not count
    assert np.isnan(compute_outcome([100.0], 100.0)["peak_glucose"])    # nothing after t0
    assert np.isnan(compute_outcome([100.0, 150.0], None)["peak_glucose_rise"])


def test_rise_is_peak_minus_a_past_only_baseline_and_label_agrees_with_the_core_validator():
    g = np.full(900, 110.0); g[430:440] = 185.0                          # excursion 30-40 min after the meal at 400
    et = build(frame(cgm=g))
    r = et.table.iloc[0]
    assert r["baseline_glucose"] == 110.0 and r["peak_glucose"] == 185.0 and r["peak_glucose_rise"] == 75.0
    assert r["label_exceeds_180"] == 1
    assert validate_meal_events(et.table[et.table["eligible_activity"]]) == []   # same schema the models consume
    assert set(MEAL_EVENT_COLUMNS) <= set(et.table.columns)


# ---------------------------------------------------------------- features

def test_activity_uses_only_the_four_hours_strictly_before_the_meal():
    df = frame(mets=2.0)
    base = pre_meal_activity(df, df.loc[400, "Timestamp"])
    assert base["mean"] == 2.0 and base["coverage"] == 1.0 and base["usable"]
    df2 = df.copy(); df2.loc[400:, "METs"] = 99.0                          # t0 and everything after
    assert pre_meal_activity(df2, df.loc[400, "Timestamp"]) == base
    df3 = df.copy(); df3.loc[200:300, "METs"] = np.nan                     # ~100 of 240 min missing
    low = pre_meal_activity(df3, df.loc[400, "Timestamp"], min_coverage=0.7)
    assert not low["usable"] and 0.5 < low["coverage"] < 0.7
    assert not pre_meal_activity(df.drop(columns=["METs"]), df.loc[400, "Timestamp"])["usable"]


def test_trend_slope_recovers_a_known_slope_and_ignores_readings_after_the_lag_cutoff():
    g = 100 + 2.0 * np.arange(900)                                         # +2 mg/dL per minute
    df = frame(cgm=g)
    t0 = df.loc[400, "Timestamp"]
    assert pre_meal_trend_slope(df, t0, "Dexcom GL", lag_minutes=5) == pytest.approx(2.0)
    g2 = g.copy(); g2[396:] = 9999.0                                       # after t0 - lag
    assert pre_meal_trend_slope(frame(cgm=g2), t0, "Dexcom GL", 5) == pytest.approx(2.0)
    sparse = df.copy(); sparse.loc[:, "Dexcom GL"] = np.nan
    assert np.isnan(pre_meal_trend_slope(sparse, t0, "Dexcom GL", 5))


def test_time_since_last_meal_counts_excluded_meals_and_ignores_the_future():
    g = 100 + 0.05 * np.arange(1500); g[:200] = np.nan                     # first meal (row 100) cannot be extracted
    et = build(frame(n=1500, meals=(100, 600), cgm=g))
    assert len(et.exclusions) == 1 and len(et.table) == 1
    assert et.table.iloc[0]["time_since_last_meal_min"] == 500.0           # measured from the excluded meal
    et2 = build(frame(n=1500, meals=(600, 1000)))                          # a later meal must not affect meal 1
    assert et2.table.iloc[0]["time_since_last_meal_min"] != et2.table.iloc[0]["time_since_last_meal_min"]  # NaN: no earlier meal


# ---------------------------------------------------------------- the blueprint's leakage test

def _mutate_after(df, cutoff, cols=("Dexcom GL", "Libre GL", "HR", "METs", "Carbs", "Calories")):
    d = df.copy()
    m = d["Timestamp"] > cutoff
    for c in cols:
        d.loc[m, c] = 12345.0
    later_meal = m & d["Meal Type"].isna()
    d.loc[later_meal.to_numpy().nonzero()[0][[5, 50, 120]], "Meal Type"] = "Snack"   # invent future meals
    return d


@pytest.mark.parametrize("meal_row", [300, 400, 600])
def test_features_are_identical_when_everything_after_t0_is_mutated(meal_row):
    df = frame(n=1200, meals=(meal_row,))
    t0 = df.loc[meal_row, "Timestamp"]
    before = build(df).table.iloc[0]
    after_df = _mutate_after(df, t0)
    after = build(after_df, max_cgm_gap_minutes=10**6, max_trailing_gap_minutes=10**6).table
    after = after[after["meal_time"] == t0].iloc[0]
    for c in FEATURE_COLUMNS:
        assert (before[c] == after[c]) or (pd.isna(before[c]) and pd.isna(after[c])), c


def test_cgm_features_are_identical_when_everything_after_the_lag_cutoff_is_mutated():
    """Stronger than the blueprint test: the guard means readings inside (t0 - lag, t0] must not matter either."""
    df = frame(n=1200, meals=(400,))
    t0 = df.loc[400, "Timestamp"]
    before = build(df).table.iloc[0]
    cutoff = t0 - pd.Timedelta(minutes=5)
    d = df.copy(); d.loc[d["Timestamp"] > cutoff, ["Dexcom GL", "Libre GL"]] = 12345.0
    after = build(d, max_cgm_gap_minutes=10**6, max_trailing_gap_minutes=10**6).table.iloc[0]
    for c in ("baseline_glucose", "baseline_age_minutes", "trend_slope_30min"):
        assert before[c] == after[c], c


def test_the_leakage_test_is_not_vacuous_outcomes_and_future_flags_do_change():
    df = frame(n=1200, meals=(400,))
    t0 = df.loc[400, "Timestamp"]
    before = build(df).table.iloc[0]
    after = build(_mutate_after(df, t0), max_cgm_gap_minutes=10**6, max_trailing_gap_minutes=10**6).table
    after = after[after["meal_time"] == t0].iloc[0]
    assert before["peak_glucose"] != after["peak_glucose"]                  # outcome legitimately uses the future
    assert before["overlaps_next_window"] != after["overlaps_next_window"]  # next-meal flag depends on the future by design


def test_column_roles_are_disjoint_and_cover_the_table():
    t = build(frame()).table
    roles = [set(FEATURE_COLUMNS), set(OUTCOME_COLUMNS), set(ELIGIBILITY_COLUMNS)]
    assert not (roles[0] & roles[1]) and not (roles[0] & roles[2]) and not (roles[1] & roles[2])
    assert (roles[0] | roles[1] | roles[2]) <= set(t.columns)


# ---------------------------------------------------------------- eligibility and reasons

def test_eligibility_flags_and_reasons():
    t = build(frame(meals=(400,))).table.iloc[0]
    assert t["eligible_core"] and t["eligible_activity"] and t["data_quality_flag"] == "ok" and t["ineligible_reasons"] == ""

    no_base = build(frame(meals=(0,)))                                      # meal on first row: no past CGM
    assert no_base.table.iloc[0]["ineligible_reasons"].startswith("baseline_missing") and not no_base.table.iloc[0]["eligible_core"]

    no_carbs = build(frame(carbs=np.nan)).table.iloc[0]
    assert "carbs_missing" in no_carbs["ineligible_reasons"] and not no_carbs["eligible_core"]

    over = build(frame(meals=(400, 450))).table
    assert not over["eligible_core"].any() and (over["ineligible_reasons"].str.contains("overlapping_meal_window")).all()
    allowed = build(frame(meals=(400, 450)), require_isolated=False).table
    assert allowed["eligible_core"].all() and set(allowed["data_quality_flag"]) == {"overlap_next", "overlap_prior"}

    df = frame(); df["METs"] = np.nan
    act = build(df).table.iloc[0]
    assert act["eligible_core"] and not act["eligible_activity"] and "activity_missing" in act["data_quality_flag"]


# ---------------------------------------------------------------- count report

def test_event_count_report_reconciles_is_anonymous_and_deterministic():
    g = 100 + 0.05 * np.arange(1500); g[:200] = np.nan
    a = build_event_table(frame(n=1500, meals=(100, 600, 1000)), "CGMacros-001")
    b = build_event_table(frame(n=1500, meals=(100, 600), cgm=g), "CGMacros-002")
    rep = event_count_report({"CGMacros-001": a, "CGMacros-002": b}, group_of={"CGMacros-001": "T2D", "CGMacros-002": "healthy"})
    assert rep["reconciles"] and rep["overall"]["n_meal_rows"] == 5
    assert rep["overall"]["n_window_valid"] + rep["overall"]["n_excluded_at_extraction"] == 5
    assert rep["n_participants"] == 2 and set(rep["by_group"]) == {"T2D", "healthy"}
    assert "CGMacros" not in str(rep) and {r["participant"] for r in rep["per_participant"]} == {"P1", "P2"}
    assert rep == event_count_report({"CGMacros-001": a, "CGMacros-002": b}, group_of={"CGMacros-001": "T2D", "CGMacros-002": "healthy"})
    assert rep["extraction_exclusion_reasons"]
