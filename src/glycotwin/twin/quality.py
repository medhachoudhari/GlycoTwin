"""Forecast-time data-quality assessment (blueprint section 19: "data quality uncertainty").

The blueprint asks for a flag, separate from the posterior width, raised when a sensor gap, a missing activity sync or a very short
meal history degrades confidence, shown as an "insufficient history" / "low data quality" badge, with the probability still shown.
What is implemented here: the FLAG and the WARNING TEXT, propagated with every forecast. What is deliberately NOT implemented: any
change to the predictive probability or interval. No validated model links these flags to forecast error (that would have to be
estimated on real data, and has not been), so widening the interval by an invented factor would be a made-up number.
`interval_adjusted` is therefore always False and says so.

Only information available WHEN THE FORECAST IS MADE is read (the baseline's age, the pre-meal activity coverage, the pre-meal trend, the
number of the person's own reconciled meals). Outcome-window quantities (window_completeness) and the future-dependent `isolated` /
`overlap_next` flags are never read here: they do not exist at forecast time. They are reported separately for a reconciled observation.

Thresholds are engineering conventions, not validated cut-offs; they are parameters and are recorded with every assessment.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

COLD_START_MAX_OBSERVATIONS = 3            # blueprint section 21: "cold-start (first 3 meals)"
EXPERIENCED_MIN_OBSERVATIONS = 10          # blueprint section 21: "experienced-twin (10+ meals)"
LOW_ACTIVITY_COVERAGE = 0.5                # share of the 4 h pre-meal window with METs readings below which activity is flagged
STALE_BASELINE_MINUTES = 30.0              # age of the baseline CGM reading above which the baseline is flagged (Libre samples every 15 min)
THRESHOLDS = {"low_activity_coverage": LOW_ACTIVITY_COVERAGE, "stale_baseline_minutes": STALE_BASELINE_MINUTES,
              "cold_start_max_observations": COLD_START_MAX_OBSERVATIONS, "status": "engineering conventions, not validated cut-offs"}
NOT_ADJUSTED_NOTE = ("The predictive probability and interval are NOT changed for data quality: no validated model of how these flags affect "
                     "forecast error exists yet. The warning is information for the reader, not a correction.")


def _num(row, key) -> Optional[float]:
    if key not in row.index:
        return None
    try:
        v = float(row[key])
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def assess_forecast_quality(meal_row: pd.Series, n_personal_observations: int) -> dict:
    reasons = []
    cov = _num(meal_row, "activity_coverage")
    if "activity_coverage" in meal_row.index and cov is None:
        reasons.append("activity coverage unknown")
    elif cov is not None and cov < LOW_ACTIVITY_COVERAGE:
        reasons.append(f"low pre-meal activity coverage ({cov:.0%} of the 4 h window)")
    if "activity_level" in meal_row.index and _num(meal_row, "activity_level") is None:
        reasons.append("pre-meal activity missing")
    age = _num(meal_row, "baseline_age_minutes")
    if age is not None and age > STALE_BASELINE_MINUTES:
        reasons.append(f"baseline glucose reading is {age:.0f} minutes old")
    if "baseline_glucose" in meal_row.index and _num(meal_row, "baseline_glucose") is None:
        reasons.append("baseline glucose missing")
    if "trend_slope_30min" in meal_row.index and _num(meal_row, "trend_slope_30min") is None:
        reasons.append("pre-meal glucose trend unavailable")
    insufficient = int(n_personal_observations) < COLD_START_MAX_OBSERVATIONS
    warnings = []
    if reasons:
        warnings.append("LOW DATA QUALITY: " + "; ".join(reasons) + ".")
    if insufficient:
        warnings.append(f"INSUFFICIENT HISTORY: only {int(n_personal_observations)} of this person's own meals have been observed "
                        f"(fewer than {COLD_START_MAX_OBSERVATIONS}); the forecast rests mainly on the population prior.")
    return {"low_data_quality": bool(reasons), "insufficient_history": bool(insufficient), "reasons": reasons,
            "n_personal_observations": int(n_personal_observations), "warnings": warnings,
            "warning": " ".join(warnings) if warnings else None,
            "interval_adjusted": False, "note": NOT_ADJUSTED_NOTE, "thresholds": THRESHOLDS}


def assess_observation_quality(window_completeness: Optional[float], data_quality_flag: Optional[str] = None) -> dict:
    """Quality of a RECONCILED outcome (known only after the window closed): how much of the 120-minute window had readings."""
    wc = None if window_completeness is None or not np.isfinite(float(window_completeness)) else float(window_completeness)
    partial = wc is not None and wc < 1.0
    return {"window_completeness": wc, "partial_window": bool(partial), "data_quality_flag": data_quality_flag,
            "note": ("The observed maximum over a partly observed window is a lower bound of the true maximum." if partial else None)}
