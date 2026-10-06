"""Model A: population-level XGBoost baseline, no personalization.

Deliberately simple: this is the blueprint's required non-personalized comparison
point for Models B/C, not an attempt at the best possible classifier. Same features
available to the Bayesian models (carbs, baseline glucose, activity) so the comparison
in the key experiment isolates the effect of personalization, not feature access.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb

BASELINE_FEATURE_COLUMNS = ["carbs_g", "baseline_glucose", "activity_level"]


class PopulationBaselineModel:
    """A thin, sklearn-style wrapper so callers (evaluation, API) don't need to know
    this is XGBoost specifically."""

    def __init__(self, **xgb_params) -> None:
        params = {
            "n_estimators": 100,
            "max_depth": 3,
            "learning_rate": 0.1,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": 0,  # reproducibility
            "n_jobs": 1,
        }
        params.update(xgb_params)
        self._model = xgb.XGBClassifier(**params)
        self._fitted = False

    def fit(self, df: pd.DataFrame) -> "PopulationBaselineModel":
        X = df[BASELINE_FEATURE_COLUMNS].to_numpy(dtype=float)
        y = df["label_exceeds_180"].to_numpy(dtype=int)
        if len(np.unique(y)) < 2:
            raise ValueError(
                "Model A requires both classes (label_exceeds_180 == 0 and == 1) present "
                "in the training data; got only one class."
            )
        self._model.fit(X, y)
        self._fitted = True
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("call fit() before predict_proba()")
        X = df[BASELINE_FEATURE_COLUMNS].to_numpy(dtype=float)
        return self._model.predict_proba(X)[:, 1]
