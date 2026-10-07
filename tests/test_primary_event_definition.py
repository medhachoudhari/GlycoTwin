"""The locked primary analysis definition (decision D9/D10), tested on SYNTHETIC frames only.

  anchor = the `Meal Type` row timestamp (never called meal_end; photos and next meals are not used)
  window = (t0, t0 + 120 min]       target = 1 if the maximum AVAILABLE glucose in the window >= 180
These tests show the code implements that definition; they say nothing about CGMacros itself.
"""
import numpy as np
import pandas as pd
import pytest

from glycotwin.data.events import (
    FEATURE_COLUMNS, OUTCOME_COLUMNS, RETAINED_RAW_COLUMNS, build_event_table, event_count_report)
from glycotwin.data.meals import normalize_meal_type

T0 = pd.Timestamp("2000-01-01 00:00")
MEAL = 400


def frame(n=900, meals=(MEAL,), cgm=None, mets=1.5, types=None, images=None, amount=0.8):
    t = pd.date_range(T0, periods=n, freq="1min")
    g = np.full(n, 100.0) if cgm is None else np.asarray(cgm, dtype=float).copy()
    mt = [np.nan] * n
    cb = [np.nan] * n
    for k, i in enumerate(meals):
        mt[i], cb[i] = (types[k] if types else "Lunch"), 40.0 + k
    d = pd.DataFrame({"Timestamp": t, "Dexcom GL": g, "Libre GL": g, "HR": 70.0, "METs": mets, "Meal Type": mt,
                      "Carbs": cb, "Protein": np.nan, "Fat": np.nan, "Fiber": np.nan, "Calories": np.nan,
                      "Amount Consumed": amount})
    if images:
        d["Image path"] = [("photo.jpg" if i in images else np.nan) for i in range(n)]
    return d


def build(df, **kw):
    return build_event_table(df, "P1", **kw)


def row(df, **kw):
    t = build(df, **kw).table
    assert len(t) == 1
    return t.iloc[0]


# --------------------------------------------------------------- anchor

def test_anchor_is_the_meal_row_timestamp_and_there_is_no_meal_end():
    df = frame()
    t = build(df).table
    assert t["meal_time"].iloc[0] == df.loc[MEAL, "Timestamp"]
    assert not any("meal_end" in c.lower() or "meal_start" in c.lower() for c in t.columns)


def test_photos_and_later_meals_do_not_move_the_anchor_or_change_the_row():
    plain = row(frame())
    with_photos = row(frame(images={MEAL, MEAL + 10, MEAL + 40}))
    pd.testing.assert_series_equal(plain, with_photos)                 # photo rows are ignored entirely
    two = build(frame(meals=(MEAL, MEAL + 30)), require_isolated=False).table
    assert two["meal_time"].tolist() == [T0 + pd.Timedelta(minutes=MEAL), T0 + pd.Timedelta(minutes=MEAL + 30)]


# --------------------------------------------------------------- window boundaries and target

@pytest.mark.parametrize("spike_row, expected_label, why", [
    (MEAL, 0, "the reading AT t0 is outside the open start of (t0, t0+120]"),
    (MEAL + 1, 1, "first minute after t0 is inside"),
    (MEAL + 120, 1, "t0+120 is inside the closed end"),
    (MEAL + 121, 0, "t0+121 is outside"),
])
def test_window_boundaries(spike_row, expected_label, why):
    g = np.full(900, 100.0); g[spike_row] = 250.0
    r = row(frame(cgm=g))
    assert r["label_exceeds_180"] == expected_label, why
    if expected_label == 0:
        assert r["peak_glucose"] == 100.0


def test_target_is_inclusive_at_180_and_uses_the_maximum_available_reading():
    for peak, label in ((179.99, 0), (180.0, 1), (180.01, 1)):
        g = np.full(900, 100.0); g[430:433] = [150.0, peak, 120.0]
        r = row(frame(cgm=g))
        assert r["label_exceeds_180"] == label and r["peak_glucose"] == peak and r["peak_glucose_rise"] == peak - 100.0


# --------------------------------------------------------------- missing glucose

def test_missing_glucose_is_never_imputed_and_completeness_is_reported():
    g = np.full(900, 100.0); g[450:460] = np.nan; g[455] = 300.0; g[455] = np.nan   # a peak hidden in the gap stays hidden
    r = row(frame(cgm=g))
    assert r["peak_glucose"] == 100.0 and r["label_exceeds_180"] == 0               # lower bound on the true maximum
    assert r["n_window_readings"] == 110 and r["window_completeness"] == pytest.approx(110 / 120)


