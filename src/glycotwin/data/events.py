"""Event table: leakage-safe features, outcomes, eligibility and event-count reports.

Built on glycotwin.data.meals. One row per meal whose outcome window passed the structural
checks; every meal that did not is in the exclusion log. Column roles are kept strictly apart:

  FEATURE_COLUMNS   may use ONLY information available when the forecast is made (data at or
                    before t0, and for CGM-derived values at or before t0 - lag). tests assert
                    these do not change when everything after t0 is mutated.
  OUTCOME_COLUMNS   use the outcome window (t0, t0 + window] by definition; never inputs.
  ELIGIBILITY       attributes used to decide which meals enter an analysis. `isolated`
                    depends on the NEXT meal, i.e. on the future: excluding meals by it is a
                    selection on future behaviour. It is legitimate for choosing evaluation
                    meals but must be reported with a sensitivity analysis (rule R7).

Nothing here decides the open scientific rules (docs/data_validity_rules.md); thresholds are
parameters with documented defaults.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from glycotwin.data.meals import (
    extract_meal_events_detailed,
    load_participant_data,
    participant_id_from_path,
)
from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL

FEATURE_COLUMNS = [
    "carbs_g", "protein_g", "fat_g", "fiber_g", "calories",
    "baseline_glucose", "baseline_age_minutes", "trend_slope_30min",
    "activity_level", "activity_coverage", "time_since_last_meal_min",
]
OUTCOME_COLUMNS = ["peak_glucose", "peak_glucose_rise", "label_exceeds_180", "n_window_readings"]
ELIGIBILITY_COLUMNS = ["overlaps_prior_window", "overlaps_next_window", "isolated",
                       "eligible_core", "eligible_activity", "ineligible_reasons", "data_quality_flag"]

REASON_BASELINE_MISSING = "baseline_missing"
REASON_CARBS_MISSING = "carbs_missing"
REASON_OVERLAP = "overlapping_meal_window"
REASON_ACTIVITY_MISSING = "activity_missing_or_low_coverage"


@dataclass
class EventTable:
    table: pd.DataFrame
    exclusions: List[Dict[str, Any]] = field(default_factory=list)
    notes: Dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- features

def pre_meal_activity(df: pd.DataFrame, t0, col: str = "METs", hours: float = 4.0, min_coverage: float = 0.5):
    """Mean of `col` over [t0 - hours, t0): STRICTLY before the meal. Coverage is the share of the
    expected one-minute rows that hold a value. Raw METs are returned; normalisation to [0, 1] must be
    fitted on training data later (the blueprint does not define it)."""
    if col not in df.columns:
        return {"mean": np.nan, "coverage": 0.0, "n_valid": 0, "usable": False}
    t0 = pd.Timestamp(t0)
    span = df[(df["Timestamp"] >= t0 - pd.Timedelta(hours=hours)) & (df["Timestamp"] < t0)]
    vals = pd.to_numeric(span[col], errors="coerce").dropna()
    coverage = len(vals) / (hours * 60.0)
    mean = float(vals.mean()) if len(vals) else np.nan
    return {"mean": mean, "coverage": float(min(coverage, 1.0)), "n_valid": int(len(vals)),
            "usable": bool(len(vals) and coverage >= min_coverage)}


def pre_meal_trend_slope(df: pd.DataFrame, t0, cgm_col: str, lag_minutes: float, minutes: float = 30.0,
                         min_points: int = 3) -> float:
    """Least-squares slope (mg/dL per minute) over valid readings in [t0 - lag - minutes, t0 - lag].
    NaN when fewer than `min_points` readings. Uses nothing after t0 - lag."""
    if cgm_col not in df.columns:
        return float("nan")
    t0 = pd.Timestamp(t0)
    end = t0 - pd.Timedelta(minutes=lag_minutes)
    span = df[(df["Timestamp"] >= end - pd.Timedelta(minutes=minutes)) & (df["Timestamp"] <= end)]
    v = pd.to_numeric(span[cgm_col], errors="coerce")
    ok = v.notna().to_numpy()
    if ok.sum() < min_points:
        return float("nan")
    x = (span["Timestamp"][ok] - end).dt.total_seconds().to_numpy() / 60.0
    return float(np.polyfit(x, v.to_numpy()[ok], 1)[0])


# ----------------------------------------------------------------------------- outcome

def compute_outcome(cgm_window: List[float], baseline: Optional[float], threshold: float = GLUCOSE_THRESHOLD_MG_DL) -> dict:
    """Peak over the outcome window (t0, t0 + window]: the reading AT t0 (window[0], the meal row) is
    excluded, matching the blueprint's open-start interval, so a high value at t0 cannot make the
    label trivially positive. label = peak >= threshold (blueprint: >= 180). rise = peak - baseline."""
    after = np.asarray(cgm_window[1:], dtype=float)
    after = after[np.isfinite(after)]
    if after.size == 0:
        return {"peak_glucose": np.nan, "peak_glucose_rise": np.nan, "label_exceeds_180": np.nan, "n_window_readings": 0}
    peak = float(after.max())
    rise = peak - baseline if baseline is not None else np.nan
    return {"peak_glucose": peak, "peak_glucose_rise": rise, "label_exceeds_180": int(peak >= threshold),
            "n_window_readings": int(after.size)}


# ----------------------------------------------------------------------------- table

def build_event_table(
    df: pd.DataFrame,
    participant_id: str,
    cgm_col: str = "Dexcom GL",
    activity_col: str = "METs",
    activity_hours: float = 4.0,
    min_activity_coverage: float = 0.5,
    require_isolated: bool = True,
    **extraction_kwargs,
) -> EventTable:
    """Build the event table for one participant. Extra kwargs go to extract_meal_events_detailed
    (gap limits, window, lag, duplicate policy)."""
    ext = extract_meal_events_detailed(df, participant_id=participant_id, cgm_col=cgm_col, **extraction_kwargs)
    sdf = df.sort_values("Timestamp", kind="stable").reset_index(drop=True)
    rows = []
    for ev in ext.events:
        t0 = ev["meal_time"]
        lag = ev["baseline_lag_minutes"]
        act = pre_meal_activity(sdf, t0, activity_col, activity_hours, min_activity_coverage)
        outcome = compute_outcome(ev["CGM_Window"], ev["baseline_glucose"])

        def macro(name):
            v = pd.to_numeric(pd.Series([ev.get(name)]), errors="coerce").iloc[0]
            return float(v) if pd.notna(v) else np.nan

        carbs = macro("Carbs")
        flags, reasons = [], []
        if ev["baseline_glucose"] is None:
            flags.append("baseline_missing"); reasons.append(REASON_BASELINE_MISSING)
        if not np.isfinite(carbs) or carbs < 0:
            flags.append("carbs_missing"); reasons.append(REASON_CARBS_MISSING)
        if ev["overlaps_prior_window"]:
            flags.append("overlap_prior")
        if ev["overlaps_next_window"]:
            flags.append("overlap_next")
        if require_isolated and not ev["isolated"]:
            reasons.append(REASON_OVERLAP)
        eligible_core = not reasons
        if not act["usable"]:
            flags.append("activity_missing")
        eligible_activity = eligible_core and act["usable"]

        rows.append({
            "participant_id": participant_id, "event_id": ev["event_id"], "meal_time": t0,
            "label_raw": ev["Original Meal Type"], "label_norm": ev["Normalized Meal Type"],
            "carbs_g": carbs, "protein_g": macro("Protein"), "fat_g": macro("Fat"), "fiber_g": macro("Fiber"),
            "calories": macro("Calories"),
            "baseline_glucose": np.nan if ev["baseline_glucose"] is None else ev["baseline_glucose"],
            "baseline_age_minutes": np.nan if ev["baseline_age_minutes"] is None else ev["baseline_age_minutes"],
            "trend_slope_30min": pre_meal_trend_slope(sdf, t0, cgm_col, lag),
            "activity_level": act["mean"], "activity_coverage": act["coverage"],
            "time_since_last_meal_min": np.nan if ev["prior_meal_gap_minutes"] is None else ev["prior_meal_gap_minutes"],
            **outcome,
            "overlaps_prior_window": ev["overlaps_prior_window"], "overlaps_next_window": ev["overlaps_next_window"],
            "isolated": ev["isolated"], "eligible_core": eligible_core, "eligible_activity": eligible_activity,
            "ineligible_reasons": ";".join(reasons + ([] if act["usable"] or not eligible_core else [REASON_ACTIVITY_MISSING])),
            "data_quality_flag": "ok" if not flags else ";".join(flags),
        })
    table = pd.DataFrame(rows)
    notes = {**ext.notes, "n_window_valid": len(rows), "cgm_channel": cgm_col}
    return EventTable(table, ext.exclusions, notes)


def build_event_table_from_csv(path: Path | str, **kwargs) -> EventTable:
    return build_event_table(load_participant_data(path), participant_id_from_path(path), **kwargs)


# ----------------------------------------------------------------------------- reports

def event_count_report(tables: Dict[str, EventTable], group_of: Optional[Dict[str, str]] = None,
                       min_per_class: int = 5, anonymize_seed: int = 0) -> dict:
    """Aggregate event counts (the blueprint's Week-1 checkpoint). Participant ids are replaced by
    seeded-random labels P1..Pn; `group_of` (participant -> glycaemic group, from bio.csv) is
    optional because that file is not ingested yet. Nothing here is a model result."""
    ids = sorted(tables)
    order = np.random.default_rng(anonymize_seed).permutation(len(ids))
    label = {pid: f"P{int(k) + 1}" for pid, k in zip(ids, order)}

    extraction_reasons, ineligible_reasons = Counter(), Counter()
    per, overall = [], Counter()
    by_group: Dict[str, Counter] = {}
    for pid in ids:
        et = tables[pid]
        t = et.table
        n_rows = et.notes.get("n_meal_rows", len(t) + len(et.exclusions))
        core = t[t["eligible_core"]] if len(t) else t
        pos = int((core["label_exceeds_180"] == 1).sum()) if len(core) else 0
        neg = int((core["label_exceeds_180"] == 0).sum()) if len(core) else 0
        extraction_reasons.update(e["reason"] for e in et.exclusions)
        for r in (t["ineligible_reasons"] if len(t) else []):
            ineligible_reasons.update(x for x in r.split(";") if x)
        rec = {"participant": label[pid], "n_meal_rows": int(n_rows), "n_excluded_at_extraction": len(et.exclusions),
               "n_window_valid": len(t), "n_isolated": int(t["isolated"].sum()) if len(t) else 0,
               "n_eligible_core": int(len(core)), "n_eligible_activity": int(t["eligible_activity"].sum()) if len(t) else 0,
               "n_positive": pos, "n_negative": neg}
        per.append(rec)
        for k in ("n_meal_rows", "n_excluded_at_extraction", "n_window_valid", "n_eligible_core", "n_eligible_activity",
                  "n_positive", "n_negative"):
            overall[k] += rec[k]
        if group_of and pid in group_of:
            g = by_group.setdefault(group_of[pid], Counter())
            g.update({k: rec[k] for k in ("n_meal_rows", "n_eligible_core", "n_positive", "n_negative")})
            g["n_participants"] += 1
    return {
        "overall": dict(overall), "n_participants": len(ids),
        "participants_with_both_classes": sum(1 for r in per if r["n_positive"] >= min_per_class and r["n_negative"] >= min_per_class),
        "min_per_class": min_per_class,
        "extraction_exclusion_reasons": dict(extraction_reasons), "ineligibility_reasons": dict(ineligible_reasons),
        "by_group": {g: dict(c) for g, c in by_group.items()}, "per_participant": sorted(per, key=lambda r: r["participant"]),
        "reconciles": overall["n_meal_rows"] == overall["n_window_valid"] + overall["n_excluded_at_extraction"],
    }
