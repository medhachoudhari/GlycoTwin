"""Versioned per-participant digital twin state, forecasts, and reconciliation.

Workflow this module implements (steps 3-7 of the blueprint's core workflow):
    1. forecast_meal(): given a logged meal, use the twin's *current* posterior
       (Model B and/or C) to forecast P(exceed 180) with uncertainty, and record it.
    2. Two hours later, once the observed CGM trace is available: reconcile_forecast()
       compares the forecast to what was observed, then calls the closed-form Bayesian
       update (glycotwin.models.bayesian.conjugate_update) with *only that one new
       meal* - never refitting from scratch - and saves a *new version* of the twin.

Persistence note: this module defines the state/record shapes and an in-memory
TwinStore implementing them. SQLite persistence (so state survives process restarts)
is a separate, not-yet-implemented stage: a SQLAlchemy-backed store implementing the
same TwinStore interface. Nothing here claims cross-restart persistence today.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL, OUTCOME_WINDOW
from glycotwin.models.bayesian import (
    MODEL_B_FEATURES,
    MODEL_C_FEATURES,
    BayesianLinearState,
    ForecastDistribution,
    conjugate_update,
    forecast_exceeds_180,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TwinState:
    """One versioned snapshot of a participant's personalization. A new meal
    reconciliation produces a new TwinState with version = previous.version + 1; the
    previous version is never overwritten, matching 'save a new version ... rather
    than recomputing from scratch'."""

    participant_id: str
    model_b: BayesianLinearState
    model_c: BayesianLinearState
    version: int
    created_at: datetime = field(default_factory=_utcnow)

    def carb_sensitivity_summary(self) -> dict:
        """What the twin-state card displays: current sensitivity +/- uncertainty."""
        b_mean, b_std = self.model_b.coefficient("carbs_g")
        c_mean, c_std = self.model_c.coefficient("carbs_g")
        c_interact_mean, c_interact_std = self.model_c.coefficient("carbs_x_activity")
        return {
            "version": self.version,
            # Model C's carb coefficient is the sensitivity at this activity level
            # (the centre used by the prior), not at activity = 0.
            "model_c_reference_activity": self.model_c.activity_center,
            "model_b_carb_sensitivity": {"mean": b_mean, "std": b_std},
            "model_c_carb_sensitivity": {"mean": c_mean, "std": c_std},
            "model_c_activity_interaction": {"mean": c_interact_mean, "std": c_interact_std},
        }


@dataclass
class ForecastRecord:
    forecast_id: str
    participant_id: str
    meal_time: pd.Timestamp
    twin_version_at_forecast: int
    model_b_forecast: ForecastDistribution
    model_c_forecast: ForecastDistribution
    meal_row: pd.Series  # the features the forecast was made from; needed to reconcile
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class ObservationRecord:
    forecast_id: str
    observed_peak_rise: float
    observed_exceeds_180: bool
    reconciled_at: datetime = field(default_factory=_utcnow)
    twin_version_after_update: int | None = None


class TwinStore:
    """In-memory reference implementation. Any persistence backend (SQLite via
    SQLAlchemy, added in the backend stage) should implement this same interface so
    the twin/forecast/reconciliation logic above does not need to change."""

    def __init__(self) -> None:
        self._twin_history: dict[str, list[TwinState]] = {}
        self._forecasts: dict[str, ForecastRecord] = {}
        self._observations: dict[str, ObservationRecord] = {}

    def initialize_twin(
        self, participant_id: str, model_b_prior: BayesianLinearState, model_c_prior: BayesianLinearState
    ) -> TwinState:
        if participant_id in self._twin_history:
            raise ValueError(f"twin already initialized for participant {participant_id!r}")
        state = TwinState(participant_id=participant_id, model_b=model_b_prior, model_c=model_c_prior, version=0)
        self._twin_history[participant_id] = [state]
        return state

    def current_twin(self, participant_id: str) -> TwinState:
        history = self._twin_history.get(participant_id)
        if not history:
            raise KeyError(f"no twin state for participant {participant_id!r}; call initialize_twin() first")
        return history[-1]

    def twin_history(self, participant_id: str) -> list[TwinState]:
        return list(self._twin_history.get(participant_id, []))

    def _save_new_version(self, state: TwinState) -> None:
        self._twin_history.setdefault(state.participant_id, []).append(state)

    def save_forecast(self, record: ForecastRecord) -> None:
        self._forecasts[record.forecast_id] = record

    def get_forecast(self, forecast_id: str) -> ForecastRecord:
        return self._forecasts[forecast_id]

    def save_observation(self, record: ObservationRecord) -> None:
        self._observations[record.forecast_id] = record

    def is_reconciled(self, forecast_id: str) -> bool:
        return forecast_id in self._observations

    def pending_forecasts(self, participant_id: str) -> list[ForecastRecord]:
        """Forecasts made but not yet reconciled - used by the replay engine."""
        return [
            f
            for f in self._forecasts.values()
            if f.participant_id == participant_id and f.forecast_id not in self._observations
        ]


