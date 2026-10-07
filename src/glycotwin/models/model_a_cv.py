"""Model A evaluation: participant-level, group-stratified 5-fold cross-validation with out-of-fold predictions.

Model A is the population-level XGBoost baseline (`PopulationBaselineModel`, features carbs_g, baseline_glucose,
activity_level; fixed configuration, no tuning). It is a research baseline, not a clinically validated model.

Protocol
  * Participants (not events) are assigned to folds with sklearn StratifiedKFold(shuffle=True, random_state=seed),
    stratified by the participant's glycaemic group; participants are sorted by id first so the assignment does not
    depend on row order. A participant is in exactly one fold, hence never in both training and validation.
  * Every event gets one out-of-fold probability from a model fitted on the other folds' participants only.
  * Missing predictors are left as NaN; XGBoost's native missing-value handling is used. Nothing is imputed.
  * No resampling, no class weighting, no threshold change. Probabilities are raw (uncalibrated).
  * Threshold-dependent metrics need a decision threshold. Two conventions are fixed in advance and both are
    reported: 0.5, and the training-fold prevalence (known from training data only). Neither is tuned.
Group results are descriptive; no inference or superiority claim is made from them.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import StratifiedKFold

from glycotwin.data.events import ELIGIBILITY_COLUMNS, FEATURE_COLUMNS, OUTCOME_COLUMNS, RETAINED_RAW_COLUMNS
from glycotwin.models.baseline import BASELINE_FEATURE_COLUMNS, PopulationBaselineModel
from glycotwin.models.evaluation import evaluate_predictions, expected_calibration_error

TARGET = "label_exceeds_180"
MODEL_A_FEATURES: List[str] = list(BASELINE_FEATURE_COLUMNS)
N_SPLITS = 5
DEFAULT_THRESHOLD = 0.5
ID_AND_GROUP_COLUMNS = {"participant_id", "event_id", "meal_time", "label_raw", "label_norm", "group", "glycaemic_group", "subject"}
FORBIDDEN_FEATURES = (set(OUTCOME_COLUMNS) | set(ELIGIBILITY_COLUMNS) | set(RETAINED_RAW_COLUMNS) | ID_AND_GROUP_COLUMNS
                      | {TARGET, "peak_glucose", "peak_glucose_rise", "Amount Consumed", "Image path"})


class FeaturePolicyError(ValueError):
    pass


def assert_feature_policy(features: List[str]) -> None:
    """Features must come from the established pre-meal feature list and never include outcomes, eligibility flags,
    identifiers, group labels, Amount Consumed or image paths."""
    bad = [f for f in features if f in FORBIDDEN_FEATURES]
    if bad:
        raise FeaturePolicyError(f"forbidden feature columns: {bad}")
    unknown = [f for f in features if f not in FEATURE_COLUMNS]
    if unknown:
        raise FeaturePolicyError(f"columns not in the established pre-meal FEATURE_COLUMNS: {unknown}")
    if len(set(features)) != len(features):
        raise FeaturePolicyError("duplicate feature columns")


# ----------------------------------------------------------------------------- folds

def make_participant_folds(group_of: Dict[str, str], n_splits: int = N_SPLITS, seed: int = 0) -> Dict[str, int]:
    """participant_id -> fold (0..n_splits-1), stratified by glycaemic group, deterministic for a given seed."""
    ids = sorted(group_of)
    groups = np.array([group_of[p] for p in ids])
    counts = pd.Series(groups).value_counts()
    if (counts < n_splits).any():
        raise ValueError(f"every group needs at least {n_splits} participants for stratified {n_splits}-fold; got {counts.to_dict()}")
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    folds = {}
    for k, (_train, val) in enumerate(skf.split(np.zeros(len(ids)), groups)):
        for i in val:
            folds[ids[i]] = k
    return folds


def fold_assignment_hash(folds: Dict[str, int]) -> str:
    return hashlib.sha256("\n".join(f"{p}:{folds[p]}" for p in sorted(folds)).encode()).hexdigest()


def fold_composition(events: pd.DataFrame, folds: Dict[str, int], group_of: Dict[str, str], n_splits: int = N_SPLITS) -> List[dict]:
    ev = events.assign(_fold=events["participant_id"].map(folds))
    rows = []
    for k in range(n_splits):
        pk = [p for p, f in folds.items() if f == k]
        e = ev[ev["_fold"] == k]
        per_part = e.groupby("participant_id")[TARGET].agg(["min", "max"]) if len(e) else pd.DataFrame(columns=["min", "max"])
        rows.append({
            "fold": k, "n_participants": len(pk), "participants_by_group": {g: sum(group_of[p] == g for p in pk) for g in sorted(set(group_of.values()))},
            "n_events": int(len(e)), "n_positive": int((e[TARGET] == 1).sum()), "n_negative": int((e[TARGET] == 0).sum()),
            "prevalence": float((e[TARGET] == 1).mean()) if len(e) else None,
            "participants_with_both_classes": int(((per_part["min"] == 0) & (per_part["max"] == 1)).sum()) if len(per_part) else 0,
        })
    return rows


# ----------------------------------------------------------------------------- out-of-fold predictions

def cross_validated_predictions(events: pd.DataFrame, folds: Dict[str, int], model_factory: Optional[Callable] = None,
                                n_splits: int = N_SPLITS) -> pd.DataFrame:
    """One out-of-fold probability per event. The held-out fold's participants are never in training."""
    assert_feature_policy(MODEL_A_FEATURES)
    missing_cols = [c for c in MODEL_A_FEATURES + [TARGET, "participant_id", "event_id"] if c not in events.columns]
    if missing_cols:
        raise ValueError(f"event table is missing columns: {missing_cols}")
    unmapped = set(events["participant_id"]) - set(folds)
    if unmapped:
        raise ValueError(f"{len(unmapped)} participants have no fold")
    factory = model_factory or (lambda: PopulationBaselineModel())
    ev = events.sort_values(["participant_id", "event_id"], kind="stable").reset_index(drop=True)
    ev["fold"] = ev["participant_id"].map(folds).astype(int)
    parts = []
    for k in range(n_splits):
        train, val = ev[ev["fold"] != k], ev[ev["fold"] == k]
        if set(train["participant_id"]) & set(val["participant_id"]):
            raise AssertionError("a participant is in both training and validation")
        if len(val) == 0:
            continue
        model = factory().fit(train)
        out = val[["event_id", "participant_id", "fold", TARGET]].rename(columns={TARGET: "y"}).copy()
        out["p"] = model.predict_proba(val)
        out["fold_train_prevalence"] = float((train[TARGET] == 1).mean())
        parts.append(out)
    oof = pd.concat(parts, ignore_index=True)
    if len(oof) != len(ev) or oof["event_id"].duplicated().any():
        raise AssertionError("out-of-fold coverage is not exactly one prediction per event")
    return oof


