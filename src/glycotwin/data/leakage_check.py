"""The blueprint's leakage unit test (section 7) as a reusable check over real pipeline code.

For a meal at t0: build the event features with the real pipeline, mutate EVERY reading, Fitbit value,
macro and meal log entry timestamped after t0 (and invent future meals), rebuild, and require every
column in FEATURE_COLUMNS to be identical. A second, stronger check mutates CGM values after
t0 - lag as well: the lag guard means readings just before the meal must not matter either.

Passing shows the feature code does not read the future in these frames. It does not prove that the
released CGM grid is free of interpolation leakage before t0 (that is what the lag guard and the
sampling-phase audit address).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from glycotwin.data.events import FEATURE_COLUMNS, build_event_table

SENTINEL = 12345.0


def _same(a, b) -> bool:
    return (a == b) or (pd.isna(a) and pd.isna(b))


def _mutate_after(df: pd.DataFrame, cutoff, cgm_cols=None) -> pd.DataFrame:
    d = df.copy()
    m = (d["Timestamp"] > cutoff).to_numpy()
    cols = [c for c in d.columns if c not in ("Timestamp", "Meal Type", "Normalized Meal Type", "Image path")
            and pd.api.types.is_numeric_dtype(d[c]) and (cgm_cols is None or c in cgm_cols)]
    for c in cols:
        d.loc[m, c] = SENTINEL
    if cgm_cols is None and "Meal Type" in d.columns:
        idx = np.flatnonzero(m & d["Meal Type"].isna().to_numpy())
        for k in (5, 50, 120):                       # invent future meals
            if len(idx) > k:
                d.loc[idx[k], "Meal Type"] = "Snack"
    return d


def check_feature_leakage(df: pd.DataFrame, participant_id: str, cgm_col: str = "Dexcom GL", meal_number: int = 0,
                          **build_kwargs) -> dict:
    """Check one meal (the `meal_number`-th window-valid event). Returns pass/fail and the failing columns."""
    base = build_event_table(df, participant_id, cgm_col=cgm_col, **build_kwargs).table
    if len(base) <= meal_number:
        return {"checked": False, "reason": "no_window_valid_event"}
    row = base.iloc[meal_number]
    t0 = row["meal_time"]
    lag_minutes = build_kwargs.get("baseline_lag_minutes")
    if lag_minutes is None:
        from glycotwin.data.meals import NATIVE_INTERVAL_MINUTES
        lag_minutes = NATIVE_INTERVAL_MINUTES.get(cgm_col, 0)

    def rebuild(mutated):
        t = build_event_table(mutated, participant_id, cgm_col=cgm_col, **build_kwargs).table
        t = t[t["meal_time"] == t0]
        return t.iloc[0] if len(t) else None

    out = {"checked": True}
    after = rebuild(_mutate_after(df, t0))
    out["blueprint_test_passed"] = after is not None
    out["blueprint_mismatched_columns"] = [] if after is None else [c for c in FEATURE_COLUMNS if not _same(row[c], after[c])]
    out["blueprint_test_passed"] = after is not None and not out["blueprint_mismatched_columns"]

    cutoff = t0 - pd.Timedelta(minutes=lag_minutes)
    strong = rebuild(_mutate_after(df, cutoff, cgm_cols={c for c in df.columns if c in ("Dexcom GL", "Libre GL")}))
    cgm_features = ["baseline_glucose", "baseline_age_minutes", "trend_slope_30min"]
    out["lag_guard_mismatched_columns"] = [] if strong is None else [c for c in cgm_features if not _same(row[c], strong[c])]
    out["lag_guard_test_passed"] = strong is not None and not out["lag_guard_mismatched_columns"]
    out["passed"] = out["blueprint_test_passed"] and out["lag_guard_test_passed"]
    return out