def forecast_meal(store: TwinStore, participant_id: str, meal_row: pd.Series) -> ForecastRecord:
    """Step 2-4 of the workflow: forecast P(exceed 180) from the twin's current
    posterior, under both Model B and Model C, and persist the forecast."""
    twin = store.current_twin(participant_id)
    baseline = float(meal_row["baseline_glucose"])

    b_forecast = forecast_exceeds_180(twin.model_b, meal_row, baseline)
    c_forecast = forecast_exceeds_180(twin.model_c, meal_row, baseline)

    record = ForecastRecord(
        forecast_id=str(uuid.uuid4()),
        participant_id=participant_id,
        meal_time=meal_row["meal_time"],
        twin_version_at_forecast=twin.version,
        model_b_forecast=b_forecast,
        model_c_forecast=c_forecast,
        meal_row=meal_row,
    )
    store.save_forecast(record)
    return record


def reconcile_forecast(
    store: TwinStore,
    forecast_id: str,
    observed_peak_rise: float,
    observed_exceeds_180: bool,
    observed_through: pd.Timestamp | None = None,
) -> TwinState:
    """Steps 5-7 of the workflow: compare the forecast to the observed trace, run the
    closed-form Bayesian update using only this one new meal, and save a *new*
    TwinState version (the old version stays in twin_history, untouched).

    Guards (each raises ValueError/KeyError rather than silently corrupting the twin):
      * a forecast can be reconciled once - a second call would count the same meal twice;
      * if `observed_through` (the latest CGM time available) is given, it must reach
        meal_time + OUTCOME_WINDOW, otherwise the outcome is not yet fully observed;
      * the observed outcome must be finite and `observed_exceeds_180` must agree with
        baseline_glucose + observed_peak_rise > 180 (same event as the forecast target).
    """
    record = store.get_forecast(forecast_id)
    if store.is_reconciled(forecast_id):
        raise ValueError(f"forecast {forecast_id!r} was already reconciled")
    if observed_through is not None and observed_through < record.meal_time + OUTCOME_WINDOW:
        raise ValueError(
            f"observation window not complete: need CGM through meal_time + {OUTCOME_WINDOW}, "
            f"have data through {observed_through}"
        )
    if not np.isfinite(observed_peak_rise):
        raise ValueError("observed_peak_rise must be finite")
    baseline = float(record.meal_row["baseline_glucose"])
    if bool(baseline + observed_peak_rise > GLUCOSE_THRESHOLD_MG_DL) != bool(observed_exceeds_180):
        raise ValueError(
            "observed_exceeds_180 is inconsistent with baseline_glucose + observed_peak_rise > 180"
        )

    twin = store.current_twin(record.participant_id)
    observation_df = record.meal_row.to_frame().T.copy()
    observation_df["peak_glucose_rise"] = observed_peak_rise

    new_version = twin.version + 1
    new_state = TwinState(
        participant_id=twin.participant_id,
        model_b=conjugate_update(twin.model_b, observation_df),
        model_c=conjugate_update(twin.model_c, observation_df),
        version=new_version,
    )
    store._save_new_version(new_state)
    store.save_observation(
        ObservationRecord(
            forecast_id=forecast_id,
            observed_peak_rise=observed_peak_rise,
            observed_exceeds_180=bool(observed_exceeds_180),
            twin_version_after_update=new_version,
        )
    )
    return new_state