# ----------------------------------------------------------------------------- metrics

def classification_metrics(y, p, threshold) -> dict:
    """Confusion matrix and threshold metrics. A metric whose denominator is zero is None with the reason stated."""
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    pred = (p >= np.asarray(threshold)).astype(int)
    tp, fn = int(((y == 1) & (pred == 1)).sum()), int(((y == 1) & (pred == 0)).sum())
    fp, tn = int(((y == 0) & (pred == 1)).sum()), int(((y == 0) & (pred == 0)).sum())
    undefined = {}

    def ratio(name, num, den, why):
        if den == 0:
            undefined[name] = why
            return None
        return float(num / den)
    sens = ratio("sensitivity", tp, tp + fn, "no positive events")
    spec = ratio("specificity", tn, tn + fp, "no negative events")
    prec = ratio("precision", tp, tp + fp, "no events predicted positive")
    f1 = ratio("f1", 2 * tp, 2 * tp + fp + fn, "no positives and none predicted positive")
    return {"threshold": float(np.mean(threshold)) if np.ndim(threshold) else float(threshold),
            "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
            "sensitivity_recall": sens, "specificity": spec, "precision": prec, "f1": f1,
            "n_predicted_positive": tp + fp, "undefined": undefined}


def calibration_slope_intercept(y, p) -> dict:
    """Logistic recalibration y ~ a + b*logit(p): slope b (1 = ideal) and intercept a (0 = ideal). None when not estimable."""
    y, p = np.asarray(y, dtype=int), np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    z = np.log(p / (1 - p)).reshape(-1, 1)
    if len(np.unique(y)) < 2 or np.ptp(z) < 1e-9:
        return {"slope": None, "intercept": None, "reason": "single class or constant predictions"}
    lr = LogisticRegression(C=np.inf, solver="lbfgs", max_iter=1000).fit(z, y)
    return {"slope": float(lr.coef_[0, 0]), "intercept": float(lr.intercept_[0]), "reason": None}


