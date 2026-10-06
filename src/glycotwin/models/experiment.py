"""Prequential (forecast-then-learn) experiment harness for the key comparison.

For each held-out participant, in meal order: forecast the meal BEFORE its outcome is known, and
apply the Bayesian update only once the meal's outcome window has closed. The population prior,
the baselines' statistics and the activity cut all come from OTHER participants only.

Forecasters (all produce P(peak >= threshold) and a predictive distribution of the rise):
  frozen_B / frozen_C   population prior only, never updated        -> what updating must beat
  B / C                 personalised, updated after each closed window (C has the activity term)
  B_shuffled            updated with OTHER participants' meals       -> control: gain must disappear
  C_perm_activity       C with activity permuted within participant  -> control for the activity term
  personal_rate         carbs x running mean of the participant's own past rise-per-gram
  population_constant   training mean rise, ignoring the meal

Nothing here claims an effect: it produces per-forecast records and paired, participant-clustered
differences. Whether any model "wins" is read from those, with their intervals, by a human.
"""

from __future__ import annotations

import hashlib
import platform
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL, OUTCOME_WINDOW
from glycotwin.models.baseline import PopulationBaselineModel
from glycotwin.models.bayesian import (
    MODEL_B_FEATURES, MODEL_C_FEATURES, conjugate_update, fit_population_prior, forecast_exceeds_180)

REQUIRED = ["participant_id", "meal_time", "carbs_g", "baseline_glucose", "activity_level", "peak_glucose_rise",
            "label_exceeds_180"]
MODELS = ["frozen_B", "frozen_C", "B", "C", "B_shuffled", "C_perm_activity", "personal_rate", "population_constant"]
MODEL_A = "A"  # population XGBoost, trained on other participants only; optional (needs both classes in training)
METRICS = ("brier", "log_loss", "mae_rise")


