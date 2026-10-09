"""Blueprint-form population prior for the twin (blueprint section 10, "Prior").

Blueprint text: "beta is initialized from the population-level regression of glucose rise on carbs, computed once across all patients
in the training fold, stratified by glycaemic group ... gamma is initialized at 0 (no assumed activity effect) with a moderately wide
prior variance." Observation noise: "Gaussian ... variance is estimated from the population's meal-to-meal variability."

What this module does, point by point (and what it had to decide):
  * beta prior MEAN   regression through the origin of peak rise on carbohydrate (rise = beta * carbs, the blueprint/H12 form) over the
                      training rows of the participant's glycaemic group; pooled over all training rows when no group is given, the
                      group is not in the data, or it has fewer than `min_group_participants` training participants (the fallback is
                      recorded in the diagnostics, never silent).
  * beta prior VARIANCE the between-participant variance of per-participant slopes, by the method of moments (observed spread minus mean
                      sampling variance), floored to a small positive share of the observed spread. The blueprint gives no number; this is
                      the empirical-Bayes choice used elsewhere in the repository, computed within the group when the group is large
                      enough, otherwise on all training participants.
  * gamma prior MEAN  exactly 0.
  * gamma prior VARIANCE "moderately wide" is not quantified in the blueprint. DECISION: prior sd of gamma = GAMMA_RELATIVE_SD x |beta mean|
                      / rms(activity) with GAMMA_RELATIVE_SD = 0.5, i.e. one prior sd of the activity term at a typical activity level is
                      half of the population sensitivity (the blueprint's own toy example has an activity effect of roughly this size).
                      A convention taken from the blueprint's scale, NOT fitted to outcomes and NOT tuned; it is a parameter, and how
                      much conclusions depend on it has NOT been studied.
  * beta-gamma prior correlation 0 (independent); the posterior becomes correlated through the data, as the blueprint describes.
  * noise variance    pooled within-participant residual variance of the through-origin fits (Model B) or the two-term fits (Model C).

This is an ALTERNATIVE to the empirical-Bayes priors used in the Model B/C research runs (`fit_population_prior`, `fit_scale_aware_prior`);
it does not replace them and the reported B-vs-C results do not use it. Nothing here has been evaluated on real data.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from glycotwin.models.bayesian import (MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR, BayesianLinearState, _per_participant_ols, build_design_matrix)

GAMMA_RELATIVE_SD = 0.5
MIN_GROUP_PARTICIPANTS = MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR
BETA_VARIANCE_FLOOR_SHARE = 1e-3
BLUEPRINT_PRIOR_SOURCE = "blueprint_stratified_regression_gamma0"
POOLED_SOURCE = BLUEPRINT_PRIOR_SOURCE + "_pooled_fallback"
DIFFUSE_BETA_SD_SHARE = 1.0           # fallback when no between-participant spread can be estimated: sd = this x |beta mean|


def _through_origin(d: pd.DataFrame) -> float:
    c, y = d["carbs_g"].to_numpy(float), d["peak_glucose_rise"].to_numpy(float)
    denom = float(c @ c)
    if denom <= 0:
        raise ValueError("carbohydrate is zero for every training row; cannot regress rise on carbohydrate")
    return float(c @ y / denom)


def _beta_variance(d: pd.DataFrame) -> Tuple[float, str]:
    fits = _per_participant_ols(d, ["carbs_g"], 0.0)
    if len(fits) < MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR:
        return float("nan"), "too few participants with an identifiable slope"
    noise = max(sum(f[1] for f in fits) / sum(f[2] for f in fits), 1e-6)
    slopes = np.array([float(f[0][0]) for f in fits])
    spread = float(np.var(slopes, ddof=1))
    sampling = float(np.mean([noise * f[3][0, 0] for f in fits]))
    return max(spread - sampling, BETA_VARIANCE_FLOOR_SHARE * spread, 1e-9), "method of moments"


def _noise_variance(train: pd.DataFrame, features: list) -> float:
    fits = _per_participant_ols(train, features, 0.0)
    if fits:
        return max(sum(f[1] for f in fits) / sum(f[2] for f in fits), 1e-6)
    X = build_design_matrix(train, features, 0.0)
    y = train["peak_glucose_rise"].to_numpy(float)
    mu, *_ = np.linalg.lstsq(X, y, rcond=None)
    return max(float((y - X @ mu) @ (y - X @ mu)) / max(len(y) - len(features), 1), 1e-6)


def fit_blueprint_prior(train: pd.DataFrame, glycaemic_group: Optional[str] = None, group_column: str = "glycaemic_group",
                        gamma_relative_sd: float = GAMMA_RELATIVE_SD, min_group_participants: int = MIN_GROUP_PARTICIPANTS
                        ) -> Tuple[BayesianLinearState, BayesianLinearState, dict]:
    """Return (Model B prior, Model C prior, diagnostics) from TRAINING rows only (the caller must have removed the participant).
    Needs participant_id, carbs_g, activity_level, peak_glucose_rise."""
    for col in ("participant_id", "carbs_g", "activity_level", "peak_glucose_rise"):
        if col not in train.columns:
            raise ValueError(f"training events are missing column {col!r}")
    if gamma_relative_sd <= 0:
        raise ValueError("gamma_relative_sd must be positive")
    num = train[["carbs_g", "activity_level", "peak_glucose_rise"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(num.to_numpy(float)).all():
        raise ValueError("training events contain missing or non-finite carbs_g, activity_level or peak_glucose_rise")
    if len(train) < 3 or train["participant_id"].nunique() < 2:
        raise ValueError("need at least two participants and three events to build a prior")

    diag = {"group_requested": glycaemic_group, "group_used": None, "fallback_reason": None, "gamma_relative_sd": gamma_relative_sd}
    stratum = train
    if glycaemic_group is None:
        diag["fallback_reason"] = "no glycaemic group supplied: pooled over all training participants"
    elif group_column not in train.columns:
        diag["fallback_reason"] = f"training events have no {group_column!r} column: pooled over all training participants"
    else:
        in_group = train[train[group_column].astype(str) == str(glycaemic_group)]
        if in_group["participant_id"].nunique() < min_group_participants:
            diag["fallback_reason"] = (f"only {in_group['participant_id'].nunique()} training participants in group {glycaemic_group!r} "
                                       f"(need {min_group_participants}): pooled over all training participants")
        else:
            stratum, diag["group_used"] = in_group, str(glycaemic_group)
    pooled = diag["group_used"] is None

    beta_mean = _through_origin(stratum)
    beta_var, how = _beta_variance(stratum)
    if not np.isfinite(beta_var) and stratum is not train:
        beta_var, how = _beta_variance(train)
        how += " (computed on all training participants)"
    if not np.isfinite(beta_var):
        beta_var, how = (DIFFUSE_BETA_SD_SHARE * max(abs(beta_mean), 1e-3)) ** 2, "fallback: sd equal to |beta mean| (no spread could be estimated)"
    a_rms = float(np.sqrt(np.mean(num["activity_level"].to_numpy(float) ** 2)))
    if a_rms <= 0:
        raise ValueError("activity is zero for every training row; the activity interaction cannot be scaled")
    gamma_sd = gamma_relative_sd * max(abs(beta_mean), 1e-3) / a_rms
    source = POOLED_SOURCE if pooled else BLUEPRINT_PRIOR_SOURCE

    prior_b = BayesianLinearState(feature_names=["carbs_g"], mean=np.array([beta_mean]), covariance=np.array([[beta_var]]),
                                  noise_variance=_noise_variance(train, ["carbs_g"]), version=0, n_observations_used=0,
                                  activity_center=0.0, prior_source=source)
    prior_c = BayesianLinearState(feature_names=["carbs_g", "carbs_x_activity"], mean=np.array([beta_mean, 0.0]),
                                  covariance=np.diag([beta_var, gamma_sd ** 2]), noise_variance=_noise_variance(train, ["carbs_g", "carbs_x_activity"]),
                                  version=0, n_observations_used=0, activity_center=0.0, prior_source=source)
    diag.update({"beta_prior_mean": beta_mean, "beta_prior_sd": float(np.sqrt(beta_var)), "beta_variance_method": how,
                 "gamma_prior_mean": 0.0, "gamma_prior_sd": float(gamma_sd), "activity_rms": a_rms,
                 "n_stratum_participants": int(stratum["participant_id"].nunique()), "n_stratum_events": int(len(stratum)),
                 "noise_sd_model_b": float(np.sqrt(prior_b.noise_variance)), "noise_sd_model_c": float(np.sqrt(prior_c.noise_variance)),
                 "prior_source": source,
                 "note": "Blueprint-form prior; an alternative to the empirical-Bayes priors of the Model B/C research runs; not evaluated on real data."})
    return prior_b, prior_c, diag
