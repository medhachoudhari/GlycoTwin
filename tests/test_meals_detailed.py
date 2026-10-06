"""Tests for extract_meal_events_detailed: gaps, exclusion log, overlap flags, past-only baseline.

All frames are controlled synthetic software-test inputs (1-minute grid, made-up values); they
say nothing about CGMacros. They check the rules in docs/data_validity_rules.md are implemented.
"""
import numpy as np
import pandas as pd
import pytest

from glycotwin.data.meals import (
    EXCLUSION_REASONS, REASON_CHANNEL_MISSING, REASON_INTERNAL_GAP, REASON_INVALID_TIME,
    REASON_LEADING_GAP, REASON_TOO_FEW, REASON_TRAILING, extract_meal_events,
    extract_meal_events_detailed, participant_id_from_path)

T0 = pd.Timestamp("2000-01-01 08:00")


def frame(n=400, meals=(0,), cgm=None, col="Dexcom GL"):
    t = pd.date_range(T0, periods=n, freq="1min")
    g = np.linspace(100, 160, n) if cgm is None else cgm
    mt = [np.nan] * n
    for i in meals:
        mt[i] = "Lunch"
    return pd.DataFrame({"Timestamp": t, col: g, "Meal Type": mt, "Carbs": np.nan,
                         "Amount Consumed": 1.0, "Image path": "x.jpg"})


def run(df, **kw):
    return extract_meal_events_detailed(df, participant_id="P1", **kw)


# ---- the defects confirmed by executing the pushed code ----

def test_leading_gap_is_now_excluded_but_a_short_one_is_allowed():
    g = np.linspace(100, 160, 400); g[0:40] = np.nan          # no CGM for 40 min after the meal
    r = run(frame(cgm=g))
    assert r.events == [] and r.exclusions[0]["reason"] == REASON_LEADING_GAP
    assert r.exclusions[0]["detail"]["leading_gap_minutes"] == 40
    g2 = np.linspace(100, 160, 400); g2[0:10] = np.nan         # 10 min <= 15 min limit
    assert len(run(frame(cgm=g2)).events) == 1


def test_overlapping_meals_are_flagged_not_hidden():
    r = run(frame(n=500, meals=(0, 30, 300)))
    by = {e["event_id"]: e for e in r.events}
    first, second, third = (by[f"P1-m00{k}"] for k in range(3))
    assert first["overlaps_next_window"] and not first["overlaps_prior_window"]
    assert second["overlaps_prior_window"] and second["prior_meal_gap_minutes"] == 30
    assert not second["overlaps_next_window"]                  # next meal is 270 min later
    assert third["isolated"] and not first["isolated"] and not second["isolated"]


def test_missing_cgm_channel_is_logged_per_meal_not_silently_dropped():
    df = frame(meals=(0, 200), col="Libre GL")                  # file has no Dexcom column
    r = run(df, cgm_col="Dexcom GL")
    assert r.events == [] and len(r.exclusions) == 2
    assert {e["reason"] for e in r.exclusions} == {REASON_CHANNEL_MISSING}
    assert r.notes["cgm_channel_missing_from_file"] == "Dexcom GL"
    assert len(run(df, cgm_col="Libre GL").events) == 2         # the other channel works


# ---- exclusion log integrity ----

def test_counts_reconcile_and_reasons_are_known():
    g = np.linspace(100, 160, 700)
    g[300:330] = np.nan                                         # internal gap inside the 3rd meal's window
    df = frame(n=700, meals=(0, 20, 290, 690), cgm=g)           # last meal: window runs off the end
    r = run(df)
    assert r.notes["n_meal_rows"] == len(r.events) + len(r.exclusions) == 4
    assert all(e["reason"] in EXCLUSION_REASONS and e["reasons"][0] == e["reason"] for e in r.exclusions)
    reasons = {e["event_id"]: e["reason"] for e in r.exclusions}
    assert reasons["P1-m002"] == REASON_INTERNAL_GAP
    assert reasons["P1-m003"] in (REASON_TOO_FEW, REASON_TRAILING)