def test_window_with_a_gap_beyond_the_limit_is_excluded_with_a_reason_not_dropped_silently():
    g = np.full(900, 100.0); g[450:470] = np.nan                                     # 21 minute gap
    et = build(frame(cgm=g))
    assert len(et.table) == 0 and [e["reason"] for e in et.exclusions] == ["internal_gap_exceeds_limit"]
    assert et.exclusions[0]["label_norm"] == "lunch" and et.notes["n_meal_rows"] == 1


def test_unobserved_end_of_window_and_unobserved_start_are_excluded():
    g = np.full(900, 100.0); g[505:] = np.nan                                        # last valid reading is 15 min before the end
    assert [e["reason"] for e in build(frame(cgm=g)).exclusions] == ["incomplete_window_end"]
    g = np.full(900, 100.0); g[MEAL:MEAL + 20] = np.nan
    assert [e["reason"] for e in build(frame(cgm=g)).exclusions] == ["leading_gap_exceeds_limit"]


def test_reading_missing_exactly_at_t0_is_not_a_problem_for_the_target():
    g = np.full(900, 100.0); g[MEAL] = np.nan; g[MEAL + 60] = 190.0
    r = row(frame(cgm=g))
    assert r["label_exceeds_180"] == 1 and r["n_window_readings"] == 120


# --------------------------------------------------------------- meal type normalisation

@pytest.mark.parametrize("raw, expected", [
    ("Breakfast", "breakfast"), (" breakfast ", "breakfast"), ("LUNCH", "lunch"), ("Dinner", "dinner"),
    ("Snack", "snack"), ("snacks", "snack"), ("Snack 1", "snack"), ("snack 2", "snack"), ("Snack1", "snack"),
    ("SNACKS  3", "snack"), ("brunch", "unrecognized"), ("", "unrecognized"), ("snackbar", "unrecognized"),
])
def test_meal_type_normalisation(raw, expected):
    assert normalize_meal_type(raw) == expected


def test_missing_meal_type_stays_missing_and_raw_label_is_preserved_in_the_table():
    assert pd.isna(normalize_meal_type(np.nan)) and pd.isna(normalize_meal_type(None))
    r = row(frame(types=["Snack 1"]))
    assert r["label_raw"] == "Snack 1" and r["label_norm"] == "snack"


def test_unrecognised_labels_are_kept_visible_in_the_report():
    tbl = {"P1": build(frame(meals=(200, 600), types=["Brunch", "Snacks"]), require_isolated=False)}
    rep = event_count_report(tbl)
    assert rep["meal_type_counts_all_meal_rows"] == {"snack": 1, "unrecognized": 1}
    assert rep["unrecognized_meal_type_raw_values"] == {"Brunch": 1}


# --------------------------------------------------------------- macros preserved, not features

def test_macros_and_amount_consumed_are_preserved_but_amount_is_not_a_feature():
    r = row(frame(amount=0.35))
    assert r["carbs_g"] == 40.0 and r["amount_consumed_raw"] == 0.35
    for c in ("protein_g", "fat_g", "fiber_g", "calories"):
        assert c in r.index                                                           # present even when the source is missing
    assert "amount_consumed_raw" in RETAINED_RAW_COLUMNS and "amount_consumed_raw" not in FEATURE_COLUMNS
    assert not set(RETAINED_RAW_COLUMNS) & set(OUTCOME_COLUMNS)
    assert not any("image" in c.lower() for c in build(frame(images={MEAL})).table.columns)


# --------------------------------------------------------------- leakage

def _mutate_from(df, cutoff, include_cutoff, cols):
    d = df.copy()
    m = (d["Timestamp"] >= cutoff) if include_cutoff else (d["Timestamp"] > cutoff)
    for c in cols:
        d.loc[m, c] = 12345.0
    return d


def _same(a, b):
    return a == b or (pd.isna(a) and pd.isna(b))


