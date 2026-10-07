"""
Data loading and meal event extraction module.

Limitations:
- Native versus interpolated Dexcom observations cannot currently be distinguished
  from the available data and documentation. The extracted CGM windows preserve
  all 1-minute interpolated values (including missing data/NaNs) without any
  attempted resampling or downsampling.

Rules implemented here (see docs/data_validity_rules.md; open questions stay open there):
- D1 window anchor (LOCKED for the primary analysis, decision D9): t0 is the `Meal Type` row timestamp. It is NOT
  called meal_end and nothing here pairs photos or assumes a meal duration. The outcome window is (t0, t0 + 120 min].
  Whether t0 is a true meal start is NOT verified (rule R1).
- Gaps are measured on VALID readings over the whole window, including the gap between t0 and
  the first valid reading (leading) and between the last valid reading and the window end
  (trailing), not only between readings (the pre-reconciliation code missed the leading gap).
- Every meal that cannot yield an outcome window is returned in `exclusions` with a reason;
  nothing is dropped silently.
- Overlapping meals are FLAGGED here (policy about them is applied downstream).
- The baseline uses only readings at or before t0 - lag, where the lag defaults to the channel's
  documented native interval (a conservative guard; the documented intervals are
  blueprint-reported and unverified).
"""
import re

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Blueprint-reported native sampling intervals (minutes). Unverified; used only as a
# conservative default lag for the baseline guard.
NATIVE_INTERVAL_MINUTES = {"Dexcom GL": 5, "Libre GL": 15}

MACRO_COLS = ["Calories", "Carbs", "Protein", "Fat", "Fiber"]
# Preserved verbatim for audit, NEVER a model feature: it may be recorded after eating (rule D7). Image path is never kept.
RETAINED_RAW_COLS = {"Amount Consumed": "amount_consumed_raw"}

CANONICAL_MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
UNRECOGNIZED_MEAL_TYPE = "unrecognized"


def normalize_meal_type(value):
    """Canonical meal type: breakfast, lunch, dinner, or snack (also 'snacks', 'snack 1', 'Snack2').
    Missing -> NaN. Anything else -> 'unrecognized' (kept visible and counted, never guessed)."""
    if pd.isna(value):
        return np.nan
    s = re.sub(r"\s+", " ", str(value).strip().lower())
    if s in ("breakfast", "lunch", "dinner"):
        return s
    if re.fullmatch(r"snacks?( ?\d+)?", s):
        return "snack"
    return UNRECOGNIZED_MEAL_TYPE

REASON_INVALID_TIME = "invalid_meal_timestamp"
REASON_CHANNEL_MISSING = "cgm_channel_missing"
REASON_TOO_FEW = "too_few_readings"
REASON_LEADING_GAP = "leading_gap_exceeds_limit"
REASON_INTERNAL_GAP = "internal_gap_exceeds_limit"
REASON_TRAILING = "incomplete_window_end"
EXCLUSION_REASONS = (REASON_INVALID_TIME, REASON_CHANNEL_MISSING, REASON_TOO_FEW,
                     REASON_LEADING_GAP, REASON_INTERNAL_GAP, REASON_TRAILING)


@dataclass
class MealExtraction:
    """Result of extracting one participant file: events kept, meals excluded (with reasons),
    and file-level notes. Counts reconcile: n_meal_rows == len(events) + len(exclusions)."""
    events: List[Dict[str, Any]] = field(default_factory=list)
    exclusions: List[Dict[str, Any]] = field(default_factory=list)
    notes: Dict[str, Any] = field(default_factory=dict)


def participant_id_from_path(filepath: Path | str) -> str:
    """Pseudonymous id taken from the file stem. Keep it in memory; never write it to a public report."""
    return Path(filepath).stem


def load_participant_data(filepath: Path | str) -> pd.DataFrame:
    """Load a participant CSV and normalize columns and meal labels."""
    df = pd.read_csv(filepath)
    # Strip whitespace from column names
    df.columns = [c.strip() for c in df.columns]
    
    if 'Timestamp' in df.columns:
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce')
    
    # Normalize meal labels while preserving the original
    if 'Meal Type' in df.columns:
        # Create a normalized version
        # Some values might be NaN, so we handle that
        df['Normalized Meal Type'] = df['Meal Type'].map(normalize_meal_type).astype('object')
        
    return df

