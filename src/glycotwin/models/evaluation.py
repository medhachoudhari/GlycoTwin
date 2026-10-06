"""Calibration/discrimination metrics for comparing Models A/B/C honestly.

No metric here decides a "winner" - they are reported together, and
compare_models_on_activity_strata explicitly separates active-day vs. sedentary-day
calibration for the key experiment. Small-sample results are flagged, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

MIN_SAMPLES_FOR_METRIC = 10  # below this, a metric is not meaningfully estimable
MIN_POSITIVES_FOR_DISCRIMINATION = 2  # AUROC/AUPRC need both classes present


@dataclass
class ReliabilityBin:
    bin_lower: float
    bin_upper: float
    n_samples: int
    mean_predicted: float | None
    mean_observed: float | None


@dataclass
class EvaluationResult:
    n_samples: int
    n_positives: int
    auroc: float | None
    auprc: float | None
    brier_score: float | None
    expected_calibration_error: float | None
    reliability_bins: list[ReliabilityBin]
    warnings: list[str]


def expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> tuple[float, list[ReliabilityBin]]:
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(y_prob, bin_edges[1:-1], right=True), 0, n_bins - 1)

    ece = 0.0
    bins = []
    n = len(y_true)
    for b in range(n_bins):
        mask = bin_idx == b
        count = int(mask.sum())
        if count == 0:
            bins.append(ReliabilityBin(bin_edges[b], bin_edges[b + 1], 0, None, None))
            continue
        mean_pred = float(y_prob[mask].mean())
        mean_obs = float(y_true[mask].mean())
        ece += (count / n) * abs(mean_pred - mean_obs)
        bins.append(ReliabilityBin(bin_edges[b], bin_edges[b + 1], count, mean_pred, mean_obs))
    return float(ece), bins


def evaluate_predictions(y_true: pd.Series | np.ndarray, y_prob: pd.Series | np.ndarray) -> EvaluationResult:
    """Compute AUROC, AUPRC, Brier score, and ECE, honestly reporting when the sample
    is too small or too imbalanced for a metric to be meaningful (returns None for
    that metric plus a warning, rather than a misleading number)."""
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    if len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must be the same length")

    n = len(y_true)
    n_pos = int(y_true.sum())
    warnings: list[str] = []

    if n < MIN_SAMPLES_FOR_METRIC:
        warnings.append(f"only {n} samples (< {MIN_SAMPLES_FOR_METRIC}); all metrics are unreliable.")

    auroc = auprc = None
    if n_pos < MIN_POSITIVES_FOR_DISCRIMINATION or n_pos > n - MIN_POSITIVES_FOR_DISCRIMINATION:
        warnings.append(
            f"only {n_pos}/{n} positives; AUROC/AUPRC require both classes well represented "
            "and are not reported."
        )
    else:
        auroc = float(roc_auc_score(y_true, y_prob))
        auprc = float(average_precision_score(y_true, y_prob))

    brier = float(brier_score_loss(y_true, y_prob)) if n > 0 else None
    ece, bins = expected_calibration_error(y_true, y_prob) if n > 0 else (None, [])

    return EvaluationResult(
        n_samples=n,
        n_positives=n_pos,
        auroc=auroc,
        auprc=auprc,
        brier_score=brier,
        expected_calibration_error=ece,
        reliability_bins=bins,
        warnings=warnings,
    )


def compare_models_on_activity_strata(
    df: pd.DataFrame, predictions: dict[str, np.ndarray], active_threshold: float
) -> dict[str, dict[str, EvaluationResult]]:
    """The key experiment: for each model's predictions, evaluate separately on
    active-day meals (activity_level >= active_threshold) vs. sedentary-day meals.
    `active_threshold` is a parameter, not a hardcoded assumption - choosing it from
    real data distribution is part of the pending real-data validation work.

    Returns {model_name: {"active": EvaluationResult, "sedentary": EvaluationResult}}.
    """
    is_active = df["activity_level"].to_numpy(dtype=float) >= active_threshold
    results: dict[str, dict[str, EvaluationResult]] = {}
    for model_name, y_prob in predictions.items():
        y_prob = np.asarray(y_prob, dtype=float)
        y_true = df["label_exceeds_180"].to_numpy(dtype=int)
        results[model_name] = {
            "active": evaluate_predictions(y_true[is_active], y_prob[is_active]),
            "sedentary": evaluate_predictions(y_true[~is_active], y_prob[~is_active]),
        }
    return results