def metric_bundle(y, p, threshold: float = DEFAULT_THRESHOLD, threshold_by_event=None) -> dict:
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    ev = evaluate_predictions(y, p)
    n = len(y)
    out = {"n_events": n, "n_positive": int(y.sum()), "n_negative": int(n - y.sum()), "prevalence": float(y.mean()) if n else None,
           "mean_predicted_probability": float(p.mean()) if n else None,
           "roc_auc": ev.auroc, "average_precision_pr_auc": ev.auprc, "brier_score": ev.brier_score,
           "brier_score_of_constant_prevalence_forecast": float(y.mean() * (1 - y.mean())) if n else None,
           "log_loss": float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])) if n else None,
           "ece_10_bins": ev.expected_calibration_error,
           "ece_5_bins": float(expected_calibration_error(y, p, n_bins=5)[0]) if n else None,
           "calibration": calibration_slope_intercept(y, p) if n else {"slope": None, "intercept": None, "reason": "no events"},
           "reliability_bins_10": [{"lower": b.bin_lower, "upper": b.bin_upper, "n": b.n_samples, "mean_predicted": b.mean_predicted,
                                    "mean_observed": b.mean_observed} for b in ev.reliability_bins],
           "warnings": ev.warnings,
           f"classification_at_{threshold}": classification_metrics(y, p, threshold)}
    if threshold_by_event is not None:
        out["classification_at_training_fold_prevalence"] = classification_metrics(y, p, threshold_by_event)
    return out


def _is_undefined(m: dict) -> list:
    return [k for k in ("roc_auc", "average_precision_pr_auc", "brier_score") if m.get(k) is None]


def per_fold_metrics(oof: pd.DataFrame, threshold: float = DEFAULT_THRESHOLD) -> List[dict]:
    rows = []
    for k, g in oof.groupby("fold"):
        m = metric_bundle(g["y"], g["p"], threshold, g["fold_train_prevalence"].to_numpy())
        rows.append({"fold": int(k), **{x: m[x] for x in ("n_events", "n_positive", "n_negative", "prevalence", "roc_auc",
                                                           "average_precision_pr_auc", "brier_score", "ece_10_bins")},
                     "calibration_slope": m["calibration"]["slope"], "undefined_metrics": _is_undefined(m), "warnings": m["warnings"]})
    return rows


def group_metrics(oof: pd.DataFrame, group_of: Dict[str, str], threshold: float = DEFAULT_THRESHOLD) -> Dict[str, dict]:
    o = oof.assign(group=oof["participant_id"].map(group_of))
    out = {}
    for g in sorted(set(group_of.values())):
        s = o[o["group"] == g]
        m = metric_bundle(s["y"], s["p"], threshold, s["fold_train_prevalence"].to_numpy())
        m["n_participants"] = int(s["participant_id"].nunique())
        m["participants_with_both_classes"] = int(((s.groupby("participant_id")["y"].agg(["min", "max"]).pipe(lambda d: (d["min"] == 0) & (d["max"] == 1))).sum())) if len(s) else 0
        m["undefined_metrics"] = _is_undefined(m)
        m["note"] = "descriptive only; subgroup sizes are small and no superiority or significance is claimed"
        out[g] = m
    return out


def bootstrap_ci(oof: pd.DataFrame, n_boot: int = 1000, seed: int = 0, alpha: float = 0.05) -> dict:
    """Participant-clustered percentile intervals for the pooled OOF ROC-AUC, average precision and Brier score.
    Resamples participants with replacement; draws without both classes are skipped and counted."""
    rng = np.random.default_rng(seed)
    ids = np.array(sorted(oof["participant_id"].unique()))
    by = {p: g for p, g in oof.groupby("participant_id")}
    vals = {"roc_auc": [], "average_precision_pr_auc": [], "brier_score": []}
    skipped = 0
    for _ in range(n_boot):
        s = pd.concat([by[p] for p in rng.choice(ids, size=len(ids), replace=True)])
        m = evaluate_predictions(s["y"].to_numpy(), s["p"].to_numpy())
        if m.auroc is None:
            skipped += 1
            continue
        vals["roc_auc"].append(m.auroc); vals["average_precision_pr_auc"].append(m.auprc); vals["brier_score"].append(m.brier_score)
    out = {"n_boot": n_boot, "seed": seed, "n_draws_used": n_boot - skipped, "n_draws_skipped_single_class": skipped, "level": 1 - alpha}
    for k, v in vals.items():
        out[k] = ({"low": float(np.quantile(v, alpha / 2)), "high": float(np.quantile(v, 1 - alpha / 2))} if v else None)
    return out