def test_trailing_gap_boundary():
    g = np.linspace(100, 160, 400); g[116:] = np.nan            # last valid reading 115 min after the meal
    assert len(run(frame(cgm=g)).events) == 1
    g2 = np.linspace(100, 160, 400); g2[110:] = np.nan          # 10 min short of the window end
    r = run(frame(cgm=g2))
    assert r.exclusions[0]["reason"] == REASON_TRAILING and r.exclusions[0]["detail"]["trailing_gap_minutes"] == 11


def test_invalid_meal_timestamp_is_excluded_with_a_reason():
    df = frame(meals=(0, 50))
    df.loc[50, "Timestamp"] = pd.NaT
    r = run(df)
    assert len(r.events) == 1 and r.exclusions[0]["reason"] == REASON_INVALID_TIME


def test_event_ids_are_unique_deterministic_and_carry_the_participant():
    df = frame(n=900, meals=(0, 300, 600))
    a, b = run(df), run(df)
    ids = [e["event_id"] for e in a.events]
    assert ids == [e["event_id"] for e in b.events] == ["P1-m000", "P1-m001", "P1-m002"]
    assert all(e["participant_id"] == "P1" for e in a.events)
    assert participant_id_from_path("some/dir/CGMacros-001.csv") == "CGMacros-001"


def test_duplicate_timestamps_raise_by_default_and_keep_first_on_request():
    df = pd.concat([frame(), frame().iloc[[10]]]).reset_index(drop=True)
    with pytest.raises(ValueError, match="duplicate or non-monotonic"):
        run(df)
    r = run(df, on_duplicate_timestamps="keep_first")
    assert r.notes["duplicate_timestamp_rows_dropped"] == 1 and len(r.events) == 1
    with pytest.raises(ValueError):
        run(df, on_duplicate_timestamps="whatever")


# ---- past-only baseline ----

def test_baseline_uses_only_readings_at_or_before_t0_minus_lag():
    g = np.arange(400, dtype=float)                             # reading value == minute index
    df = frame(n=400, meals=(60,), cgm=g)
    e5 = run(df).events[0]                                      # Dexcom default lag = 5 min
    assert e5["baseline_glucose"] == 55.0 and e5["baseline_age_minutes"] == 5.0 and e5["baseline_lag_minutes"] == 5.0
    assert run(df, baseline_lag_minutes=0).events[0]["baseline_glucose"] == 60.0
    assert run(df, baseline_lag_minutes=15).events[0]["baseline_glucose"] == 45.0


def test_baseline_ignores_everything_after_the_lag_cutoff():
    """Mutate every reading after t0 - lag (including the outcome window): the baseline must not move."""
    g = np.linspace(100, 160, 400)
    base = run(frame(n=400, meals=(60,), cgm=g)).events[0]["baseline_glucose"]
    g2 = g.copy(); g2[56:] = 9999.0                             # t0=60, lag=5 -> readings after index 55 are 'future'
    mutated = run(frame(n=400, meals=(60,), cgm=g2), max_cgm_gap_minutes=15).events[0]["baseline_glucose"]
    assert base == mutated == g[55]


def test_missing_baseline_keeps_the_event_but_records_none():
    r = run(frame(meals=(0,)))                                  # meal on the very first row: no past reading
    assert len(r.events) == 1 and r.events[0]["baseline_glucose"] is None


# ---- contract / privacy ----

def test_events_never_carry_amount_consumed_or_image_paths():
    e = run(frame()).events[0]
    assert "Amount Consumed" not in e and "Image path" not in e and not any("image" in k.lower() for k in e)


def test_legacy_wrapper_matches_detailed_events_and_keeps_the_old_keys():
    df = frame(meals=(0,))
    legacy, detailed = extract_meal_events(df), run(df).events
    assert len(legacy) == len(detailed) == 1
    for k in ("Timestamp", "Original Meal Type", "Normalized Meal Type", "Calories", "CGM_Window"):
        assert k in legacy[0]
    assert len(legacy[0]["CGM_Window"]) == 121                  # full 1-minute window preserved, no downsampling


def test_cgm_window_preserves_nans_on_the_one_minute_grid():
    g = np.linspace(100, 160, 400); g[30:35] = np.nan
    w = run(frame(cgm=g)).events[0]["CGM_Window"]
    assert len(w) == 121 and np.isnan(w[30:35]).all()
