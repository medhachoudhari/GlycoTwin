"""Model C evaluation: activity-conditioned personalised Bayesian carbohydrate sensitivity (the main innovation experiment),
sequential (forecast -> observe -> update) inside the SAME participant-level, group-stratified 5-fold CV as Models A and B.

Locked specification (blueprint form; decisions B1-B6):
  observation model   rise_ij = (beta_i + gamma_i * a_ij) * c_ij + e_ij  =  beta_i * c_ij + gamma_i * (c_ij * a_ij) + e_ij,
                      e_ij ~ Normal(0, sigma^2), sigma^2 known.  c = carbs_g;  a = activity_level = mean raw METs over the four
                      hours strictly before the meal row (UN-centred, raw units, no [0,1] normalisation).  NO intercept,
                      NO activity main effect.  Design x = [c, c*a]; coefficient vector theta_i = (beta_i, gamma_i).
  prior               theta_i ~ Normal(mu_pop, Sigma_between): unstratified empirical Bayes fitted on the fold's TRAINING participants
                      only (see `fit_scale_aware_prior`).  gamma's between-participant spread is estimated empirically and reported.
  update              Sigma_post = (Sigma^-1 + x x^T / sigma^2)^-1,   mu_post = Sigma_post (Sigma^-1 mu + x * rise / sigma^2)
  prediction          rise ~ Normal(x^T mu, sigma^2 + x^T Sigma x),  x^T mu = (m_beta + m_gamma * a) * c;
                      P(event) = P(baseline + rise >= 180) = Phi((baseline + x^T mu - 180) / sqrt(sigma^2 + x^T Sigma x))
Baseline glucose enters only the threshold conversion; the observed rise is used only after the forecast.

Scale-aware regularisation (replaces the unit-dependent coefficient floor of `fit_population_prior`, which is left untouched for Model B):
  every coefficient is rescaled by the RMS of its regressor over the training rows (D = diag(rms(c), rms(c*a))), which turns it into an
  EFFECT on the rise in mg/dL.  The between-participant covariance estimate (observed spread minus mean sampling covariance, symmetrised)
  is converted to effect space (D S D), its eigenvalues are floored at  EPS * trace(D S_obs D) / k  (S_obs: observed spread of the per-participant
  OLS coefficients; EPS = 1e-3 is a dimensionless ratio, the same ratio Model B's floor uses), and it is converted back (D^-1 . D^-1).
  Rescaling activity by any factor s rescales gamma by 1/s and leaves D S D unchanged, so the prior, and therefore every forecast, is invariant
  to the activity units (tested).  The diffuse fallback (fewer than 5 usable participants) is likewise a variance of 1e4 mg/dL^2 in effect space.

Sequential protocol, participant isolation and leakage rules are identical to Model B (`model_b_cv`); that module is not modified.
Research model; not clinically validated.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from glycotwin.features import OUTCOME_WINDOW
from glycotwin.models import model_a_cv as ma
from glycotwin.models import prior_schemes as ps
from glycotwin.models.bayesian import (MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR, PRIOR_SOURCE_DIFFUSE, BayesianLinearState,
                                       _per_participant_ols, build_design_matrix, conjugate_update, forecast_exceeds_180)
from glycotwin.models.experiment import paired_cluster_bootstrap

MODEL_C_DESIGN: List[str] = ["carbs_g", "carbs_x_activity"]       # no intercept; carbs_x_activity = carbs_g * activity_level (un-centred)
BETA, GAMMA = "carbs_g", "carbs_x_activity"
TARGET = "label_exceeds_180"
REQUIRED = ["participant_id", "event_id", "meal_time", "carbs_g", "baseline_glucose", "peak_glucose_rise", "activity_level", TARGET]
REGULARIZATION_RATIO = 1e-3                                       # dimensionless, applied in effect space (mg/dL)
DIFFUSE_EFFECT_VARIANCE = 1e4                                     # mg/dL^2 in effect space, fallback only
PRIOR_SOURCE_SCALE_AWARE = "empirical_bayes_hierarchical_scale_aware"
MIN_OBS_LEVELS = (1, 3, 5, 10, 20)                                # reporting levels only, not minimums


# ----------------------------------------------------------------------------- eligibility and checks

def select_activity_eligible(table: pd.DataFrame) -> pd.DataFrame:
    """Model C population (decision B3): core-eligible events whose pre-meal activity is usable (`eligible_activity`,
    i.e. at least 50% METs coverage in the four hours before the meal). Events without usable activity are dropped,
    never imputed."""
    for c in ("eligible_core", "eligible_activity"):
        if c not in table.columns:
            raise ValueError(f"event table has no {c} column")
    return table[table["eligible_core"].astype(bool) & table["eligible_activity"].astype(bool)].copy()


def _check(events: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"event table is missing columns required by Model C: {missing}")
    ev = events.copy()
    ev["meal_time"] = pd.to_datetime(ev["meal_time"])
    num = ev[["carbs_g", "baseline_glucose", "peak_glucose_rise", "activity_level"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(num.to_numpy(dtype=float)).all():
        raise ValueError("Model C needs finite carbs_g, baseline_glucose, peak_glucose_rise and activity_level "
                         "(pass activity-eligible events; missing or low-coverage activity is excluded, never imputed)")
    ev[TARGET] = ev[TARGET].astype(int)
    return ev


# ----------------------------------------------------------------------------- scale-aware empirical-Bayes prior

def fit_scale_aware_prior(df: pd.DataFrame, feature_names: List[str] = MODEL_C_DESIGN,
                          regularization: float = REGULARIZATION_RATIO) -> Tuple[BayesianLinearState, dict]:
    """Unstratified empirical-Bayes prior for Model C from `df` (training participants only), plus diagnostics.
    Returns (state at version 0, diagnostics). `df` must hold ONLY training rows: nothing here can tell otherwise."""
    if list(feature_names) != MODEL_C_DESIGN:
        raise ValueError("fit_scale_aware_prior is the Model C prior: design must be ['carbs_g', 'carbs_x_activity']")
    k = len(feature_names)
    if len(df) <= k:
        raise ValueError(f"need more than {k} observations to fit a population prior")
    X = build_design_matrix(df, feature_names, 0.0)                 # un-centred: second column is carbs * activity
    y = df["peak_glucose_rise"].to_numpy(dtype=float)
    mu_pop, *_ = np.linalg.lstsq(X, y, rcond=None)
    pooled_variance = max(float((y - X @ mu_pop) @ (y - X @ mu_pop)) / max(len(y) - k, 1), 1e-6)
    rms = np.sqrt((X ** 2).mean(axis=0))
    rms = np.where(rms > 0, rms, 1.0)
    D = np.diag(rms)
    Dinv = np.diag(1.0 / rms)
    fits = _per_participant_ols(df, feature_names, 0.0)
    diag = {"n_training_participants": int(df["participant_id"].nunique()), "n_training_events": int(len(df)),
            "n_participants_usable_for_spread": len(fits), "effect_scale_rms": {BETA: float(rms[0]), GAMMA: float(rms[1])},
            "regularization_ratio": regularization}
    if len(fits) >= MIN_PARTICIPANTS_FOR_HIERARCHICAL_PRIOR:
        noise_variance = max(sum(f[1] for f in fits) / sum(f[2] for f in fits), 1e-6)
        betas = np.array([f[0] for f in fits])
        spread = np.atleast_2d(np.cov(betas, rowvar=False))
        sampling = np.mean([noise_variance * f[3] for f in fits], axis=0)
        raw = (spread - sampling + (spread - sampling).T) / 2.0
        raw_eff = D @ raw @ D
        vals, vecs = np.linalg.eigh(raw_eff)
        floor = max(regularization * float(np.trace(D @ spread @ D)) / k, 1e-12)
        between_eff = (vecs * np.clip(vals, floor, None)) @ vecs.T
        covariance = Dinv @ between_eff @ Dinv
        source = PRIOR_SOURCE_SCALE_AWARE
        diag.update({
            "raw_between_participant_variance_before_regularization": {BETA: float(raw[0, 0]), GAMMA: float(raw[1, 1])},
            "observed_spread_of_per_participant_coefficients": {BETA: float(spread[0, 0]), GAMMA: float(spread[1, 1])},
            "mean_sampling_variance_of_per_participant_coefficients": {BETA: float(sampling[0, 0]), GAMMA: float(sampling[1, 1])},
            "gamma_share_of_observed_spread_that_is_sampling_noise": float(sampling[1, 1] / spread[1, 1]) if spread[1, 1] > 0 else None,
            "n_eigenvalues_raised_to_the_floor": int((vals < floor).sum()), "effect_space_eigenvalue_floor": float(floor)})
    else:
        noise_variance = pooled_variance
        covariance = Dinv @ (np.eye(k) * DIFFUSE_EFFECT_VARIANCE) @ Dinv
        source = PRIOR_SOURCE_DIFFUSE
        diag["n_eigenvalues_raised_to_the_floor"] = None
    state = BayesianLinearState(feature_names=list(feature_names), mean=mu_pop, covariance=covariance, noise_variance=noise_variance,
                                version=0, n_observations_used=0, activity_center=0.0, prior_source=source)
    sd = np.sqrt(np.diag(covariance))
    diag.update({"prior_source": source, "beta_population_mean": float(mu_pop[0]), "gamma_population_mean": float(mu_pop[1]),
                 "beta_between_participant_sd": float(sd[0]), "gamma_between_participant_sd": float(sd[1]),
                 "beta_gamma_prior_correlation": float(covariance[0, 1] / (sd[0] * sd[1])), "noise_sd": float(np.sqrt(noise_variance))})
    return state, diag


# ----------------------------------------------------------------------------- sequential protocol

def _coef(state: BayesianLinearState):
    return state.coefficient(BETA), state.coefficient(GAMMA)


def sequential_participant(events_p: pd.DataFrame, prior: BayesianLinearState, window: pd.Timedelta = OUTCOME_WINDOW):
    """Forecast -> observe -> update for ONE participant from `prior`. Returns (records, trajectory); trajectory[0] is the prior."""
    if list(prior.feature_names) != MODEL_C_DESIGN or prior.activity_center != 0.0:
        raise ValueError("Model C uses x = [carbs_g, carbs_g * activity_level] only (no intercept, un-centred activity)")
    ev = events_p.sort_values(["meal_time", "event_id"], kind="stable").reset_index(drop=True)
    state = prior
    pending: List[tuple] = []

    def point(order):
        (bm, bs), (gm, gs) = _coef(state)
        return {"version": state.version, "n_observations": state.n_observations_used, "beta_mean": bm, "beta_sd": bs,
                "gamma_mean": gm, "gamma_sd": gs, "after_event_order": order}
    traj = [point(None)]
    records = []
    for i, row in ev.iterrows():
        due = sorted([p for p in pending if p[0] <= row["meal_time"]], key=lambda p: p[0])
        pending = [p for p in pending if p[0] > row["meal_time"]]
        for _close, j in due:
            state = conjugate_update(state, ev.iloc[[j]])
            traj.append(point(int(j)))
        base = float(row["baseline_glucose"])
        f = forecast_exceeds_180(state, row, base)
        fr = forecast_exceeds_180(prior, row, base)
        (bm, bs), (gm, gs) = _coef(state)
        records.append({"event_id": row["event_id"], "participant_id": row["participant_id"], "order": int(i), "y": int(row[TARGET]),
                        "rise": float(row["peak_glucose_rise"]), "activity": float(row["activity_level"]),
                        "p": f.probability_exceeds_180, "mean_rise": f.mean_rise, "pred_std": f.predictive_std,
                        "interval90_low": f.interval_90[0], "interval90_high": f.interval_90[1],
                        "p_frozen_prior": fr.probability_exceeds_180, "mean_rise_frozen_prior": fr.mean_rise,
                        "version_at_forecast": state.version, "n_personal_before": state.n_observations_used,
                        "beta_mean_before": bm, "beta_sd_before": bs, "gamma_mean_before": gm, "gamma_sd_before": gs})
        pending.append((row["meal_time"] + window, i))
    for _close, j in sorted(pending, key=lambda p: p[0]):          # final state, for the personalisation summary only
        state = conjugate_update(state, ev.iloc[[j]])
        traj.append(point(int(j)))
    return records, traj


def cross_validated_sequential(events: pd.DataFrame, folds: Dict[str, int], n_splits: int = ma.N_SPLITS,
                               window: pd.Timedelta = OUTCOME_WINDOW, prior_scheme: str = "empirical_bayes",
                               group_of: Optional[Dict[str, str]] = None, gamma_relative_sd: Optional[float] = None):
    """Sequential Model C forecasts for every event; fold k's prior is fitted on the other folds' participants only.

    prior_scheme="empirical_bayes" (default) is the primary protocol, unchanged. prior_scheme="blueprint" builds, for each held-out participant, the
    blueprint prior from the training fold's participants in that participant's glycaemic group (`group_of` required), with gamma centred at 0 and a
    prior sd of `gamma_relative_sd` (one of the prespecified widths, default 0.5) x |beta| / rms(activity); see models/prior_schemes.py."""
    prior_scheme, gamma_width = ps.validate_prior_options("C", prior_scheme, gamma_relative_sd)
    if prior_scheme == "blueprint" and group_of is None:
        raise ValueError("the blueprint prior needs group_of (participant -> glycaemic group)")
    ev = _check(events)
    unmapped = set(ev["participant_id"]) - set(folds)
    if unmapped:
        raise ValueError(f"{len(unmapped)} participants have no fold")
    ev["fold"] = ev["participant_id"].map(folds).astype(int)
    out, trajs, priors = [], {}, {}
    for k in range(n_splits):
        train, val = ev[ev["fold"] != k], ev[ev["fold"] == k]
        if set(train["participant_id"]) & set(val["participant_id"]):
            raise AssertionError("a participant is in both training and validation")
        if len(val) == 0:
            continue
        prev = float((train[TARGET] == 1).mean())
        if prior_scheme == "empirical_bayes":
            prior, diag = fit_scale_aware_prior(train)
            priors[k] = diag
        else:
            train_g, fold_sums = ps.with_group(train, group_of), []
        for pid, g in val.groupby("participant_id", sort=True):
            if prior_scheme == "blueprint":
                if pid not in group_of:
                    raise ValueError("a held-out participant has no glycaemic group")
                prior, d = ps.blueprint_prior_for_participant(train_g, pid, group_of[pid], "C", gamma_width)
                fold_sums.append(d)
            recs, traj = sequential_participant(g, prior, window)
            for r in recs:
                r["fold"] = k
                r["fold_train_prevalence"] = prev
            out += recs
            trajs[pid] = {"fold": k, "trajectory": traj}
            if prior_scheme == "blueprint":
                trajs[pid]["prior"] = ps.participant_prior_record("C", d)
                trajs[pid]["prior_summary"] = d
        if prior_scheme == "blueprint":
            priors[k] = ps.fold_summary_C(fold_sums, gamma_width)
    oof = pd.DataFrame(out)
    if len(oof) != len(ev) or oof["event_id"].duplicated().any():
        raise AssertionError("sequential coverage is not exactly one forecast per event")
    return oof, trajs, priors


# ----------------------------------------------------------------------------- reporting

def _summ(v) -> dict:
    v = np.asarray([x for x in v if x is not None and np.isfinite(x)], dtype=float)
    if v.size == 0:
        return {"n": 0}
    q = np.percentile(v, [5, 25, 50, 75, 95])
    return {"n": int(v.size), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else None, "min": float(v.min()),
            "p5": float(q[0]), "p25": float(q[1]), "median": float(q[2]), "p75": float(q[3]), "p95": float(q[4]), "max": float(v.max())}


def _identifiable(events: pd.DataFrame) -> Dict[str, bool]:
    """Both coefficients are identifiable from a participant's OWN events iff the design [c, c*a] has rank 2 with more events than
    coefficients (the condition the per-participant least-squares fit itself needs); no extra minimum is imposed."""
    out = {}
    for pid, g in events.groupby("participant_id"):
        X = build_design_matrix(g, MODEL_C_DESIGN, 0.0)
        out[pid] = bool(len(g) > len(MODEL_C_DESIGN) and np.linalg.matrix_rank(X) == len(MODEL_C_DESIGN))
    return out


def personalization_summary(oof: pd.DataFrame, trajs: dict, priors: dict, events: pd.DataFrame) -> dict:
    """Aggregate evidence that beta_i and gamma_i are learned. No identifiers, no individual values."""
    last = {p: t["trajectory"][-1] for p, t in trajs.items()}
    pri = {p: t.get("prior", priors[t["fold"]]) for p, t in trajs.items()}          # per-participant prior if the blueprint scheme was used
    n_obs = [v["n_observations"] for v in last.values()]
    d_beta = np.array([last[p]["beta_mean"] - pri[p]["beta_population_mean"] for p in last])
    d_gamma = np.array([last[p]["gamma_mean"] - pri[p]["gamma_population_mean"] for p in last])
    r_beta = np.array([last[p]["beta_sd"] / pri[p]["beta_between_participant_sd"] for p in last])
    r_gamma = np.array([last[p]["gamma_sd"] / pri[p]["gamma_between_participant_sd"] for p in last])
    ident = _identifiable(events)
    ident_ids = {p for p, ok in ident.items() if ok}
    fold_keys = sorted(priors)
    def across(key):
        return _summ([priors[k][key] for k in fold_keys])
    return {
        "units": "beta: mg/dL of peak rise per gram of carbohydrate; gamma: mg/dL per gram per unit of raw pre-meal activity (mean METs, 4 h)",
        "prior_across_folds": {"beta_population_mean": across("beta_population_mean"), "beta_between_participant_sd": across("beta_between_participant_sd"),
                               "gamma_population_mean": across("gamma_population_mean"), "gamma_between_participant_sd": across("gamma_between_participant_sd"),
                               "beta_gamma_prior_correlation": across("beta_gamma_prior_correlation"), "noise_sd": across("noise_sd")},
        "prior_by_fold": {str(k): priors[k] for k in fold_keys},
        "observations_per_participant": _summ(n_obs),
        "participants_with_at_least_n_observations_reporting_levels": {str(m): int(sum(n >= m for n in n_obs)) for m in MIN_OBS_LEVELS},
        "participants_with_both_coefficients_identifiable_from_own_events": int(len(ident_ids)),
        "participants_total": int(len(ident)),
        "identifiable_rule": "own events > 2 and design [c, c*a] has rank 2 (the least-squares requirement; no additional minimum)",
        "final_posterior_beta_mean": _summ([v["beta_mean"] for v in last.values()]),
        "final_posterior_gamma_mean": _summ([v["gamma_mean"] for v in last.values()]),
        "final_minus_prior_beta": _summ(d_beta), "final_minus_prior_gamma": _summ(d_gamma),
        "abs_final_minus_prior_beta": _summ(np.abs(d_beta)), "abs_final_minus_prior_gamma": _summ(np.abs(d_gamma)),
        "final_over_prior_sd_beta": _summ(r_beta), "final_over_prior_sd_gamma": _summ(r_gamma),
        "final_over_prior_sd_gamma_participants_identifiable": _summ([last[p]["gamma_sd"] / pri[p]["gamma_between_participant_sd"] for p in last if p in ident_ids]),
        "between_participant_sd_of_final_gamma_means": float(np.std([v["gamma_mean"] for v in last.values()], ddof=1)) if len(last) > 1 else None,
        "between_participant_sd_of_final_beta_means": float(np.std([v["beta_mean"] for v in last.values()], ddof=1)) if len(last) > 1 else None,
        "posterior_beta_sd_at_forecast_time": _summ(oof["beta_sd_before"]), "posterior_gamma_sd_at_forecast_time": _summ(oof["gamma_sd_before"]),
        "personal_observations_used_at_forecast_time": _summ(oof["n_personal_before"]),
        "forecasts_made_from_prior_only": int((oof["n_personal_before"] == 0).sum()),
        "note": "aggregates across participants; individual trajectories are in a git-ignored local file only",
    }


def continuous_metrics(oof: pd.DataFrame) -> dict:
    err = oof["mean_rise"] - oof["rise"]
    inside = (oof["rise"] >= oof["interval90_low"]) & (oof["rise"] <= oof["interval90_high"])
    errf = oof["mean_rise_frozen_prior"] - oof["rise"]
    return {"mae_rise_mg_dl": float(err.abs().mean()), "mean_error_rise_mg_dl": float(err.mean()),
            "coverage_of_90pct_predictive_interval": float(inside.mean()), "mae_rise_frozen_prior_mg_dl": float(errf.abs().mean())}


def compare_c_to_frozen_prior(oof_c: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> dict:
    """Paired participant-clustered differences between C and its own never-updated prior (does personal updating help?).
    Negative favours C; an interval containing 0 is inconclusive."""
    c = oof_c[["event_id", "participant_id", "y", "p", "mean_rise", "rise"]].assign(model="C")
    fz = oof_c[["event_id", "participant_id", "y", "rise"]].assign(model="C_frozen_prior", p=oof_c["p_frozen_prior"],
                                                                  mean_rise=oof_c["mean_rise_frozen_prior"])
    recs = pd.concat([c, fz], ignore_index=True)
    return {"_reading": "estimate = mean(metric_C - metric_frozen_prior); negative favours C; 95% interval resamples participants",
            "comparisons": [paired_cluster_bootstrap(recs, "C", "C_frozen_prior", m, n_boot=n_boot, seed=seed) for m in ("brier", "log_loss", "mae_rise")]}


def compare_c_to_b(oof_c: pd.DataFrame, oof_b: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> dict:
    """Paired C-vs-B comparison on IDENTICAL events (B must be re-run on the same activity-eligible subset and folds).
    Refuses different event sets. Negative favours C; an interval containing 0 is inconclusive."""
    if set(oof_c["event_id"]) != set(oof_b["event_id"]):
        raise ValueError("Model C and Model B were not evaluated on the same events; re-run Model B on the activity-eligible subset")
    c = oof_c[["event_id", "participant_id", "y", "p", "mean_rise", "rise"]].assign(model="C")
    b = oof_b[["event_id", "participant_id", "y", "p", "mean_rise", "rise"]].assign(model="B")
    recs = pd.concat([c, b], ignore_index=True)
    return {"_reading": "estimate = mean(metric_C - metric_B) over identical events; negative favours C; 95% interval resamples participants; "
                        "an interval containing 0 is inconclusive, not 'no difference'",
            "comparisons": [paired_cluster_bootstrap(recs, "C", "B", m, n_boot=n_boot, seed=seed) for m in ("brier", "log_loss", "mae_rise")]}


def fingerprint(events: pd.DataFrame) -> str:
    cols = ["participant_id", "event_id", "meal_time", "carbs_g", "baseline_glucose", "peak_glucose_rise", "activity_level", TARGET]
    return hashlib.sha256(events[cols].sort_values(["participant_id", "event_id"]).to_csv(index=False).encode()).hexdigest()


def run_model_c(events: pd.DataFrame, group_of: Dict[str, str], seed: int = 0, threshold: float = ma.DEFAULT_THRESHOLD,
                n_boot: int = 1000, channel: str = "Libre GL", event_table_name: str = "", n_core_events: Optional[int] = None,
                prior_scheme: str = "empirical_bayes", gamma_relative_sd: Optional[float] = None):
    """Model C on activity-eligible `events`. `group_of` must cover ALL core-eligible participants (as in Models A and B), so the
    folds are identical even if a participant has no activity-eligible events. Returns (report, oof, trajectories, folds)."""
    prior_scheme, gamma_width = ps.validate_prior_options("C", prior_scheme, gamma_relative_sd)
    ev = _check(events)
    extra = set(ev["participant_id"]) - set(group_of)
    if extra:
        raise ValueError(f"{len(extra)} participants have no glycaemic group")
    folds = ma.make_participant_folds(dict(group_of), ma.N_SPLITS, seed)
    oof, trajs, priors = cross_validated_sequential(ev, folds, prior_scheme=prior_scheme, group_of=dict(group_of) if prior_scheme == "blueprint" else None,
                                                    gamma_relative_sd=gamma_width)
    blueprint_summaries = [t["prior_summary"] for t in trajs.values() if "prior_summary" in t]
    both = ev.groupby("participant_id")[TARGET].agg(["min", "max"])
    import scipy, sklearn, xgboost  # noqa: E401
    report = {
        "_privacy": "aggregate-only: no participant identifiers, timestamps or per-event values",
        "_status": "RESEARCH MODEL. Not clinically validated. Sequential out-of-fold forecasts only.",
        "manifest": {
            "model": "C: activity-conditioned personalised Bayesian carbohydrate sensitivity",
            "formulation": "rise = (beta_i + gamma_i * activity) * carbs + e, e~N(0,s2) known s2; no intercept; activity = raw mean METs over the "
                           "4 h strictly before the meal row, un-centred; theta_i~N(mu_pop, Sigma_between) prior (see `prior`: unstratified empirical Bayes from training "
                           "participants only unless the blueprint scheme was selected); conjugate update after each closed outcome window; "
                           "P(event)=Phi((baseline+x'mu-180)/sqrt(s2+x'Sigma x))",
            "design_features": MODEL_C_DESIGN, "intercept": "none", "activity": "activity_level, raw, un-centred",
            "regularization": "scale-aware: eigenvalue floor of the effect-space (coefficient x regressor RMS) between-participant covariance at "
                              f"{REGULARIZATION_RATIO} x trace of the observed effect-space spread; invariant to activity units",
            "baseline_use": "threshold conversion only (not a regression input)",
            "update_rule": "update with an event only after its window (t0, t0+120 min] has closed and after its own forecast",
            "population": "core-eligible AND activity-eligible events", "cgm_channel": channel, "event_table_file_name": event_table_name,
            "event_table_sha256": fingerprint(ev), "seed_for_folds": seed, "fold_assignment_sha256": ma.fold_assignment_hash(folds),
            "prior": ps.prior_manifest("C", prior_scheme, gamma_width, blueprint_summaries if prior_scheme == "blueprint" else None),
            "n_participants_in_folds": int(len(folds)), "threshold_for_classification_metrics": threshold, "n_bootstrap": n_boot,
            "folds_built_from": "all core-eligible participants (same function, participants and seed as Models A and B)",
            "same_folds_as_model_a_and_b": True,
            "versions": {"numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__,
                         "xgboost": xgboost.__version__}, **ma._git_state()},
        "data": {"n_events": int(len(ev)), "n_core_events_before_activity_eligibility": n_core_events,
                 "n_events_dropped_for_missing_or_low_coverage_activity": (None if n_core_events is None else int(n_core_events - len(ev))),
                 "n_participants": int(ev["participant_id"].nunique()), "n_participants_in_folds": int(len(folds)),
                 "n_positive": int(ev[TARGET].sum()), "n_negative": int((ev[TARGET] == 0).sum()), "prevalence": float(ev[TARGET].mean()),
                 "participants_with_both_classes": int(((both["min"] == 0) & (both["max"] == 1)).sum()),
                 "activity_level": _summ(ev["activity_level"])},
        "fold_composition": ma.fold_composition(ev, folds, {p: group_of[p] for p in folds}),
        "model_c_overall": ma.metric_bundle(oof["y"], oof["p"], threshold, oof["fold_train_prevalence"].to_numpy()),
        "model_c_overall_participant_bootstrap_95ci": ma.bootstrap_ci(oof, n_boot, seed),
        "model_c_continuous": continuous_metrics(oof),
        "model_c_per_fold": ma.per_fold_metrics(oof, threshold),
        "model_c_by_glycaemic_group": ma.group_metrics(oof, {p: group_of[p] for p in ev["participant_id"].unique()}, threshold),
        "model_c_frozen_prior_overall": ma.metric_bundle(oof["y"], oof["p_frozen_prior"], threshold, oof["fold_train_prevalence"].to_numpy()),
        "paired_c_vs_frozen_prior": compare_c_to_frozen_prior(oof, n_boot, seed),
        "paired_c_vs_b": "NOT COMPUTED HERE: re-run Model B on this exact activity-eligible event subset and folds, then use compare_c_to_b",
        "personalization": personalization_summary(oof, trajs, priors, ev),
    }
    return report, oof, trajs, folds
