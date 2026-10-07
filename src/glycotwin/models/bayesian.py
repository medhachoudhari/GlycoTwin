"""Closed-form Bayesian carbohydrate-sensitivity model (Models B and C).

Model: peak_glucose_rise = x @ beta + noise, noise ~ Normal(0, noise_variance).

- Model B features: x = [1, carbs_g]
      beta = [intercept, carb_sensitivity]
- Model C features: x = [1, carbs_g, carbs_g * (activity - activity_center)]
      beta = [intercept, carb_sensitivity_at_reference_activity, activity_interaction]
  Activity is centred at a reference value (the mean activity of the data the prior was
  fit on, stored in the state) so the carb coefficient is the sensitivity at a *typical*
  activity level rather than at activity = 0, which may be outside the observed range.
  Centring is a reparametrisation: it changes what the coefficients mean, not the fit.

beta has a Normal prior/posterior (conjugate Normal-Normal Bayesian linear regression),
so each participant's posterior updates in closed form from their own new meals without
refitting - this is the twin's "update posterior, save a new version" mechanism.

Prior (empirical Bayes, hierarchical): participant beta_i ~ Normal(mu_pop, Sigma_between).
mu_pop is the pooled OLS fit; Sigma_between is the between-participant spread of
per-participant OLS coefficients minus their average sampling covariance (method of
moments), floored to be positive definite; the noise variance is the pooled
*within-participant* residual variance. If too few participants/meals exist to estimate
that spread, the prior falls back to a deliberately diffuse one and says so in
`prior_source`: forecasts are then honestly near-uninformative until personal data arrives.

Assumptions that remain and need confirming against the blueprint / real data:
  * noise_variance is treated as known (what makes the update exactly conjugate);
  * the rise is Gaussian with constant variance. A peak (a maximum over a window) is
    non-negative and likely right-skewed, and its variance probably grows with carbs;
  * participants are exchangeable draws from one population (no covariates in the prior).

P(exceed 180) is the posterior-predictive probability that baseline + rise >= 180, i.e.
Phi((baseline + mean_rise - 180) / predictive_std), where predictive_std combines
parameter uncertainty and residual noise. It equals the label
`label_exceeds_180 = 1[baseline_glucose + peak_glucose_rise >= 180]` (the blueprint's inclusive
threshold; for a continuous predictive distribution P(>=180) == P(>180)) *only if* the adapter
defines peak_glucose_rise = max(CGM in the window) - baseline_glucose with the same
baseline (features.validate_meal_events checks this consistency).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

GLUCOSE_THRESHOLD_MG_DL = 180.0

MODEL_B_FEATURES = ["intercept", "carbs_g"]
# Blueprint form of Model B (decision H12): rise = beta_i * carbs, NO intercept. Used by models/model_b_cv.py.
# MODEL_B_FEATURES above is the earlier intercept variant, still used by the legacy prequential harness
# (models/experiment.py) and the in-memory twin store (twin/state.py); aligning those is pending the Model C work.
MODEL_B_BLUEPRINT_FEATURES = ["carbs_g"]
MODEL_C_FEATURES = ["intercept", "carbs_g", "carbs_x_activity"]

# Fewer participants than this cannot support an estimate of between-participant spread.
MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR = 5

PRIOR_SOURCE_HIERARCHICAL = "empirical_bayes_hierarchical"
PRIOR_SOURCE_DIFFUSE = "diffuse_fallback"


def build_design_matrix(
    df: pd.DataFrame, feature_names: list[str], activity_center: float = 0.0
) -> np.ndarray:
    """Design matrix for Model B or C from a MealEvent-shaped DataFrame."""
    n = len(df)
    cols = []
    for name in feature_names:
        if name == "intercept":
            cols.append(np.ones(n))
        elif name == "carbs_g":
            cols.append(df["carbs_g"].to_numpy(dtype=float))
        elif name == "carbs_x_activity":
            activity = df["activity_level"].to_numpy(dtype=float) - activity_center
            cols.append(df["carbs_g"].to_numpy(dtype=float) * activity)
        else:
            raise ValueError(f"unknown feature '{name}'")
    return np.column_stack(cols)


@dataclass
class BayesianLinearState:
    """A participant's (or the population prior's) distribution over beta at a version."""

    feature_names: list[str]
    mean: np.ndarray           # shape (k,)
    covariance: np.ndarray     # shape (k, k)
    noise_variance: float
    version: int = 0
    n_observations_used: int = 0   # this participant's own meals only; the prior is 0
    activity_center: float = 0.0
    prior_source: str = "unspecified"

    def __post_init__(self) -> None:
        k = len(self.feature_names)
        self.mean = np.asarray(self.mean, dtype=float).reshape(k)
        self.covariance = np.asarray(self.covariance, dtype=float).reshape(k, k)
        if self.noise_variance <= 0:
            raise ValueError("noise_variance must be positive")

    def coefficient(self, name: str) -> tuple[float, float]:
        """(posterior mean, posterior std) for one named coefficient."""
        i = self.feature_names.index(name)
        return float(self.mean[i]), float(np.sqrt(self.covariance[i, i]))


def _per_participant_ols(df: pd.DataFrame, feature_names: list[str], activity_center: float):
    """OLS per participant; skips participants without enough/identifiable data."""
    fits = []
    k = len(feature_names)
    for _pid, g in df.groupby("participant_id"):
        X = build_design_matrix(g, feature_names, activity_center)
        y = g["peak_glucose_rise"].to_numpy(dtype=float)
        if len(g) <= k or np.linalg.matrix_rank(X) < k:
            continue
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        fits.append((beta, float(resid @ resid), len(g) - k, np.linalg.inv(X.T @ X)))
    return fits


def fit_population_prior(
    df: pd.DataFrame,
    feature_names: list[str],
    exclude_participants: tuple[str, ...] | list[str] = (),
    diffuse_variance: float = 1e4,
) -> BayesianLinearState:
    """Empirical-Bayes population prior from `df` (see module docstring).

    Leakage rules for callers (not enforceable from here):
      * pass TRAINING rows only - fitting the prior on evaluation-period meals leaks;
      * to evaluate a participant's personalization, pass `exclude_participants=(that
        participant,)` (leave-one-participant-out). Otherwise their own training meals
        shape the prior and are then counted again in the personal update.
    """
    d = df[~df["participant_id"].isin(list(exclude_participants))]
    k = len(feature_names)
    if len(d) <= k:
        raise ValueError(f"need more than {k} observations to fit a population prior")

    activity_center = (
        float(d["activity_level"].mean()) if "carbs_x_activity" in feature_names else 0.0
    )
    X = build_design_matrix(d, feature_names, activity_center)
    y = d["peak_glucose_rise"].to_numpy(dtype=float)
    mu_pop, *_ = np.linalg.lstsq(X, y, rcond=None)
    pooled_resid = y - X @ mu_pop
    pooled_variance = max(float(pooled_resid @ pooled_resid) / max(len(y) - k, 1), 1e-6)

    fits = _per_participant_ols(d, feature_names, activity_center)
    if len(fits) >= MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR:
        noise_variance = max(sum(f[1] for f in fits) / sum(f[2] for f in fits), 1e-6)
        betas = np.array([f[0] for f in fits])
        spread = np.atleast_2d(np.cov(betas, rowvar=False))
        sampling = np.mean([noise_variance * f[3] for f in fits], axis=0)
        between = (spread - sampling + (spread - sampling).T) / 2.0
        vals, vecs = np.linalg.eigh(between)
        floor = max(1e-3 * float(np.trace(spread)) / k, 1e-9)
        between = (vecs * np.clip(vals, floor, None)) @ vecs.T
        covariance, source = between, PRIOR_SOURCE_HIERARCHICAL
    else:
        noise_variance = pooled_variance
        covariance, source = np.eye(k) * diffuse_variance, PRIOR_SOURCE_DIFFUSE

    return BayesianLinearState(
        feature_names=list(feature_names),
        mean=mu_pop,
        covariance=covariance,
        noise_variance=noise_variance,
        version=0,
        n_observations_used=0,
        activity_center=activity_center,
        prior_source=source,
    )


def conjugate_update(prior: BayesianLinearState, df: pd.DataFrame) -> BayesianLinearState:
    """Closed-form Normal-Normal Bayesian linear regression update.

    posterior_precision = prior_precision + X^T X / noise_variance
    posterior_mean      = posterior_cov @ (prior_precision @ prior_mean + X^T y / noise_variance)

    A pure function of (prior, df): it cannot depend on any meal not passed in.
    Sequential single-meal updates equal one batch update (noise variance is fixed).
    """
    if len(df) == 0:
        raise ValueError("conjugate_update requires at least one observation")

    X = build_design_matrix(df, prior.feature_names, prior.activity_center)
    y = df["peak_glucose_rise"].to_numpy(dtype=float)
    if not (np.isfinite(X).all() and np.isfinite(y).all()):
        raise ValueError("conjugate_update received non-finite features or outcomes")

    prior_precision = np.linalg.inv(prior.covariance)
    posterior_covariance = np.linalg.inv(prior_precision + (X.T @ X) / prior.noise_variance)
    posterior_covariance = (posterior_covariance + posterior_covariance.T) / 2.0
    posterior_mean = posterior_covariance @ (
        prior_precision @ prior.mean + (X.T @ y) / prior.noise_variance
    )

    return BayesianLinearState(
        feature_names=prior.feature_names,
        mean=posterior_mean,
        covariance=posterior_covariance,
        noise_variance=prior.noise_variance,
        version=prior.version + 1,
        n_observations_used=prior.n_observations_used + len(df),
        activity_center=prior.activity_center,
        prior_source=prior.prior_source,
    )


@dataclass
class ForecastDistribution:
    """Posterior-predictive forecast for one meal."""

    mean_rise: float
    predictive_std: float
    probability_exceeds_180: float
    interval_90: tuple[float, float] = field(repr=False, default=(0.0, 0.0))


def forecast_exceeds_180(
    state: BayesianLinearState, x_row: pd.Series, baseline_glucose: float
) -> ForecastDistribution:
    """P(baseline + rise >= 180) and a 90% predictive interval on the rise."""
    x = build_design_matrix(x_row.to_frame().T, state.feature_names, state.activity_center)[0]
    mean_rise = float(x @ state.mean)
    predictive_std = float(np.sqrt(state.noise_variance + x @ state.covariance @ x))

    margin = baseline_glucose + mean_rise - GLUCOSE_THRESHOLD_MG_DL
    prob_exceeds = float(stats.norm.cdf(margin / predictive_std))

    z90 = stats.norm.ppf(0.95)
    interval = (mean_rise - z90 * predictive_std, mean_rise + z90 * predictive_std)
    return ForecastDistribution(mean_rise, predictive_std, prob_exceeds, interval)