def extract_meal_events_detailed(
    df: pd.DataFrame,
    participant_id: str = "unknown",
    cgm_col: str = "Dexcom GL",
    max_cgm_gap_minutes: float = 15,
    window_minutes: int = 120,
    max_trailing_gap_minutes: float = 5,
    overlap_minutes: Optional[float] = None,
    baseline_lag_minutes: Optional[float] = None,
    baseline_max_extra_age_minutes: float = 15,
    on_duplicate_timestamps: str = "raise",
) -> MealExtraction:
    """Extract meal events with quality facts, overlap flags, a past-only baseline, and an
    exclusion log. Returns kept events and excluded meals; nothing is silently dropped.

    max_cgm_gap_minutes      largest allowed leading or internal gap between valid readings
                             (15 reproduces the previous behaviour; the blueprint says 30: open
                             rule R6 in docs/data_validity_rules.md).
    max_trailing_gap_minutes the last valid reading must be within this of the window end
                             (5 == the previous "window spans >= 115 min" rule).
    overlap_minutes          another logged meal this close before/after is flagged
                             (default: window_minutes).
    baseline_lag_minutes     baseline uses readings at or before t0 - lag; default is the
                             channel's documented native interval (conservative guard).
    on_duplicate_timestamps  'raise' (default, as before) or 'keep_first' (drop later duplicates
                             and record how many in notes).
    """
    if on_duplicate_timestamps not in ("raise", "keep_first"):
        raise ValueError("on_duplicate_timestamps must be 'raise' or 'keep_first'")
    result = MealExtraction()
    if df.empty or "Timestamp" not in df.columns or "Meal Type" not in df.columns:
        return result
    overlap = float(window_minutes if overlap_minutes is None else overlap_minutes)
    lag = float(NATIVE_INTERVAL_MINUTES.get(cgm_col, 0) if baseline_lag_minutes is None else baseline_lag_minutes)

    df = df.sort_values("Timestamp", kind="stable").reset_index(drop=True)
    timed = df[df["Timestamp"].notna()]
    if timed["Timestamp"].duplicated().any():
        if on_duplicate_timestamps == "raise":
            raise ValueError("Data contains duplicate or non-monotonic timestamps.")
        n_before = len(df)
        keep = ~(df["Timestamp"].notna() & df["Timestamp"].duplicated(keep="first"))
        df = df[keep].reset_index(drop=True)
        result.notes["duplicate_timestamp_rows_dropped"] = int(n_before - len(df))

    times = df["Timestamp"].to_numpy()
    has_channel = cgm_col in df.columns
    values = pd.to_numeric(df[cgm_col], errors="coerce").to_numpy(dtype=float) if has_channel else None
    if not has_channel:
        result.notes["cgm_channel_missing_from_file"] = cgm_col

    meal_idx = np.flatnonzero(df["Meal Type"].notna().to_numpy())
    valid_meal_times = [times[i] for i in meal_idx if not pd.isna(times[i])]
    one_min = np.timedelta64(1, "m")
    window_td = np.timedelta64(int(window_minutes), "m")

    ordinal = 0
    for i in meal_idx:
        row = df.iloc[i]
        t0 = times[i]
        event_id = f"{participant_id}-m{ordinal:03d}"
        ordinal += 1
        base_rec = {"participant_id": participant_id, "event_id": event_id,
                    "label_raw": row["Meal Type"], "label_norm": normalize_meal_type(row["Meal Type"])}

        if pd.isna(t0):
            result.exclusions.append({**base_rec, "reason": REASON_INVALID_TIME, "reasons": [REASON_INVALID_TIME], "detail": {}})
            continue
        if not has_channel:
            result.exclusions.append({**base_rec, "reason": REASON_CHANNEL_MISSING, "reasons": [REASON_CHANNEL_MISSING],
                                      "detail": {"channel": cgm_col}})
            continue

        lo = int(np.searchsorted(times, t0, side="left"))
        hi = int(np.searchsorted(times, t0 + window_td, side="right"))
        w_times, w_vals = times[lo:hi], values[lo:hi]
        ok = np.isfinite(w_vals)
        vt = w_times[ok]

        reasons, detail = [], {"n_valid_readings": int(ok.sum())}
        if vt.size < 2:
            reasons.append(REASON_TOO_FEW)
            leading = internal = trailing = None
        else:
            leading = float((vt[0] - t0) / one_min)
            internal = float(np.max(np.diff(vt)) / one_min)
            trailing = float((t0 + window_td - vt[-1]) / one_min)
            detail.update(leading_gap_minutes=leading, max_internal_gap_minutes=internal, trailing_gap_minutes=trailing)
            if leading > max_cgm_gap_minutes:
                reasons.append(REASON_LEADING_GAP)
            if internal > max_cgm_gap_minutes:
                reasons.append(REASON_INTERNAL_GAP)
            if trailing > max_trailing_gap_minutes:
                reasons.append(REASON_TRAILING)
        if reasons:
            result.exclusions.append({**base_rec, "reason": reasons[0], "reasons": reasons, "detail": detail})
            continue

        # past-only baseline: latest valid reading at or before t0 - lag
        cutoff = t0 - np.timedelta64(int(round(lag * 60)), "s")
        b_hi = int(np.searchsorted(times, cutoff, side="right"))
        past_ok = np.flatnonzero(np.isfinite(values[:b_hi]))
        baseline = baseline_age = None
        if past_ok.size:
            j = past_ok[-1]
            age = float((t0 - times[j]) / one_min)
            if age <= lag + baseline_max_extra_age_minutes:
                baseline, baseline_age = float(values[j]), age

        pos = valid_meal_times.index(t0)
        prior_gap = float((t0 - valid_meal_times[pos - 1]) / one_min) if pos > 0 else None
        next_gap = float((valid_meal_times[pos + 1] - t0) / one_min) if pos + 1 < len(valid_meal_times) else None
        overlaps_prior = prior_gap is not None and prior_gap < overlap
        overlaps_next = next_gap is not None and next_gap < overlap

        event = {
            "Timestamp": pd.Timestamp(t0),
            "Original Meal Type": row["Meal Type"],
            "Normalized Meal Type": normalize_meal_type(row["Meal Type"]),   # single source of truth, even for frames not built by load_participant_data
        }
        for mc in MACRO_COLS:
            event[mc] = row[mc] if mc in row else np.nan
        for raw, kept in RETAINED_RAW_COLS.items():
            event[kept] = row[raw] if raw in row else np.nan
        event["CGM_Window"] = w_vals.tolist()
        event.update(
            participant_id=participant_id, event_id=event_id, meal_time=pd.Timestamp(t0), cgm_channel=cgm_col,
            baseline_glucose=baseline, baseline_age_minutes=baseline_age, baseline_lag_minutes=lag,
            n_valid_readings=detail["n_valid_readings"], leading_gap_minutes=leading,
            max_internal_gap_minutes=internal, trailing_gap_minutes=trailing,
            prior_meal_gap_minutes=prior_gap, next_meal_gap_minutes=next_gap,
            overlaps_prior_window=overlaps_prior, overlaps_next_window=overlaps_next,
            isolated=not (overlaps_prior or overlaps_next),
        )
        result.events.append(event)

    result.notes["n_meal_rows"] = int(len(meal_idx))
    return result


def extract_meal_events(
    df: pd.DataFrame,
    max_cgm_gap_minutes: int = 15,
    cgm_col: str = 'Dexcom GL'
) -> List[Dict[str, Any]]:
    """
    Extract meal events with timestamps and available macronutrients,
    along with the 2-hour post-meal CGM window.

    Validates timestamp ordering, duplicates, CGM gaps (leading, internal and trailing), and
    window completeness. Does not include 'Amount Consumed' as a feature.

    Backward-compatible wrapper over extract_meal_events_detailed that returns only the kept
    events; use the detailed function to also get the exclusion log.
    """
    return extract_meal_events_detailed(
        df, cgm_col=cgm_col, max_cgm_gap_minutes=max_cgm_gap_minutes
    ).events