def test_activity_features_ignore_the_meal_row_itself_and_everything_after_it():
    df = frame(n=2200, meals=(1700,), mets=1.5)
    t0 = df.loc[1700, "Timestamp"]
    base = row(df)
    mutated = row(_mutate_from(df, t0, True, ["METs", "HR", "Amount Consumed"]), max_cgm_gap_minutes=10**6,
                  max_trailing_gap_minutes=10**6)                                     # includes the reading AT t0
    for c in ("activity_level", "activity_coverage", "activity_1h", "activity_1h_coverage", "activity_24h", "activity_24h_coverage"):
        assert _same(base[c], mutated[c]), c


def test_activity_features_do_respond_to_the_past_so_the_check_is_not_vacuous():
    df = frame(n=2200, meals=(1700,), mets=1.5)
    t0 = df.loc[1700, "Timestamp"]
    d = df.copy(); d.loc[(d["Timestamp"] >= t0 - pd.Timedelta(minutes=30)) & (d["Timestamp"] < t0), "METs"] = 9.0
    base, changed = row(df), row(d)
    assert changed["activity_1h"] > base["activity_1h"] and changed["activity_24h"] > base["activity_24h"]
    assert changed["activity_level"] > base["activity_level"]


def test_each_activity_window_reads_its_own_span():
    df = frame(n=2200, meals=(1700,), mets=1.5)
    t0 = df.loc[1700, "Timestamp"]
    d = df.copy(); d.loc[(d["Timestamp"] >= t0 - pd.Timedelta(hours=10)) & (d["Timestamp"] < t0 - pd.Timedelta(hours=9)), "METs"] = 9.0
    base, far = row(df), row(d)                                       # activity 9-10 h before: only the 24 h window may see it
    assert far["activity_24h"] > base["activity_24h"]
    assert far["activity_level"] == base["activity_level"] and far["activity_1h"] == base["activity_1h"]
    e = df.copy(); e.loc[(e["Timestamp"] >= t0 - pd.Timedelta(hours=3)) & (e["Timestamp"] < t0 - pd.Timedelta(hours=2)), "METs"] = 9.0
    mid = row(e)                                                       # 2-3 h before: the 4 h and 24 h windows, not the 1 h window
    assert mid["activity_level"] > base["activity_level"] and mid["activity_1h"] == base["activity_1h"]


def test_all_features_are_identical_when_everything_after_t0_changes_including_future_meals_and_labels():
    df = frame(n=2200, meals=(1700,))
    t0 = df.loc[1700, "Timestamp"]
    d = _mutate_from(df, t0, False, ["METs", "HR", "Amount Consumed", "Carbs", "Dexcom GL", "Libre GL"])
    idx = np.flatnonzero((d["Timestamp"] > t0).to_numpy())
    d.loc[idx[10], "Meal Type"] = "Brunch"; d.loc[idx[200], "Meal Type"] = "Dinner"     # invented future meals
    after = build(d, max_cgm_gap_minutes=10**6, max_trailing_gap_minutes=10**6).table
    after = after[after["meal_time"] == t0].iloc[0]
    base = row(df)
    for c in FEATURE_COLUMNS:
        assert _same(base[c], after[c]), c
    assert base["peak_glucose"] != after["peak_glucose"]                                 # the outcome does use the future, by definition


def test_features_are_computed_from_the_past_even_for_the_first_meal_of_a_file():
    r = row(frame(n=300, meals=(3,)))
    assert pd.isna(r["baseline_glucose"]) and r["activity_24h_coverage"] < 0.01 and pd.isna(r["time_since_last_meal_min"])


# --------------------------------------------------------------- report

def test_report_has_completeness_missingness_and_reconciles():
    g = np.full(900, 100.0); g[450:460] = np.nan
    a = build(frame(cgm=g))
    g2 = np.full(900, 100.0); g2[450:470] = np.nan
    b = build_event_table(frame(cgm=g2), "P2")
    rep = event_count_report({"P1": a, "P2": b})
    assert rep["reconciles"] and rep["overall"]["n_meal_rows"] == 2 and rep["overall"]["n_window_valid"] == 1
    assert rep["window_completeness_retained"]["n"] == 1
    assert rep["window_completeness_retained"]["min"] == pytest.approx(110 / 120)
    assert rep["valid_reading_share_of_excluded_windows"]["n"] == 1
    miss = rep["feature_missingness_window_valid"]
    assert set(FEATURE_COLUMNS) <= set(miss) and miss["carbs_g"]["n_missing"] == 0
    assert rep["meal_type_counts_all_meal_rows"] == {"lunch": 2} and rep["meal_type_counts_retained"] == {"lunch": 1}