# ----------------------------------------------------------------------------- manifest

def _git_state() -> dict:
    try:
        root = Path(__file__).resolve().parents[3]
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip())
        return {"git_commit": head or None, "working_tree_dirty": dirty}
    except Exception:  # noqa: BLE001
        return {"git_commit": None, "working_tree_dirty": None}


def event_table_fingerprint(events: pd.DataFrame) -> str:
    cols = ["participant_id", "event_id", "meal_time"] + MODEL_A_FEATURES + [TARGET]
    canon = events[cols].sort_values(["participant_id", "event_id"]).to_csv(index=False).encode()
    return hashlib.sha256(canon).hexdigest()


def build_manifest(events: pd.DataFrame, folds: Dict[str, int], seed: int, channel: str, event_table_name: str,
                   threshold: float, model_factory: Optional[Callable] = None) -> dict:
    import scipy, sklearn, xgboost  # noqa: E401
    model = (model_factory or (lambda: PopulationBaselineModel()))()
    params = getattr(getattr(model, "_model", None), "get_params", lambda: {})()
    return {
        "model": "A: population-level XGBoost classifier (research baseline; not clinically validated)",
        "cgm_channel": channel, "event_table_file_name": event_table_name,
        "event_table_sha256_of_model_a_columns": event_table_fingerprint(events),
        "n_events": int(len(events)), "n_participants": int(events["participant_id"].nunique()),
        "seed_for_folds": seed, "n_splits": N_SPLITS, "fold_method": "StratifiedKFold(shuffle=True, random_state=seed) over participants sorted by id, stratified by glycaemic group",
        "fold_assignment_sha256": fold_assignment_hash(folds),
        "feature_columns": MODEL_A_FEATURES, "target": TARGET,
        "missing_value_policy": "no imputation; NaN passed to XGBoost's native missing-value handling",
        "class_imbalance_policy": "none (no resampling, no class weights, target threshold unchanged)",
        "xgboost_params": {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)) for k, v in sorted(params.items())},
        "decision_thresholds_reported": [threshold, "training-fold prevalence"],
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                     "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__},
        **_git_state(),
    }


def feature_missingness(events: pd.DataFrame) -> dict:
    return {f: {"n_missing": int(events[f].isna().sum()), "share_missing": float(events[f].isna().mean())} for f in MODEL_A_FEATURES}


def run_model_a(events: pd.DataFrame, group_of: Dict[str, str], seed: int = 0, threshold: float = DEFAULT_THRESHOLD,
                n_boot: int = 1000, channel: str = "Libre GL", event_table_name: str = "",
                model_factory: Optional[Callable] = None) -> tuple[dict, pd.DataFrame, Dict[str, int]]:
    """The whole protocol on an already-filtered event table (core-eligible events). Returns (report, oof, folds)."""
    events = events.copy()
    events[TARGET] = events[TARGET].astype(int)
    folds = make_participant_folds({p: group_of[p] for p in events["participant_id"].unique()}, N_SPLITS, seed)
    oof = cross_validated_predictions(events, folds, model_factory)
    overall = metric_bundle(oof["y"], oof["p"], threshold, oof["fold_train_prevalence"].to_numpy())
    both = events.groupby("participant_id")[TARGET].agg(["min", "max"])
    report = {
        "_privacy": "aggregate-only: no participant identifiers, timestamps or per-event values",
        "_status": "RESEARCH BASELINE. Not clinically validated. Out-of-fold results only; no training-set metric is a result.",
        "manifest": build_manifest(events, folds, seed, channel, event_table_name, threshold, model_factory),
        "data": {"n_events": int(len(events)), "n_participants": int(events["participant_id"].nunique()),
                 "n_positive": int(events[TARGET].sum()), "n_negative": int((events[TARGET] == 0).sum()),
                 "prevalence": float(events[TARGET].mean()),
                 "participants_with_both_classes": int(((both["min"] == 0) & (both["max"] == 1)).sum()),
                 "participants_by_group": {g: int(sum(group_of[p] == g for p in events["participant_id"].unique())) for g in sorted(set(group_of.values()))},
                 "feature_missingness": feature_missingness(events)},
        "fold_composition": fold_composition(events, folds, group_of),
        "overall_out_of_fold": overall,
        "overall_out_of_fold_participant_bootstrap_95ci": bootstrap_ci(oof, n_boot, seed),
        "per_fold": per_fold_metrics(oof, threshold),
        "by_glycaemic_group": group_metrics(oof, group_of, threshold),
    }
    return report, oof, folds
