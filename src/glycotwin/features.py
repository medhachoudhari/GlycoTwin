"""Internal meal-event schema and leakage-safe evaluation splitting.

Important: this schema is **not** derived from an inspection of real CGMacros files —
no real CGMacros data has been inspected in this repository yet. It is the internal
representation GlycoTwin's models consume, produced by a dataset-specific adapter that
is built once the real files/documentation are reviewed (see scripts/audit_dataset.py).
Treat every field name/unit below as a design decision to validate against real data,
not a fact about CGMacros.

MealEvent fields (one row per logged meal, already linked to its 2-hour outcome):
    participant_id       str   - opaque per-participant identifier
    meal_time             datetime (native/local units from the source; never assume
                                     a timezone or that it is wall-clock real time -
                                     CGMacros timestamps are privacy-shifted)
    carbs_g                float  - carbohydrate grams for the meal
    baseline_glucose      float  - glucose value at/just before meal_time (mg/dL)
    activity_level        float  - a pre-meal activity/heart-rate summary (units and
                                    exact window are a research decision, pending audit)
    peak_glucose_rise     float  - max(glucose in the 2h window) - baseline_glucose;
                                    this is the continuous target the Bayesian layer
                                    regresses on
    label_exceeds_180      int(0/1) - whether glucose exceeded 180 mg/dL in the 2h
                                       window; the classification target for Model A
    data_quality_flag     str   - e.g. "ok", "sparse_cgm_window", "missing_activity";
                                   set by the adapter, never fabricated here

Nothing in this module invents participants or values: it only operates on whatever
DataFrame it is given, and all of this module's own tests use clearly synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MEAL_EVENT_COLUMNS = [
    "participant_id",
    "meal_time",
    "carbs_g",
    "baseline_glucose",
    "activity_level",
    "peak_glucose_rise",
    "label_exceeds_180",
    "data_quality_flag",
]


OUTCOME_WINDOW = pd.Timedelta(hours=2)
GLUCOSE_THRESHOLD_MG_DL = 180.0
NUMERIC_COLUMNS = ["carbs_g", "baseline_glucose", "activity_level", "peak_glucose_rise"]


def validate_meal_events(df: pd.DataFrame) -> list[str]:
    """Return a list of schema/consistency problems (empty if none). Never raises or
    mutates, and reports counts only - never row values."""
    problems = []
    missing_cols = [c for c in MEAL_EVENT_COLUMNS if c not in df.columns]
    if missing_cols:
        problems.append(f"missing required columns: {missing_cols}")
        return problems  # can't check further without the columns
    if df["participant_id"].isna().any():
        problems.append("participant_id has null values")
    if not pd.api.types.is_datetime64_any_dtype(df["meal_time"]):
        problems.append("meal_time is not a datetime dtype")
    if not df["label_exceeds_180"].dropna().isin([0, 1]).all():
        problems.append("label_exceeds_180 contains values other than 0/1")

    numeric = {c: pd.to_numeric(df[c], errors="coerce") for c in NUMERIC_COLUMNS}
    for c, col in numeric.items():
        n_bad = int((~np.isfinite(col)).sum())
        if n_bad:
            problems.append(f"{c} has {n_bad} null/non-numeric/non-finite values")
    if (numeric["carbs_g"] < 0).any():
        problems.append("carbs_g has negative values")

    # The label must agree with the continuous target the Bayesian models regress on:
    # label == 1[baseline + peak_rise > 180]. A mismatch means the adapter used a
    # different baseline/window for the two, and Models B/C probabilities would not
    # target the same event as the label.
    usable = np.isfinite(numeric["baseline_glucose"]) & np.isfinite(numeric["peak_glucose_rise"])
    usable &= df["label_exceeds_180"].isin([0, 1])
    expected = (numeric["baseline_glucose"] + numeric["peak_glucose_rise"] > GLUCOSE_THRESHOLD_MG_DL)
    n_mismatch = int((expected[usable].astype(int) != df.loc[usable, "label_exceeds_180"].astype(int)).sum())
    if n_mismatch:
        problems.append(
            f"label_exceeds_180 disagrees with baseline_glucose + peak_glucose_rise > 180 "
            f"in {n_mismatch} rows"
        )
    return problems


@dataclass
class SplitResult:
    train_index: pd.Index
    test_index: pd.Index
    description: str
    purged_index: pd.Index = field(default_factory=lambda: pd.Index([]))


def _concat_index(parts: list[pd.Index]) -> pd.Index:
    return parts[0].append(parts[1:]) if parts else pd.Index([])


def chronological_participant_split(
    df: pd.DataFrame, test_fraction: float = 0.25, outcome_window: pd.Timedelta = OUTCOME_WINDOW
) -> SplitResult:
    """Leakage-safe per-participant chronological split.

    For each participant the most recent `test_fraction` of meals (by meal_time) is the
    test set. Training meals whose outcome window (meal_time + outcome_window) reaches
    the first test meal are PURGED (returned in `purged_index`, used for neither set):
    their labels are computed from CGM readings taken after the first test meal began,
    so they would not yet be observable when that meal is forecast.

    Participants are never mixed across time with each other: meal_time may be
    privacy-shifted per participant, so cross-participant chronology is not assumed.
    This evaluates each participant's own forecast -> observe -> reconcile sequence, not
    generalisation to unseen participants (a separate, stricter split).
    """
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1 (exclusive)")

    train_parts, test_parts, purged_parts = [], [], []
    for _pid, group in df.sort_values("meal_time", kind="stable").groupby("participant_id", sort=False):
        n = len(group)
        n_test = max(1, int(round(n * test_fraction))) if n > 1 else 0
        train_g, test_g = group.iloc[: n - n_test], group.iloc[n - n_test :]
        if len(test_g):
            overlaps = (train_g["meal_time"] + outcome_window > test_g["meal_time"].iloc[0]).to_numpy()
            purged_parts.append(train_g.index[overlaps])
            train_g = train_g[~overlaps]
        train_parts.append(train_g.index)
        test_parts.append(test_g.index)

    return SplitResult(
        train_index=_concat_index(train_parts),
        test_index=_concat_index(test_parts),
        purged_index=_concat_index(purged_parts),
        description=(
            f"per-participant chronological split: last {test_fraction:.0%} of each "
            f"participant's meals held out; training meals whose {outcome_window} outcome "
            "window reaches the first test meal are purged"
        ),
    )


def assert_no_temporal_leakage(
    df: pd.DataFrame, split: SplitResult, outcome_window: pd.Timedelta = OUTCOME_WINDOW
) -> None:
    """Raise AssertionError if train/test overlap, or if for any participant a training
    meal's outcome is not fully observed (meal_time + outcome_window) before that
    participant's first test meal."""
    if set(split.train_index) & set(split.test_index):
        raise AssertionError("train and test sets share rows")
    train_df, test_df = df.loc[split.train_index], df.loc[split.test_index]
    train_last = train_df.groupby("participant_id")["meal_time"].max()
    test_first = test_df.groupby("participant_id")["meal_time"].min()
    shared = train_last.index.intersection(test_first.index)
    violations = [pid for pid in shared if test_first[pid] < train_last[pid] + outcome_window]
    if violations:
        raise AssertionError(f"temporal leakage detected for participants: {violations}")
