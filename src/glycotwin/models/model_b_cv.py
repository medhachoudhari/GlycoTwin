"""Model B evaluation: personalised Bayesian carbohydrate sensitivity, sequential (forecast -> observe -> update),
inside participant-level, group-stratified 5-fold cross-validation (the same folds as Model A).

Formulation (the repository's existing `glycotwin.models.bayesian`, used unchanged):
  observation model   peak_glucose_rise_i = beta * carbs_g_i + e_i,   e_i ~ Normal(0, sigma^2), sigma^2 known
                      (blueprint form, decision H12: no intercept; beta = the participant's carbohydrate sensitivity)
  prior               beta ~ Normal(mu_pop, Sigma_between)  (empirical-Bayes hierarchical prior fitted on the
                      TRAINING participants of the fold only; sigma^2 = pooled within-participant residual variance)
  update (scalar)     tau_post^2 = 1 / (1/tau^2 + c^2/sigma^2),  m_post = tau_post^2 * (m/tau^2 + c * rise / sigma^2)
  prediction          rise ~ Normal(m * c, sigma^2 + c^2 * tau^2);
                      P(event) = P(baseline + rise >= 180) = Phi((baseline + m * c - 180) / sqrt(sigma^2 + c^2 * tau^2))
(m, tau^2: current posterior mean and variance of beta; c = carbs_g.) The design is x = [carbs_g] only:
no intercept and no activity term. Activity is never read.

Sequential protocol for each VALIDATION participant (events sorted by meal_time):
  * start from the fold's population prior (fitted without any validation participant);
  * before forecasting an event at t, apply the updates of earlier events whose outcome window (t0, t0 + 120 min] has
    closed by t (for core-eligible events, which are isolated, that is every earlier event);
  * forecast the event from the current posterior, record it, and only then queue the event's own update.
So an event's forecast never uses its own outcome or any later outcome. Validation participants never touch the prior,
and one participant's observations never update another participant's state.
Research model; not clinically validated.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from glycotwin.features import OUTCOME_WINDOW
from glycotwin.models import model_a_cv as ma
from glycotwin.models import prior_schemes as ps
from glycotwin.models.bayesian import (MODEL_B_BLUEPRINT_FEATURES, BayesianLinearState, conjugate_update, fit_population_prior,
                                       forecast_exceeds_180)
from glycotwin.models.experiment import paired_cluster_bootstrap

MODEL_B_DESIGN = list(MODEL_B_BLUEPRINT_FEATURES)   # ["carbs_g"]: no intercept (H12)
TARGET = "label_exceeds_180"
REQUIRED = ["participant_id", "event_id", "meal_time", "carbs_g", "baseline_glucose", "peak_glucose_rise", TARGET]
SENS = "carbs_g"
MIN_OBS_LEVELS = (1, 3, 5, 10, 20)


def _check(events: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"event table is missing columns required by Model B: {missing}")
    ev = events.copy()
    ev["meal_time"] = pd.to_datetime(ev["meal_time"])
    num = ev[["carbs_g", "baseline_glucose", "peak_glucose_rise"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(num.to_numpy(dtype=float)).all():
        raise ValueError("Model B needs finite carbs_g, baseline_glucose and peak_glucose_rise (pass core-eligible events)")
    ev[TARGET] = ev[TARGET].astype(int)
    return ev


def sequential_participant(events_p: pd.DataFrame, prior: BayesianLinearState, window: pd.Timedelta = OUTCOME_WINDOW):
    """Forecast -> observe -> update for ONE participant from `prior`. Returns (records, trajectory).
    The trajectory lists every posterior version (version 0 = the prior)."""
    if list(prior.feature_names) != MODEL_B_DESIGN:
        raise ValueError("Model B uses x = [carbs_g] only (no intercept, no activity term)")
    ev = events_p.sort_values(["meal_time", "event_id"], kind="stable").reset_index(drop=True)
    state = prior
    pending: List[tuple] = []          # (window_close_time, row index)
    s0_mean, s0_sd = prior.coefficient(SENS)
    traj = [{"version": 0, "n_observations": 0, "sens_mean": s0_mean, "sens_sd": s0_sd, "after_event_order": None}]
    records = []
    for i, row in ev.iterrows():
        due = sorted([p for p in pending if p[0] <= row["meal_time"]], key=lambda p: p[0])
        pending = [p for p in pending if p[0] > row["meal_time"]]
        for _close, j in due:
            state = conjugate_update(state, ev.iloc[[j]])
            m, s = state.coefficient(SENS)
            traj.append({"version": state.version, "n_observations": state.n_observations_used, "sens_mean": m, "sens_sd": s, "after_event_order": int(j)})
        base = float(row["baseline_glucose"])
        f = forecast_exceeds_180(state, row, base)
        fr = forecast_exceeds_180(prior, row, base)
        m, s = state.coefficient(SENS)
        records.append({"event_id": row["event_id"], "participant_id": row["participant_id"], "order": int(i),
                        "y": int(row[TARGET]), "rise": float(row["peak_glucose_rise"]),
                        "p": f.probability_exceeds_180, "mean_rise": f.mean_rise, "pred_std": f.predictive_std,
                        "interval90_low": f.interval_90[0], "interval90_high": f.interval_90[1],
                        "p_frozen_prior": fr.probability_exceeds_180, "mean_rise_frozen_prior": fr.mean_rise,
                        "version_at_forecast": state.version, "n_personal_before": state.n_observations_used,
                        "sens_mean_before": m, "sens_sd_before": s})
        pending.append((row["meal_time"] + window, i))      # this event's own outcome is used only AFTER its forecast
    for _close, j in sorted(pending, key=lambda p: p[0]):    # end of sequence: final state, for the personalisation summary only
        state = conjugate_update(state, ev.iloc[[j]])
        m, s = state.coefficient(SENS)
        traj.append({"version": state.version, "n_observations": state.n_observations_used, "sens_mean": m, "sens_sd": s, "after_event_order": int(j)})
    return records, traj


def cross_validated_sequential(events: pd.DataFrame, folds: Dict[str, int], n_splits: int = ma.N_SPLITS,
                               window: pd.Timedelta = OUTCOME_WINDOW, prior_scheme: str = "empirical_bayes",
                               group_of: Optional[Dict[str, str]] = None):
    """Sequential Model B forecasts for every event; the prior of fold k is fitted on the other folds only.

    prior_scheme="empirical_bayes" (default) is the primary protocol, unchanged. prior_scheme="blueprint" builds, for each held-out participant, the
    blueprint prior from the training fold's participants in that participant's glycaemic group (`group_of` required); see models/prior_schemes.py."""
    prior_scheme, _ = ps.validate_prior_options("B", prior_scheme, None)
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
            prior = fit_population_prior(train, MODEL_B_DESIGN)
            pm, psd = prior.coefficient(SENS)
            priors[k] = {"prior_source": prior.prior_source, "sens_mean": pm, "sens_sd": psd,
                         "noise_sd": float(np.sqrt(prior.noise_variance)),
                         "n_training_events": int(len(train)), "n_training_participants": int(train["participant_id"].nunique())}
        else:
            train_g, fold_sums = ps.with_group(train, group_of), []
        for pid, g in val.groupby("participant_id", sort=True):
            if prior_scheme == "blueprint":
                if pid not in group_of:
                    raise ValueError("a held-out participant has no glycaemic group")
                prior, d = ps.blueprint_prior_for_participant(train_g, pid, group_of[pid], "B", None)
                fold_sums.append(d)
            recs, traj = sequential_participant(g, prior, window)
            for r in recs:
                r["fold"] = k
                r["fold_train_prevalence"] = prev
            out += recs
            trajs[pid] = {"fold": k, "trajectory": traj}
            if prior_scheme == "blueprint":
                trajs[pid]["prior"] = ps.participant_prior_record("B", d)
                trajs[pid]["prior_summary"] = d
        if prior_scheme == "blueprint":
            priors[k] = ps.fold_summary_B(fold_sums)
    oof = pd.DataFrame(out)
    if len(oof) != len(ev) or oof["event_id"].duplicated().any():
        raise AssertionError("sequential coverage is not exactly one forecast per event")
    return oof, trajs, priors


# ----------------------------------------------------------------------------- summaries

def _summ(v) -> dict:
    v = np.asarray([x for x in v if x is not None and np.isfinite(x)], dtype=float)
    if v.size == 0:
        return {"n": 0}
    q = np.percentile(v, [5, 25, 50, 75, 95])
    return {"n": int(v.size), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else None, "min": float(v.min()),
            "p5": float(q[0]), "p25": float(q[1]), "median": float(q[2]), "p75": float(q[3]), "p95": float(q[4]), "max": float(v.max())}


def personalization_summary(oof: pd.DataFrame, trajs: dict, priors: dict) -> dict:
    """Aggregate evidence that individual states are learned. No identifiers, no individual values."""
    n_obs = [t["trajectory"][-1]["n_observations"] for t in trajs.values()]
    final_m = [t["trajectory"][-1]["sens_mean"] for t in trajs.values()]
    final_sd = [t["trajectory"][-1]["sens_sd"] for t in trajs.values()]
    prior_m = [t.get("prior", priors[t["fold"]])["sens_mean"] for t in trajs.values()]       # per-participant prior if the blueprint scheme was used
    prior_sd = [t.get("prior", priors[t["fold"]])["sens_sd"] for t in trajs.values()]
    change = np.array(final_m) - np.array(prior_m)
    ratio = np.array(final_sd) / np.array(prior_sd)
    return {
        "units": "carbohydrate sensitivity = mg/dL of peak rise per gram of carbohydrate",
        "observations_per_participant": _summ(n_obs),
        "participants_with_at_least_n_observations": {str(m): int(sum(n >= m for n in n_obs)) for m in MIN_OBS_LEVELS},
        "prior_by_fold": {str(k): v for k, v in sorted(priors.items())},
        "final_posterior_sensitivity_mean_across_participants": _summ(final_m),
        "final_minus_prior_sensitivity_mean": _summ(change),
        "abs_final_minus_prior_sensitivity_mean": _summ(np.abs(change)),
        "final_over_prior_sensitivity_sd": _summ(ratio),
        "between_participant_sd_of_final_sensitivity_means": float(np.std(final_m, ddof=1)) if len(final_m) > 1 else None,
        "personal_observations_used_at_forecast_time": _summ(oof["n_personal_before"]),
        "posterior_sensitivity_sd_at_forecast_time": _summ(oof["sens_sd_before"]),
        "forecasts_made_from_prior_only": int((oof["n_personal_before"] == 0).sum()),
        "note": "aggregates across participants; individual trajectories are in a git-ignored local file only",
    }


def continuous_metrics(oof: pd.DataFrame) -> dict:
    """The model predicts the rise; these check that part directly (Model A has no equivalent)."""
    err = oof["mean_rise"] - oof["rise"]
    inside = (oof["rise"] >= oof["interval90_low"]) & (oof["rise"] <= oof["interval90_high"])
    errf = oof["mean_rise_frozen_prior"] - oof["rise"]
    return {"mae_rise_mg_dl": float(err.abs().mean()), "mean_error_rise_mg_dl": float(err.mean()),
            "coverage_of_90pct_predictive_interval": float(inside.mean()),
            "mae_rise_frozen_prior_mg_dl": float(errf.abs().mean())}


def compare_models(oof_a: pd.DataFrame, oof_b: pd.DataFrame, n_boot: int = 1000, seed: int = 0) -> dict:
    """Paired, participant-clustered differences on the SAME events (lower is better; an interval containing 0 is
    inconclusive). Also B against its own never-updated prior, the check that updating itself helps."""
    a = oof_a[["event_id", "participant_id", "y", "p"]].assign(model="A", mean_rise=np.nan, rise=np.nan)
    b = oof_b[["event_id", "participant_id", "y", "p", "mean_rise", "rise"]].assign(model="B")
    fz = oof_b[["event_id", "participant_id", "y", "rise"]].assign(model="B_frozen_prior", p=oof_b["p_frozen_prior"],
                                                                   mean_rise=oof_b["mean_rise_frozen_prior"])
    recs = pd.concat([a, b, fz], ignore_index=True)
    if set(oof_a["event_id"]) != set(oof_b["event_id"]):
        raise ValueError("Model A and Model B were not evaluated on the same events")
    out = {"_reading": "estimate = mean(metric_first - metric_second) over identical events; negative favours the first model; "
                       "95% interval from resampling participants; an interval containing 0 is inconclusive, not 'no difference'",
           "comparisons": []}
    for first, second, metric in (("B", "A", "brier"), ("B", "A", "log_loss"), ("B", "B_frozen_prior", "brier"),
                                  ("B", "B_frozen_prior", "log_loss"), ("B", "B_frozen_prior", "mae_rise")):
        out["comparisons"].append(paired_cluster_bootstrap(recs, first, second, metric, n_boot=n_boot, seed=seed))
    return out


def fingerprint(events: pd.DataFrame) -> str:
    cols = ["participant_id", "event_id", "meal_time", "carbs_g", "baseline_glucose", "peak_glucose_rise", TARGET]
    return hashlib.sha256(events[cols].sort_values(["participant_id", "event_id"]).to_csv(index=False).encode()).hexdigest()


def run_model_b(events: pd.DataFrame, group_of: Dict[str, str], seed: int = 0, threshold: float = ma.DEFAULT_THRESHOLD,
                n_boot: int = 1000, channel: str = "Libre GL", event_table_name: str = "",
                fold_group_of: Optional[Dict[str, str]] = None, prior_scheme: str = "empirical_bayes"):
    """Model B with the same participants, events, folds (seed) and metric conventions as Model A, plus a paired
    comparison with Model A. Returns (report, oof_b, oof_a, trajectories, folds).

    fold_group_of (optional): participant -> group for ALL participants that define the folds. Pass it when `events` is a
    subset (e.g. the activity-eligible events used by Model C) so the folds stay identical to Models A and C even if a
    participant has no events in the subset. Default None keeps the original behaviour (folds from the participants in `events`)."""
    prior_scheme, _ = ps.validate_prior_options("B", prior_scheme, None)
    ev = _check(events)
    if fold_group_of is None:
        folds = ma.make_participant_folds({p: group_of[p] for p in ev["participant_id"].unique()}, ma.N_SPLITS, seed)
    else:
        missing = set(ev["participant_id"]) - set(fold_group_of)
        if missing:
            raise ValueError(f"{len(missing)} participants in the events are not in fold_group_of")
        folds = ma.make_participant_folds(dict(fold_group_of), ma.N_SPLITS, seed)
    oof_b, trajs, priors = cross_validated_sequential(ev, folds, prior_scheme=prior_scheme, group_of=group_of if prior_scheme == "blueprint" else None)
    blueprint_summaries = [t["prior_summary"] for t in trajs.values() if "prior_summary" in t]
    oof_a = ma.cross_validated_predictions(ev, folds)
    b_metrics = ma.metric_bundle(oof_b["y"], oof_b["p"], threshold, oof_b["fold_train_prevalence"].to_numpy())
    a_metrics = ma.metric_bundle(oof_a["y"], oof_a["p"], threshold, oof_a["fold_train_prevalence"].to_numpy())
    f_metrics = ma.metric_bundle(oof_b["y"], oof_b["p_frozen_prior"], threshold, oof_b["fold_train_prevalence"].to_numpy())
    import scipy, sklearn, xgboost  # noqa: E401
    report = {
        "_privacy": "aggregate-only: no participant identifiers, timestamps or per-event values",
        "_status": "RESEARCH MODEL. Not clinically validated. Sequential out-of-fold forecasts only.",
        "manifest": {
            "model": "B: personalised Bayesian carbohydrate sensitivity (no activity term)",
            "formulation": "rise = beta*carbs + e, e~N(0,s2) known s2 (no intercept); beta~N(mu_pop, tau2_between) prior (see `prior`; empirical Bayes "
                           "from training participants unless the blueprint scheme was selected); conjugate update after each closed outcome window; "
                           "P(event)=Phi((baseline+m*carbs-180)/sqrt(s2+carbs^2*tau2))",
            "design_features": MODEL_B_DESIGN, "intercept": "none (blueprint form, H12)", "baseline_use": "threshold conversion only (not a regression input)",
            "update_rule": "update with an event only after its window (t0, t0+120 min] has closed and after its own forecast",
            "cgm_channel": channel, "event_table_file_name": event_table_name, "event_table_sha256": fingerprint(ev),
            "seed_for_folds": seed, "fold_assignment_sha256": ma.fold_assignment_hash(folds), "same_folds_as_model_a": True,
            "prior": ps.prior_manifest("B", prior_scheme, None, blueprint_summaries if prior_scheme == "blueprint" else None),
            "n_participants_in_folds": int(len(folds)), "threshold_for_classification_metrics": threshold, "n_bootstrap": n_boot,
            "versions": {"numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__,
                         "xgboost": xgboost.__version__},
            **ma._git_state(),
        },
        "data": {"n_events": int(len(ev)), "n_participants": int(ev["participant_id"].nunique()), "n_positive": int(ev[TARGET].sum()),
                 "n_negative": int((ev[TARGET] == 0).sum()), "prevalence": float(ev[TARGET].mean())},
        "fold_composition": ma.fold_composition(ev, folds, group_of),
        "model_b_overall": b_metrics,
        "model_b_overall_participant_bootstrap_95ci": ma.bootstrap_ci(oof_b, n_boot, seed),
        "model_b_continuous": continuous_metrics(oof_b),
        "model_b_per_fold": ma.per_fold_metrics(oof_b, threshold),
        "model_b_by_glycaemic_group": ma.group_metrics(oof_b, group_of, threshold),
        "model_b_frozen_prior_overall": f_metrics,
        "model_a_overall_same_folds": a_metrics,
        "model_a_overall_participant_bootstrap_95ci": ma.bootstrap_ci(oof_a, n_boot, seed),
        "paired_comparisons": compare_models(oof_a, oof_b, n_boot, seed),
        "personalization": personalization_summary(oof_b, trajs, priors),
    }
    return report, oof_b, oof_a, trajs, folds
