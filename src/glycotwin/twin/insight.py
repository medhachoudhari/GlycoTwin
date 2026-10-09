"""Twin insight, parameter evolution and what-if scenarios, on top of the existing in-memory twin (no database, no web framework).

Everything here is READ-ONLY with respect to the twin: nothing in this module updates a posterior, saves a forecast or touches a store.

Definitions (both Model B and Model C use the existing `BayesianLinearState`):
  effective carbohydrate sensitivity at activity a   s(a) = beta + gamma * (a - center)      [mg/dL of peak rise per gram]
      Model C blueprint form: center = 0 (un-centred), so s(a) = beta + gamma * a;  Model B: s = beta (activity is never used).
      Posterior of s(a) is Normal with mean w.mu and variance w' Sigma w, w = (1, a - center) on (beta, gamma): the beta-gamma
      covariance is included. The raw `carbs_g` coefficient of an un-centred Model C is the sensitivity at activity 0, which may be
      outside the observed activity range, so it is reported as a coefficient, never as "the" sensitivity.
  what-if scenarios are HYPOTHETICAL inputs to the current posterior-predictive distribution; they are not observations and are
  never stored as forecasts (so they cannot be reconciled or learned from).
Research tooling; not clinically validated; no medical advice.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from glycotwin.models.bayesian import BayesianLinearState, forecast_exceeds_180
from glycotwin.twin.state import TwinState, TwinStore

Z90 = 1.6448536269514722
UNITS = {"carb_sensitivity": "mg/dL of peak glucose rise per gram of carbohydrate",
         "activity_interaction": "mg/dL per gram per unit of the pre-meal activity feature (gamma)",
         "rise": "mg/dL above the pre-meal baseline"}
GUARDRAILS = [
    "Research prototype; not clinically validated; gives no diagnosis, treatment or dosing advice.",
    "Posterior intervals are 90% credible intervals under the model's Gaussian assumptions; an interval excluding 0 is not a significance test.",
    "The activity interaction (gamma) may be weakly identified and correlated with beta (see docs/model_b_vs_c_report.md); do not read an individual's gamma as an established physiological or causal fact.",
]


def _interval(mean: float, sd: float) -> List[float]:
    return [float(mean - Z90 * sd), float(mean + Z90 * sd)]


def _coef(state: BayesianLinearState, name: str) -> dict:
    m, sd = state.coefficient(name)
    return {"mean": m, "sd": sd, "interval90": _interval(m, sd)}


def effective_sensitivity(state: BayesianLinearState, activity: Optional[float] = None) -> dict:
    """Posterior of beta + gamma*(activity - center) (Model C) or beta (Model B), with the beta-gamma covariance included."""
    i = state.feature_names.index("carbs_g")
    if "carbs_x_activity" not in state.feature_names:
        m, sd = float(state.mean[i]), float(np.sqrt(state.covariance[i, i]))
        return {"mean": m, "sd": sd, "interval90": _interval(m, sd), "activity": None}
    if activity is None or not np.isfinite(activity):
        raise ValueError("a finite activity value is required for an activity-conditioned sensitivity")
    j = state.feature_names.index("carbs_x_activity")
    w = np.zeros(len(state.feature_names))
    w[i], w[j] = 1.0, float(activity) - state.activity_center
    m, sd = float(w @ state.mean), float(np.sqrt(w @ state.covariance @ w))
    return {"mean": m, "sd": sd, "interval90": _interval(m, sd), "activity": float(activity)}


def _reference_activity(twin: TwinState, reference_activity: Optional[float]) -> float:
    if reference_activity is not None:
        return float(reference_activity)
    if twin.model_c.activity_center != 0.0:
        return float(twin.model_c.activity_center)            # legacy centred form: its own reference level
    raise ValueError("reference_activity is required: the un-centred Model C coefficient beta is the sensitivity at activity 0, "
                     "so state the activity level at which the sensitivity should be reported")


def _model_c_block(state: BayesianLinearState, ref: float) -> dict:
    ib, ig = state.feature_names.index("carbs_g"), state.feature_names.index("carbs_x_activity")
    sd_b, sd_g = np.sqrt(state.covariance[ib, ib]), np.sqrt(state.covariance[ig, ig])
    gamma = _coef(state, "carbs_x_activity")
    return {
        "beta_carb_sensitivity": {**_coef(state, "carbs_g"), "meaning": "sensitivity at activity = center (center = 0 for the blueprint form)"},
        "gamma_activity_interaction": {**gamma, "interval90_excludes_zero": bool(gamma["interval90"][0] > 0 or gamma["interval90"][1] < 0)},
        "activity_center": float(state.activity_center),
        "sensitivity_at_reference_activity": {**effective_sensitivity(state, ref), "reference_activity": float(ref)},
        "beta_gamma_posterior_correlation": float(state.covariance[ib, ig] / (sd_b * sd_g)),
        "n_observations_used": int(state.n_observations_used), "prior_source": state.prior_source,
    }


def twin_insight(store: TwinStore, participant_id: str, reference_activity: Optional[float] = None) -> dict:
    """What the twin currently believes about this participant, with uncertainty and the version it belongs to."""
    twin = store.current_twin(participant_id)
    ref = _reference_activity(twin, reference_activity)
    b = effective_sensitivity(twin.model_b)
    c = _model_c_block(twin.model_c, ref)
    return {
        "participant_label": participant_id, "twin_version": twin.version, "created_at": twin.created_at.isoformat(),
        "units": UNITS, "n_reconciled_observations": len(store.reconciliation_log(participant_id)),
        "model_b": {"carb_sensitivity": b, "n_observations_used": int(twin.model_b.n_observations_used), "prior_source": twin.model_b.prior_source},
        "model_c": c,
        "noise_sd_mg_dl": {"model_b": float(np.sqrt(twin.model_b.noise_variance)), "model_c": float(np.sqrt(twin.model_c.noise_variance))},
        "difference_c_minus_b_at_reference_activity": {"mean": c["sensitivity_at_reference_activity"]["mean"] - b["mean"]},
        "guardrails": GUARDRAILS,
    }


def parameter_history(store: TwinStore, participant_id: str, reference_activity: Optional[float] = None) -> dict:
    """Posterior parameters at every stored twin version, with the observation that produced each new version."""
    history = store.twin_history(participant_id)
    if not history:
        raise KeyError(f"no twin history for participant {participant_id!r}")
    ref = _reference_activity(history[-1], reference_activity)
    by_version = {o.twin_version_after_update: o for o in store.reconciliation_log(participant_id)}
    rows, prev = [], None
    for tw in history:
        b = effective_sensitivity(tw.model_b)
        c = _model_c_block(tw.model_c, ref)
        row = {"version": tw.version, "created_at": tw.created_at.isoformat(), "n_observations_model_b": int(tw.model_b.n_observations_used),
               "n_observations_model_c": int(tw.model_c.n_observations_used),
               "b_sensitivity_mean": b["mean"], "b_sensitivity_sd": b["sd"],
               "c_beta_mean": c["beta_carb_sensitivity"]["mean"], "c_beta_sd": c["beta_carb_sensitivity"]["sd"],
               "c_gamma_mean": c["gamma_activity_interaction"]["mean"], "c_gamma_sd": c["gamma_activity_interaction"]["sd"],
               "c_sensitivity_at_reference_mean": c["sensitivity_at_reference_activity"]["mean"],
               "c_sensitivity_at_reference_sd": c["sensitivity_at_reference_activity"]["sd"],
               "triggering_observation": None}
        o = by_version.get(tw.version)
        if o is not None:
            row["triggering_observation"] = {"forecast_id": o.forecast_id, "observed_peak_rise": o.observed_peak_rise,
                                             "observed_exceeds_180": bool(o.observed_exceeds_180), "kind": "OBSERVED (reconciled)"}
        if prev is not None:
            row["change_since_previous_version"] = {k: row[k] - prev[k] for k in ("b_sensitivity_mean", "c_beta_mean", "c_gamma_mean",
                                                                                  "c_sensitivity_at_reference_mean")}
            row["sd_ratio_to_previous_version"] = {k: (row[k] / prev[k] if prev[k] > 0 else None) for k in ("b_sensitivity_sd", "c_beta_sd", "c_gamma_sd")}
        rows.append(row)
        prev = row
    first, last = rows[0], rows[-1]
    return {"participant_label": participant_id, "reference_activity": ref, "units": UNITS, "versions": rows,
            "summary": {"n_versions": len(rows), "first_version": first["version"], "last_version": last["version"],
                        "prior_to_current_change": {k: last[k] - first[k] for k in ("b_sensitivity_mean", "c_beta_mean", "c_gamma_mean",
                                                                                     "c_sensitivity_at_reference_mean")},
                        "current_over_prior_sd": {k: (last[k] / first[k] if first[k] > 0 else None) for k in ("b_sensitivity_sd", "c_beta_sd", "c_gamma_sd")}}}


def _validate_scenario(sc: dict, default_baseline: Optional[float]) -> dict:
    label = str(sc.get("label", "unnamed scenario"))
    carbs, act = sc.get("carbs_g"), sc.get("activity_level")
    base = sc.get("baseline_glucose", default_baseline)
    for name, v in (("carbs_g", carbs), ("activity_level", act), ("baseline_glucose", base)):
        if v is None or not np.isfinite(float(v)):
            raise ValueError(f"scenario {label!r}: {name} must be a finite number")
    if float(carbs) < 0:
        raise ValueError(f"scenario {label!r}: carbs_g must not be negative")
    return {"label": label, "carbs_g": float(carbs), "activity_level": float(act), "baseline_glucose": float(base)}


def _extrapolation_warnings(v: dict, reference_ranges: Optional[Dict[str, tuple]]) -> List[str]:
    if not reference_ranges:
        return []
    out = []
    for key in ("carbs_g", "activity_level", "baseline_glucose"):
        if key in reference_ranges:
            lo, hi = reference_ranges[key]
            if v[key] < lo or v[key] > hi:
                out.append(f"{key}={v[key]:g} is outside the supplied reference range [{lo:g}, {hi:g}]: this scenario extrapolates beyond the data the twin has seen")
    return out


def what_if(twin: TwinState, scenarios: List[dict], baseline_glucose: Optional[float] = None,
            reference_ranges: Optional[Dict[str, tuple]] = None) -> dict:
    """Posterior-predictive distribution of the peak rise and P(peak >= 180) under HYPOTHETICAL scenarios, for Model B and Model C,
    from the twin's current posterior. Pure: the twin, the store and every record are untouched. The first scenario is the
    reference for the reported differences. `reference_ranges` ({"carbs_g": (lo, hi), ...}, typically the range of the participant's
    or the population's observed values) lets the function flag scenarios that extrapolate."""
    if not scenarios:
        raise ValueError("at least one scenario is required")
    out, ref = [], None
    for sc in scenarios:
        v = _validate_scenario(sc, baseline_glucose)
        row = pd.Series({"carbs_g": v["carbs_g"], "activity_level": v["activity_level"]})
        res = {}
        for name, state in (("model_b", twin.model_b), ("model_c", twin.model_c)):
            f = forecast_exceeds_180(state, row, v["baseline_glucose"])
            res[name] = {"distribution": {"family": "normal", "mean_rise_mg_dl": f.mean_rise, "sd_mg_dl": f.predictive_std,
                                          "interval90_mg_dl": [float(f.interval_90[0]), float(f.interval_90[1])]},
                         "p_peak_at_least_180": f.probability_exceeds_180}
        entry = {"kind": "HYPOTHETICAL (what-if), not observed data", "scenario": v, "twin_version_used": twin.version, **res,
                 "extrapolation_check": ("performed against the supplied reference ranges" if reference_ranges
                                         else "NOT performed: no reference ranges were supplied, so out-of-range scenarios are not flagged"),
                 "extrapolation_warnings": _extrapolation_warnings(v, reference_ranges)}
        if ref is None:
            ref = entry
        else:
            entry["difference_from_first_scenario"] = {
                m: {"mean_rise_mg_dl": entry[m]["distribution"]["mean_rise_mg_dl"] - ref[m]["distribution"]["mean_rise_mg_dl"],
                    "p_peak_at_least_180": entry[m]["p_peak_at_least_180"] - ref[m]["p_peak_at_least_180"]} for m in ("model_b", "model_c")}
        out.append(entry)
    return {"label": "WHAT-IF SIMULATION: hypothetical scenarios evaluated on the current posterior; nothing here was observed, stored or learned from",
            "screen_label": WHAT_IF_SCREEN_LABEL, "twin_version_used": twin.version, "scenarios": out, "guardrails": GUARDRAILS}


WHAT_IF_SCREEN_LABEL = ("This is a research simulation based on this patient's learned model. It is not a diet prescription, "
                        "treatment recommendation, or insulin dosing suggestion.")


def what_if_side_by_side(twin: TwinState, current: dict, scenario: dict, baseline_glucose: Optional[float] = None,
                         reference_ranges: Optional[Dict[str, tuple]] = None) -> dict:
    """Blueprint Part 20: the current meal and one alternative scenario side by side, with the probability difference and the difference in
    the estimated rise. Same posterior-predictive computation as `what_if` (pure, nothing stored or learned)."""
    both = what_if(twin, [current, scenario], baseline_glucose, reference_ranges)
    cur, sc = both["scenarios"]
    return {"screen_label": WHAT_IF_SCREEN_LABEL, "label": both["label"], "twin_version_used": twin.version, "current": cur, "scenario": sc,
            "difference_scenario_minus_current": sc["difference_from_first_scenario"], "guardrails": GUARDRAILS}


# ----------------------------------------------------------------------------- reconciliation view (forecast versus what was observed)

def reconciliation_report(store: TwinStore, participant_id: str) -> dict:
    """Forecast-versus-observed record for every forecast of this participant: what each model predicted BEFORE the outcome, what was
    then observed, whether the observation fell inside the 90% predictive interval, and the standardised surprise. Pending forecasts
    (outcome not yet reconciled) are listed separately and carry no outcome. Read-only."""
    store.current_twin(participant_id)
    done, rows = {o.forecast_id: o for o in store.reconciliation_log(participant_id)}, []
    for fid, o in done.items():
        f = store.get_forecast(fid)
        row = {"forecast_id": fid, "meal_time": str(f.meal_time), "twin_version_at_forecast": f.twin_version_at_forecast,
               "twin_version_after_update": o.twin_version_after_update,
               "observed": {"peak_rise_mg_dl": o.observed_peak_rise, "peak_at_least_180": bool(o.observed_exceeds_180), "kind": "OBSERVED (reconciled)"}}
        for name, fc in (("model_b", f.model_b_forecast), ("model_c", f.model_c_forecast)):
            sd = fc.predictive_std
            p_obs = fc.probability_exceeds_180 if o.observed_exceeds_180 else 1.0 - fc.probability_exceeds_180
            row[name] = {"forecast_p_peak_at_least_180": fc.probability_exceeds_180, "forecast_mean_rise_mg_dl": fc.mean_rise, "forecast_sd_mg_dl": sd,
                         "forecast_interval90_mg_dl": [float(fc.interval_90[0]), float(fc.interval_90[1])],
                         "observed_inside_interval90": bool(fc.interval_90[0] <= o.observed_peak_rise <= fc.interval_90[1]),
                         "standardised_error": float((o.observed_peak_rise - fc.mean_rise) / sd),
                         "probability_given_to_what_happened": float(p_obs), "brier_component": float((fc.probability_exceeds_180 - float(o.observed_exceeds_180)) ** 2)}
        rows.append(row)
    rows.sort(key=lambda r: r["twin_version_after_update"] or 0)
    summ = {"n_reconciled": len(rows), "n_pending": len(store.pending_forecasts(participant_id))}
    for name in ("model_b", "model_c"):
        if rows:
            summ[name] = {"share_observed_inside_interval90": float(np.mean([r[name]["observed_inside_interval90"] for r in rows])),
                          "mean_standardised_error": float(np.mean([r[name]["standardised_error"] for r in rows])),
                          "mean_brier": float(np.mean([r[name]["brier_component"] for r in rows]))}
    pending = [{"forecast_id": f.forecast_id, "meal_time": str(f.meal_time), "twin_version_at_forecast": f.twin_version_at_forecast,
                "status": "PENDING: outcome not yet observed"} for f in store.pending_forecasts(participant_id)]
    return {"participant_label": participant_id, "reconciled": rows, "pending": pending, "summary": summ,
            "note": "A handful of forecasts per person cannot assess calibration; the summary is descriptive only.", "guardrails": GUARDRAILS}


# ----------------------------------------------------------------------------- explanation of one forecast (decomposition, not causation)

def explain_forecast(twin: TwinState, meal: Dict[str, float], model: str = "model_c") -> dict:
    """Decompose a posterior-predictive forecast into its parts: the contribution of each regression term to the predicted rise (with
    its own uncertainty), the split of the predictive variance between parameter uncertainty and residual noise, and the threshold
    arithmetic behind P(peak >= 180). `meal` needs carbs_g, activity_level and baseline_glucose. Read-only. This describes how the
    MODEL arrives at its forecast; it is not a causal statement about the person."""
    if model not in ("model_b", "model_c"):
        raise ValueError("model must be 'model_b' or 'model_c'")
    c, a, b = meal.get("carbs_g"), meal.get("activity_level"), meal.get("baseline_glucose")
    for name, v in (("carbs_g", c), ("activity_level", a), ("baseline_glucose", b)):
        if v is None or not np.isfinite(float(v)):
            raise ValueError(f"{name} must be a finite number")
    if float(c) < 0:
        raise ValueError("carbs_g must not be negative")
    state = twin.model_b if model == "model_b" else twin.model_c
    from glycotwin.models.bayesian import build_design_matrix
    x = build_design_matrix(pd.DataFrame({"carbs_g": [float(c)], "activity_level": [float(a)]}), state.feature_names, state.activity_center)[0]
    terms = {}
    for j, name in enumerate(state.feature_names):
        mean, sd = float(x[j] * state.mean[j]), float(abs(x[j]) * np.sqrt(state.covariance[j, j]))
        terms[name] = {"design_value": float(x[j]), "coefficient_mean": float(state.mean[j]), "contribution_mg_dl": mean, "contribution_sd_mg_dl": sd,
                       "contribution_interval90_mg_dl": _interval(mean, sd)}
    mean_rise = float(x @ state.mean)
    param_var, noise_var = float(x @ state.covariance @ x), float(state.noise_variance)
    pred_sd = float(np.sqrt(noise_var + param_var))
    margin = float(b) + mean_rise - 180.0
    f = forecast_exceeds_180(state, pd.Series({"carbs_g": float(c), "activity_level": float(a)}), float(b))
    lines = [f"{model} expects a peak rise of {mean_rise:.0f} mg/dL (sd {pred_sd:.0f}) for {float(c):g} g carbohydrate at activity {float(a):g}."]
    if "carbs_x_activity" in terms:
        act = terms["carbs_x_activity"]
        lines.append(f"Of this, the carbohydrate term contributes {terms['carbs_g']['contribution_mg_dl']:.0f} mg/dL and the activity term "
                     f"{act['contribution_mg_dl']:+.0f} mg/dL (marginal sd {act['contribution_sd_mg_dl']:.0f}).")
    lines.append(f"The expected peak is {float(b) + mean_rise:.0f} mg/dL ({margin:+.0f} mg/dL relative to 180); with a predictive sd of {pred_sd:.0f} "
                 f"that gives P(peak >= 180) = {f.probability_exceeds_180:.2f}.")
    lines.append(f"{100 * param_var / (param_var + noise_var):.0f}% of the predictive variance is uncertainty about this person's parameters "
                 f"(it shrinks with more observations); the rest is meal-to-meal noise that more data cannot remove.")
    return {"kind": "MODEL EXPLANATION (decomposition of a posterior-predictive forecast); not a causal claim", "model": model, "twin_version": twin.version,
            "inputs": {"carbs_g": float(c), "activity_level": float(a), "baseline_glucose": float(b)},
            "terms": terms, "predicted_rise_mg_dl": mean_rise,
            "variance": {"parameter_uncertainty": param_var, "residual_noise": noise_var, "share_parameter_uncertainty": param_var / (param_var + noise_var)},
            "predictive_sd_mg_dl": pred_sd, "expected_peak_mg_dl": float(b) + mean_rise, "margin_to_180_mg_dl": margin,
            "p_peak_at_least_180": f.probability_exceeds_180, "plain_language": lines, "guardrails": GUARDRAILS}


# ----------------------------------------------------------------------------- patient-list view

def store_overview(store: TwinStore, reference_activity: Optional[float] = None) -> dict:
    """One row per twin in the store (the data behind a patient list / overview): version, reconciled and pending counts, and the current
    sensitivities with uncertainty. Model C's sensitivity at a stated activity is included only when `reference_activity` is given (or the
    state is centred); otherwise it is left out rather than reporting the activity-0 coefficient as 'the' sensitivity. Read-only."""
    rows = []
    for pid in store.participants():
        tw = store.current_twin(pid)
        row = {"participant_label": pid, "twin_version": tw.version, "n_reconciled": len(store.reconciliation_log(pid)),
               "n_pending_forecasts": len(store.pending_forecasts(pid)), "profile": dict(tw.profile),
               "model_b_sensitivity": effective_sensitivity(tw.model_b)}
        try:
            ref = _reference_activity(tw, reference_activity)
            row["model_c_sensitivity_at_reference_activity"] = {**effective_sensitivity(tw.model_c, ref), "reference_activity": ref}
        except ValueError:
            row["model_c_sensitivity_at_reference_activity"] = None
        gm, gs = tw.model_c.coefficient("carbs_x_activity")
        row["model_c_activity_interaction"] = {"mean": gm, "sd": gs}
        rows.append(row)
    return {"n_twins": len(rows), "twins": rows, "units": UNITS, "guardrails": GUARDRAILS}


# ----------------------------------------------------------------------------- twin-specific metrics (blueprint section 21)

HIT_THRESHOLD = 0.5            # blueprint section 9: the 50% probability threshold is used for headline hit/miss reporting


def posterior_convergence(store: TwinStore, participant_id: str, reference_activity: Optional[float] = None) -> dict:
    """Does the posterior narrow as meals are observed? Per stored version: number of observations, posterior sd of the Model B sensitivity,
    of Model C's sensitivity at the reference activity, of beta and of gamma, and the ratio to the prior (version 0).

    With a known noise variance the posterior covariance can only shrink (in the positive-semidefinite order), so each reported sd is
    non-increasing; `monotone_non_increasing` verifies that on the actual numbers and is a check of the implementation, not a finding
    about the person. What is informative is HOW MUCH the sd fell: a quantity that stays near 1 was barely informed by the data
    (typically gamma, when the person's activity hardly varies). Descriptive only; no claim about calibration."""
    hist = parameter_history(store, participant_id, reference_activity)
    rows = hist["versions"]
    keys = {"model_b_sensitivity_sd": "b_sensitivity_sd", "model_c_sensitivity_at_reference_sd": "c_sensitivity_at_reference_sd",
            "model_c_beta_sd": "c_beta_sd", "model_c_gamma_sd": "c_gamma_sd"}
    series = {name: [r[k] for r in rows] for name, k in keys.items()}
    tol = 1e-9
    out = {"participant_label": participant_id, "reference_activity": hist["reference_activity"], "n_versions": len(rows),
           "n_observations": [r["n_observations_model_c"] for r in rows], "sd": series,
           "ratio_to_prior": {n: [v / s[0] if s[0] > 0 else None for v in s] for n, s in series.items()},
           "monotone_non_increasing": {n: bool(all(b <= a * (1 + tol) + tol for a, b in zip(s, s[1:]))) for n, s in series.items()},
           "units": UNITS,
           "note": "Descriptive. Narrowing is guaranteed by the known-noise conjugate update; the size of the reduction is what carries information."}
    out["current_over_prior"] = {n: r[-1] for n, r in out["ratio_to_prior"].items()}
    return out


def hit_rate_trend(store: TwinStore, participant_id: str, window: int = 5, threshold: float = HIT_THRESHOLD) -> dict:
    """Reconciliation 'hit' trend: a forecast is a HIT when (P >= threshold) agrees with the observed label (blueprint table: reconciliations.hit,
    at the 50% threshold). Reports, in reconciliation order, the cumulative hit rate and the hit rate over the last `window` forecasts,
    plus the first-half and second-half hit rates. A person has few reconciled meals, so this is a description of a short sequence,
    not evidence that the twin 'learns' (that would need many people; see the pooled cold-start/experienced split)."""
    if window < 1:
        raise ValueError("window must be at least 1")
    rows = reconciliation_report(store, participant_id)["reconciled"]
    out = {"participant_label": participant_id, "threshold": threshold, "window": window, "n_reconciled": len(rows)}
    for name in ("model_b", "model_c"):
        hits = [bool((r[name]["forecast_p_peak_at_least_180"] >= threshold) == r["observed"]["peak_at_least_180"]) for r in rows]
        cum = [float(np.mean(hits[: i + 1])) for i in range(len(hits))]
        rolling = [float(np.mean(hits[max(0, i + 1 - window): i + 1])) for i in range(len(hits))]
        half = len(hits) // 2
        out[name] = {"hits": hits, "cumulative_hit_rate": cum, "rolling_hit_rate": rolling,
                     "first_half_hit_rate": float(np.mean(hits[:half])) if half else None,
                     "second_half_hit_rate": float(np.mean(hits[half:])) if len(hits) - half and half else None,
                     "overall_hit_rate": float(np.mean(hits)) if hits else None}
    out["note"] = "Descriptive only. With a handful of meals per person a trend in the hit rate is dominated by chance."
    return out


# ----------------------------------------------------------------------------- blueprint section 18: contributing factors with the person's own history

TREND_TOLERANCE_MG_DL_PER_MIN = 0.1       # |slope| below this is called 'flat' (a display convention, not a clinical cut-off)
SIMILAR_MEAL_CARB_TOLERANCE = 0.25        # earlier meals within +/-25% of the carbohydrate amount count as 'similar' (display convention)


def explain_forecast_in_context(store: TwinStore, participant_id: str, meal: Dict[str, float], model: str = "model_c") -> dict:
    """`explain_forecast` plus the blueprint's contributing-factor list: the carbohydrate amount (with the share of the predicted rise it
    carries), the direction of the activity effect for THIS person, the pre-meal glucose trend if the meal carries `trend_slope_30min`,
    and this person's own reconciled meals of similar size (count, mean observed rise, share that crossed 180). Read-only; the factors
    describe the model and the person's recorded history, they are not causal statements."""
    twin = store.current_twin(participant_id)
    base = explain_forecast(twin, meal, model)
    carbs = float(meal["carbs_g"])
    factors = []
    c_term = base["terms"]["carbs_g"]["contribution_mg_dl"]
    total = base["predicted_rise_mg_dl"]
    share = (c_term / total) if total else None
    factors.append({"factor": "carbohydrate", "text": f"{carbs:g} g carbohydrate (primary driver)" if (share is not None and abs(share) >= 0.5)
                    else f"{carbs:g} g carbohydrate", "contribution_mg_dl": c_term, "share_of_predicted_rise": share})
    if "carbs_x_activity" in base["terms"]:
        act = base["terms"]["carbs_x_activity"]
        gamma = float(twin.model_c.coefficient("carbs_x_activity")[0]) if model == "model_c" else 0.0
        direction = "lowers" if act["contribution_mg_dl"] < 0 else "raises"
        factors.append({"factor": "activity", "contribution_mg_dl": act["contribution_mg_dl"], "contribution_sd_mg_dl": act["contribution_sd_mg_dl"],
                        "text": f"Pre-meal activity {float(meal['activity_level']):g}: the activity term {direction} the predicted rise by "
                                f"{abs(act['contribution_mg_dl']):.0f} mg/dL for this person (interaction coefficient {gamma:+.3f}; its uncertainty is large relative to its size when few meals are observed)"})
    slope = meal.get("trend_slope_30min")
    if slope is not None and np.isfinite(float(slope)):
        s = float(slope)
        word = "rising" if s > TREND_TOLERANCE_MG_DL_PER_MIN else ("falling" if s < -TREND_TOLERANCE_MG_DL_PER_MIN else "flat")
        factors.append({"factor": "glucose_trend", "slope_mg_dl_per_min": s, "text": f"Glucose was {word} before the meal ({s:+.2f} mg/dL per minute over 30 minutes); "
                        f"this is context only: the model does not use the trend as an input"})
    done = [(store.get_forecast(o.forecast_id), o) for o in store.reconciliation_log(participant_id)]
    similar = [(f, o) for f, o in done if abs(float(f.meal_row["carbs_g"]) - carbs) <= SIMILAR_MEAL_CARB_TOLERANCE * carbs]
    hist = {"n_similar_earlier_meals": len(similar), "carbohydrate_tolerance": SIMILAR_MEAL_CARB_TOLERANCE,
            "mean_observed_rise_mg_dl": float(np.mean([o.observed_peak_rise for _, o in similar])) if similar else None,
            "share_reached_180": float(np.mean([o.observed_exceeds_180 for _, o in similar])) if similar else None}
    factors.append({"factor": "own_history", **hist,
                    "text": (f"This person's own history: {len(similar)} earlier observed meal(s) within +/-{SIMILAR_MEAL_CARB_TOLERANCE:.0%} of this size"
                             + (f", mean observed rise {hist['mean_observed_rise_mg_dl']:.0f} mg/dL." if similar else "; none yet."))})
    return {**base, "contributing_factors": factors}


# ----------------------------------------------------------------------------- twin history export (blueprint Part 16 `twin_states` / `personal_parameters`)

def twin_history_rows(store: TwinStore, participant_id: str, reference_activity: Optional[float] = None) -> List[dict]:
    """One row per stored twin version, with the columns of the blueprint's `twin_states` and `personal_parameters` tables (Model C posterior
    detail, including the beta-gamma covariance) and Model B's sensitivity. Read-only; the caller decides where, if anywhere, to write it."""
    hist = store.twin_history(participant_id)
    if not hist:
        raise KeyError(f"no twin history for participant {participant_id!r}")
    ref = _reference_activity(hist[-1], reference_activity)
    rows = []
    for tw in hist:
        ib, ig = tw.model_c.feature_names.index("carbs_g"), tw.model_c.feature_names.index("carbs_x_activity")
        s = effective_sensitivity(tw.model_c, ref)
        rows.append({"version_id": tw.version, "parent_version_id": tw.parent_version, "created_at": tw.created_at.isoformat(),
                     "n_meals_observed": int(tw.model_c.n_observations_used),
                     "beta_mean": float(tw.model_c.mean[ib]), "beta_var": float(tw.model_c.covariance[ib, ib]),
                     "gamma_mean": float(tw.model_c.mean[ig]), "gamma_var": float(tw.model_c.covariance[ig, ig]),
                     "beta_gamma_covariance": float(tw.model_c.covariance[ib, ig]),
                     "carb_sensitivity_mean": s["mean"], "carb_sensitivity_variance": s["sd"] ** 2, "reference_activity": ref,
                     "model_b_sensitivity_mean": float(tw.model_b.mean[0]), "model_b_sensitivity_var": float(tw.model_b.covariance[0, 0])})
    return rows


def twin_history_csv(store: TwinStore, participant_id: str, reference_activity: Optional[float] = None) -> str:
    rows = twin_history_rows(store, participant_id, reference_activity)
    cols = list(rows[0])
    return "\n".join([",".join(cols)] + [",".join(str(r[c]) for c in cols) for r in rows]) + "\n"
