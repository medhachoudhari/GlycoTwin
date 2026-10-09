"""The blueprint's formal TwinState (section 4), composed from the store plus the most recent logged meal. Read-only.

The blueprint lists nine components. The store versions only the Bayesian parameters (`personalized_parameters`); the other components
are DERIVED here, on demand, from records the store already holds, and carry an `as_of` time and an explicit `unavailable` list instead
of invented values:
  current_glucose_state   baseline glucose, its age and the 30 min pre-meal trend, as measured at the LAST LOGGED MEAL (this prototype
                          has no continuous 5-minute tick, so the state is as of that meal, not 'now').
  recent_activity_state   pre-meal 4 h mean METs (the Model C covariate), 1 h / 24 h means and coverage when present, and an
                          active/sedentary label relative to the person's own earlier meals. step_count_today: not in the event table.
  recent_hr_state         only if heart-rate columns exist in the meal row; otherwise None (the HR deviation feature is not built).
  meal_state              forecasts whose outcome window is still open as of `as_of`, and the carbohydrate in them. `carbs_on_board` is
                          None: the blueprint names it without an absorption model, and none is invented.
  uncertainty             width of the 90% credible interval of the carbohydrate sensitivity; rolling Brier score of the last
                          reconciled forecasts (the blueprint's `calibration_score_rolling`, defined here as that Brier score), None
                          until at least `MIN_ROLLING` reconciled forecasts exist.
  prediction_state        the latest forecast and whether it has been reconciled.
  historical_response_state  version, parent version, creation time and the reconciled forecast ids (the audit chain).
Research tooling; not clinically validated.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from glycotwin.features import OUTCOME_WINDOW
from glycotwin.models.activity_strata import prospective_activity_label
from glycotwin.twin.insight import GUARDRAILS, UNITS, _reference_activity, effective_sensitivity
from glycotwin.twin.state import TwinStore

MIN_ROLLING = 3          # reconciled forecasts needed before a rolling calibration score is reported
ROLLING_WINDOW = 10      # the score covers the most recent reconciled forecasts, at most this many
STATIC_PROFILE_KEYS = ["hba1c", "fasting_glucose", "fasting_insulin", "homa_ir", "lipid_panel", "bmi", "glycaemic_group", "age", "sex"]


def _val(row: pd.Series, key: str):
    if row is None or key not in row.index:
        return None
    v = row[key]
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v if not pd.isna(v) else None
    return f if np.isfinite(f) else None


def twin_state_view(store: TwinStore, participant_id: str, reference_activity: Optional[float] = None) -> Dict:
    twin = store.current_twin(participant_id)
    forecasts = sorted([f for f in store._forecasts.values() if f.participant_id == participant_id], key=lambda f: f.meal_time)
    last = forecasts[-1] if forecasts else None
    row = last.meal_row if last is not None else None
    as_of = last.meal_time if last is not None else None
    done = {o.forecast_id for o in store.reconciliation_log(participant_id)}
    unavailable: List[str] = []

    profile = {k: twin.profile.get(k) for k in STATIC_PROFILE_KEYS}
    missing_profile = [k for k, v in profile.items() if v is None]
    if missing_profile:
        unavailable.append("static_profile." + ",".join(missing_profile))

    glucose = {"last_value_mg_dl": _val(row, "baseline_glucose"), "baseline_age_minutes": _val(row, "baseline_age_minutes"),
               "trend_slope_mg_dl_per_min": _val(row, "trend_slope_30min"), "time_since_last_meal_min": _val(row, "time_since_last_meal_min"),
               "as_of": None if as_of is None else str(as_of), "basis": "the last logged meal (no continuous CGM tick in this prototype)"}
    if last is None:
        unavailable.append("current_glucose_state (no meal logged yet)")

    cur_act = _val(row, "activity_level")
    prior_acts = [_val(f.meal_row, "activity_level") for f in forecasts[:-1]]
    activity = {"rolling_mets_4h": cur_act, "coverage_4h": _val(row, "activity_coverage"), "mets_1h": _val(row, "activity_1h"),
                "mets_24h": _val(row, "activity_24h"), "step_count_today": None,
                "activity_label": prospective_activity_label([a for a in prior_acts if a is not None], cur_act) if last is not None else "unknown",
                "activity_label_rule": "relative to the median activity of this person's earlier meals (needs >= 4); unknown otherwise",
                "as_of": None if as_of is None else str(as_of)}
    unavailable.append("recent_activity_state.step_count_today (not in the event table)")

    hr_cols = {"current_hr": _val(row, "current_hr"), "hr_deviation_from_baseline": _val(row, "hr_deviation_from_resting")}
    if all(v is None for v in hr_cols.values()):
        unavailable.append("recent_hr_state (no heart-rate columns in the event table; HR deviation feature not built)")
    hr = {**hr_cols, "as_of": None if as_of is None else str(as_of)}

    open_windows = []
    if as_of is not None:
        for f in forecasts:
            close = f.meal_time + OUTCOME_WINDOW
            if f.forecast_id not in done and close > as_of:
                open_windows.append({"forecast_id": f.forecast_id, "meal_time": str(f.meal_time), "window_closes_at": str(close),
                                     "carbs_g": _val(f.meal_row, "carbs_g")})
    awaiting = [f.forecast_id for f in forecasts if f.forecast_id not in done and (as_of is None or f.meal_time + OUTCOME_WINDOW <= as_of)]
    carbs_open = float(sum(w["carbs_g"] or 0.0 for w in open_windows))
    meal_state = {"open_meal_windows": open_windows, "carbs_in_open_outcome_windows_g": carbs_open, "carbs_on_board": None,
                  "forecasts_awaiting_reconciliation": awaiting,
                  "note": "carbs_on_board is not computed: the blueprint gives no absorption model and none is invented"}
    unavailable.append("meal_state.carbs_on_board (no absorption model specified)")

    try:
        ref = _reference_activity(twin, reference_activity if reference_activity is not None else (cur_act if twin.model_c.activity_center == 0.0 else None))
    except ValueError:
        ref = None                                    # un-centred Model C with no stated reference and no activity value: report no sensitivity
    b = effective_sensitivity(twin.model_b)
    c_beta, c_gamma = twin.model_c.coefficient("carbs_g"), twin.model_c.coefficient("carbs_x_activity")
    c_ref = effective_sensitivity(twin.model_c, ref) if ref is not None else None
    if c_ref is None:
        unavailable.append("personalized_parameters.carb_sensitivity_model_c_at_reference_activity (no reference activity)")
    params = {"carb_sensitivity_model_b": {"mean": b["mean"], "variance": b["sd"] ** 2},
              "carb_sensitivity_model_c_at_reference_activity": None if c_ref is None else {"mean": c_ref["mean"], "variance": c_ref["sd"] ** 2, "reference_activity": ref},
              "beta_model_c": {"mean": c_beta[0], "variance": c_beta[1] ** 2, "note": "coefficient at activity = the model's centre; see reference-activity sensitivity"},
              "activity_interaction_coefficient": {"mean": c_gamma[0], "variance": c_gamma[1] ** 2},
              "n_meals_observed": int(twin.model_c.n_observations_used)}

    recs = sorted([(store.get_forecast(o.forecast_id), o) for o in store.reconciliation_log(participant_id)], key=lambda t: t[0].meal_time)
    recent = recs[-ROLLING_WINDOW:]
    rolling = {"window": ROLLING_WINDOW, "n_reconciled_in_window": len(recent), "definition": "Brier score of the last reconciled forecasts"}
    if len(recent) >= MIN_ROLLING:
        for name, attr in (("model_b", "model_b_forecast"), ("model_c", "model_c_forecast")):
            rolling[name] = float(np.mean([(getattr(f, attr).probability_exceeds_180 - float(o.observed_exceeds_180)) ** 2 for f, o in recent]))
    else:
        rolling["model_b"] = rolling["model_c"] = None
        rolling["unavailable_because"] = f"fewer than {MIN_ROLLING} reconciled forecasts"
        unavailable.append("uncertainty.calibration_score_rolling (too few reconciled forecasts)")
    uncertainty = {"posterior_band_width_90": {"model_b": 2 * 1.6448536269514722 * b["sd"], "model_c_at_reference_activity": None if c_ref is None else 2 * 1.6448536269514722 * c_ref["sd"],
                                               "unit": UNITS["carb_sensitivity"]},
                   "calibration_score_rolling": rolling}

    prediction = {"last_forecast_id": None if last is None else last.forecast_id}
    if last is not None:
        prediction.update({"model_b_probability": last.model_b_forecast.probability_exceeds_180, "model_c_probability": last.model_c_forecast.probability_exceeds_180,
                           "model_b_interval90_rise_mg_dl": [float(x) for x in last.model_b_forecast.interval_90],
                           "model_c_interval90_rise_mg_dl": [float(x) for x in last.model_c_forecast.interval_90],
                           "horizon_minutes": OUTCOME_WINDOW.total_seconds() / 60.0, "reconciled": last.forecast_id in done,
                           "data_quality": last.data_quality, "twin_version_at_forecast": last.twin_version_at_forecast})
    history = {"version_number": twin.version, "parent_version_id": twin.parent_version, "created_at": twin.created_at.isoformat(),
               "reconciliation_log_ref": [o.forecast_id for o in store.reconciliation_log(participant_id)]}
    return {"kind": "TWIN STATE VIEW (derived; research prototype)", "participant_label": participant_id, "as_of": None if as_of is None else str(as_of),
            "static_profile": profile, "current_glucose_state": glucose, "recent_activity_state": activity, "recent_hr_state": hr,
            "meal_state": meal_state, "personalized_parameters": params, "uncertainty": uncertainty, "prediction_state": prediction,
            "historical_response_state": history, "unavailable": unavailable, "guardrails": GUARDRAILS}