def _check(events: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"events missing required columns: {missing}")
    num = events[["carbs_g", "baseline_glucose", "activity_level", "peak_glucose_rise", "label_exceeds_180"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(num.to_numpy()).all():
        raise ValueError("events contain non-finite values; pass only eligible events (eligible_activity == True)")


def _normal_prob(baseline: float, mean_rise: float, std: float, threshold: float) -> float:
    return float(stats.norm.cdf((baseline + mean_rise - threshold) / std)) if std > 0 else float(baseline + mean_rise >= threshold)


def prequential_participant(
    events: pd.DataFrame,
    train: pd.DataFrame,
    window: pd.Timedelta = OUTCOME_WINDOW,
    seed: int = 0,
    threshold: float = GLUCOSE_THRESHOLD_MG_DL,
    include_model_a: bool = False,
) -> pd.DataFrame:
    """Per-forecast records for ONE participant. `train` must not contain this participant.
    include_model_a adds the population XGBoost (raw probabilities; the blueprint's isotonic calibration
    needs an inner split and is not applied here)."""
    _check(events); _check(train)
    pid = events["participant_id"].iloc[0]
    if (train["participant_id"] == pid).any():
        raise ValueError("train contains the held-out participant: that would leak their outcomes into the prior")
    ev = events.sort_values("meal_time", kind="stable").reset_index(drop=True)
    rng = np.random.default_rng(seed)

    prior_b = fit_population_prior(train, MODEL_B_FEATURES)
    prior_c = fit_population_prior(train, MODEL_C_FEATURES)
    pop_rate = float(prior_b.coefficient("carbs_g")[0])
    pop_mean_rise, pop_sd = float(train["peak_glucose_rise"].mean()), float(train["peak_glucose_rise"].std(ddof=1))
    active_cut = float(train["activity_level"].median())

    perm = ev.copy()
    perm["activity_level"] = rng.permutation(ev["activity_level"].to_numpy())
    state = {"B": prior_b, "C": prior_c, "B_shuffled": prior_b, "C_perm_activity": prior_c}
    n_updates = Counter()
    rates: List[float] = []
    pending: List[tuple] = []
    rows = []

    def apply_due(now):
        nonlocal pending
        due = sorted([p for p in pending if p[0] <= now], key=lambda p: p[0])
        pending = [p for p in pending if p[0] > now]
        for _close, i in due:
            own = ev.iloc[[i]]
            state["B"] = conjugate_update(state["B"], own); state["C"] = conjugate_update(state["C"], own)
            state["C_perm_activity"] = conjugate_update(state["C_perm_activity"], perm.iloc[[i]])
            state["B_shuffled"] = conjugate_update(state["B_shuffled"], train.iloc[[int(rng.integers(len(train)))]])
            rates.append(float(own["peak_glucose_rise"].iloc[0] / max(float(own["carbs_g"].iloc[0]), 1.0)))
            n_updates["n"] += 1

    n = len(ev)
    for i, row in ev.iterrows():
        apply_due(row["meal_time"])
        base = float(row["baseline_glucose"])
        out = {}
        for name, feats, st, r in (("frozen_B", MODEL_B_FEATURES, prior_b, row), ("frozen_C", MODEL_C_FEATURES, prior_c, row),
                                   ("B", MODEL_B_FEATURES, state["B"], row), ("C", MODEL_C_FEATURES, state["C"], row),
                                   ("B_shuffled", MODEL_B_FEATURES, state["B_shuffled"], row),
                                   ("C_perm_activity", MODEL_C_FEATURES, state["C_perm_activity"], perm.iloc[i])):
            f = forecast_exceeds_180(st, r, base)
            out[name] = (f.probability_exceeds_180, f.mean_rise, f.predictive_std)
        rate = float(np.mean(rates)) if rates else pop_rate
        mean_pr = float(row["carbs_g"]) * rate
        out["personal_rate"] = (_normal_prob(base, mean_pr, float(np.sqrt(prior_b.noise_variance)), threshold), mean_pr, float(np.sqrt(prior_b.noise_variance)))
        out["population_constant"] = (_normal_prob(base, pop_mean_rise, pop_sd, threshold), pop_mean_rise, pop_sd)
        for name, (p, mean_rise, sd) in out.items():
            rows.append({"participant_id": pid, "event_id": row.get("event_id", f"{pid}-{i}"), "order": i, "model": name,
                         "p": p, "mean_rise": mean_rise, "pred_std": sd, "y": int(row["label_exceeds_180"]),
                         "rise": float(row["peak_glucose_rise"]), "n_personal_before": int(n_updates["n"]),
                         "is_second_half": bool(i >= n / 2), "activity": float(row["activity_level"]),
                         "is_active": bool(row["activity_level"] >= active_cut)})
        pending.append((row["meal_time"] + window, i))
    if include_model_a:
        proba = PopulationBaselineModel().fit(train).predict_proba(ev)          # trained without this participant
        for i, row in ev.iterrows():
            rows.append({"participant_id": pid, "event_id": row.get("event_id", f"{pid}-{i}"), "order": i, "model": MODEL_A,
                         "p": float(proba[i]), "mean_rise": np.nan, "pred_std": np.nan, "y": int(row["label_exceeds_180"]),
                         "rise": float(row["peak_glucose_rise"]), "n_personal_before": 0, "is_second_half": bool(i >= n / 2),
                         "activity": float(row["activity_level"]), "is_active": bool(row["activity_level"] >= active_cut)})
    return pd.DataFrame(rows)


def run_prequential_experiment(events: pd.DataFrame, participants: Optional[List[str]] = None, seed: int = 0,
                               min_events: int = 2, window: pd.Timedelta = OUTCOME_WINDOW,
                               include_model_a: bool = False) -> pd.DataFrame:
    """Leave-one-participant-out prequential run over every (or the given) participant."""
    _check(events)
    ids = sorted(events["participant_id"].unique()) if participants is None else list(participants)
    out = []
    for k, pid in enumerate(ids):
        ev = events[events["participant_id"] == pid]
        if len(ev) < min_events:
            continue
        out.append(prequential_participant(ev, events[events["participant_id"] != pid], window=window, seed=seed + k,
                                           include_model_a=include_model_a))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ----------------------------------------------------------------------------- metrics and CIs

def per_event_metric(records: pd.DataFrame, metric: str) -> pd.Series:
    if metric == "brier":
        return (records["p"] - records["y"]) ** 2
    if metric == "log_loss":
        p = records["p"].clip(1e-6, 1 - 1e-6)
        return -(records["y"] * np.log(p) + (1 - records["y"]) * np.log(1 - p))
    if metric == "mae_rise":
        return (records["mean_rise"] - records["rise"]).abs()
    raise ValueError(f"unknown metric {metric!r}; choose from {METRICS}")


def paired_cluster_bootstrap(records: pd.DataFrame, model_a: str, model_b: str, metric: str = "brier",
                             subset: Optional[pd.Series] = None, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict:
    """mean(metric_a - metric_b) over the same events, with a percentile CI from resampling PARTICIPANTS
    (events of one participant stay together). For these metrics lower is better: a negative estimate
    means model_a is better. An interval that contains 0 is inconclusive, not 'no effect'."""
    a = records[records["model"] == model_a].set_index("event_id")
    b = records[records["model"] == model_b].set_index("event_id")
    if subset is not None:
        keep = records.loc[subset & (records["model"] == model_a), "event_id"]
        a, b = a.loc[a.index.intersection(keep)], b.loc[b.index.intersection(keep)]
    a, b = a.loc[a.index.intersection(b.index)], b.loc[a.index.intersection(b.index)]
    if len(a) == 0:
        return {"n_events": 0, "n_participants": 0, "estimate": None, "ci_low": None, "ci_high": None}
    d = pd.DataFrame({"pid": a["participant_id"], "d": per_event_metric(a.reset_index(), metric).to_numpy()
                      - per_event_metric(b.reset_index(), metric).to_numpy()})
    g = d.groupby("pid")["d"].agg(["sum", "count"])
    sums, counts = g["sum"].to_numpy(), g["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g)))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    est = float(sums.sum() / counts.sum())
    return {"model_a": model_a, "model_b": model_b, "metric": metric, "n_events": int(counts.sum()), "n_participants": int(len(g)),
            "estimate": est, "ci_low": float(lo), "ci_high": float(hi), "n_boot": n_boot, "seed": seed,
            "interval_excludes_zero": bool(lo > 0 or hi < 0),
            "reading": "negative favours model_a" if est < 0 else "positive favours model_b"}


# ----------------------------------------------------------------------------- manifest

def build_manifest(params: Dict, events: pd.DataFrame, seed: int) -> dict:
    """Everything needed to reproduce a run, without any participant-level values. The table
    fingerprint is a hash, so a changed event table is detectable without publishing it."""
    cols = [c for c in REQUIRED + ["event_id"] if c in events.columns]
    canon = events[cols].sort_values([c for c in ("participant_id", "meal_time") if c in cols]).to_csv(index=False).encode()
    import scipy, sklearn, xgboost  # noqa: E401
    return {
        "seed": seed, "params": params, "n_events": int(len(events)), "n_participants": int(events["participant_id"].nunique()),
        "n_positive": int((events["label_exceeds_180"] == 1).sum()), "event_table_sha256": hashlib.sha256(canon).hexdigest(),
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                     "scipy": scipy.__version__, "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__},
        "models": MODELS, "threshold_mg_dl": GLUCOSE_THRESHOLD_MG_DL, "window_minutes": OUTCOME_WINDOW.total_seconds() / 60,
    }
