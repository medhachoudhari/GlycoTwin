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
from typing import Optional
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL, LABEL_TOLERANCE_MG_DL, OUTCOME_WINDOW
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
    # Additive, optional (defaults keep every existing call working): static, non-identifying profile labels supplied by the caller
    # (for example the glycaemic group), carried unchanged to every later version; and the explicit parent link of the version chain.
    profile: dict = field(default_factory=dict)
    parent_version: Optional[int] = None

    def carb_sensitivity_summary(self) -> dict:
        """LEGACY summary kept for compatibility. Read `interpretation` before using it.

        `model_c_carb_sensitivity` is the posterior of the Model C `carbs_g` COEFFICIENT, i.e. the sensitivity at activity =
        `model_c_reference_activity` (the prior's centre). For the blueprint (un-centred) Model C that reference is 0, an
        activity level that may lie outside the observed range, and the value is NOT comparable with Model B's sensitivity
        or with a typical person's sensitivity. For a sensitivity at a stated activity level, with the beta-gamma covariance
        in its uncertainty, use `glycotwin.twin.insight.twin_insight` / `effective_sensitivity`."""
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
            "interpretation": (
                "LEGACY summary. model_c_carb_sensitivity is the carbs_g coefficient, i.e. the sensitivity at "
                f"activity = {self.model_c.activity_center:g}"
                + (" (un-centred form: activity 0 may be outside the observed range, and this value is not comparable with Model B's sensitivity). "
                   if self.model_c.activity_center == 0.0 else " (the prior's centre). ")
                + "Use glycotwin.twin.insight.twin_insight for a sensitivity at a stated activity level with correct uncertainty."),
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
    # Additive (default empty): forecast-time data-quality / insufficient-history assessment from twin/quality.py. It is information
    # carried with the forecast; it never alters the probability or interval.
    data_quality: dict = field(default_factory=dict)


@dataclass
class ObservationRecord:
    forecast_id: str
    observed_peak_rise: float
    observed_exceeds_180: bool
    reconciled_at: datetime = field(default_factory=_utcnow)
    twin_version_after_update: int | None = None
    observation_quality: dict = field(default_factory=dict)       # additive: how completely the outcome window was observed


@dataclass
class ExclusionRecord:
    """Blueprint section 11 / 13: when the outcome window cannot be trusted (e.g. a sensor gap over 30 minutes) the meal is marked excluded
    with a reason and the twin is NOT updated. The forecast stays on record (it was made), but it never becomes training evidence."""
    forecast_id: str
    reason: str
    recorded_at: datetime = field(default_factory=_utcnow)


class TwinStore:
    """In-memory reference implementation. Any persistence backend (SQLite via
    SQLAlchemy, added in the backend stage) should implement this same interface so
    the twin/forecast/reconciliation logic above does not need to change."""

    def __init__(self) -> None:
        self._twin_history: dict[str, list[TwinState]] = {}
        self._forecasts: dict[str, ForecastRecord] = {}
        self._observations: dict[str, ObservationRecord] = {}
        self._exclusions: dict[str, ExclusionRecord] = {}

    def initialize_twin(
        self, participant_id: str, model_b_prior: BayesianLinearState, model_c_prior: BayesianLinearState,
        profile: Optional[dict] = None,
    ) -> TwinState:
        if participant_id in self._twin_history:
            raise ValueError(f"twin already initialized for participant {participant_id!r}")
        state = TwinState(participant_id=participant_id, model_b=model_b_prior, model_c=model_c_prior, version=0,
                          profile=dict(profile or {}), parent_version=None)
        self._twin_history[participant_id] = [state]
        return state

    def participants(self) -> list[str]:
        """Participant labels that have a twin, sorted (read-only; supports the patient-list view)."""
        return sorted(self._twin_history)

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

    def is_excluded(self, forecast_id: str) -> bool:
        return forecast_id in self._exclusions

    def save_exclusion(self, record: ExclusionRecord) -> None:
        self._exclusions[record.forecast_id] = record

    def exclusions(self, participant_id: str) -> list[ExclusionRecord]:
        mine = {fid for fid, f in self._forecasts.items() if f.participant_id == participant_id}
        return [e for fid, e in self._exclusions.items() if fid in mine]

    def _snapshot(self):
        """Shallow copy of the store's contents (stored versions and records are never mutated, so this is a faithful restore point)."""
        return ({k: list(v) for k, v in self._twin_history.items()}, dict(self._forecasts), dict(self._observations), dict(self._exclusions))

    def _restore(self, snapshot) -> None:
        history, forecasts, observations, exclusions = snapshot
        self._twin_history = {k: list(v) for k, v in history.items()}
        self._forecasts, self._observations, self._exclusions = dict(forecasts), dict(observations), dict(exclusions)

    def reconciliation_log(self, participant_id: str) -> list[ObservationRecord]:
        """Observations already reconciled for this participant, oldest twin version first (read-only view)."""
        mine = {fid for fid, f in self._forecasts.items() if f.participant_id == participant_id}
        obs = [o for fid, o in self._observations.items() if fid in mine]
        return sorted(obs, key=lambda o: (o.twin_version_after_update or 0))

    def pending_forecasts(self, participant_id: str) -> list[ForecastRecord]:
        """Forecasts made but not yet reconciled - used by the replay engine."""
        return [
            f
            for f in self._forecasts.values()
            if f.participant_id == participant_id and f.forecast_id not in self._observations and f.forecast_id not in self._exclusions
        ]


def forecast_meal(store: TwinStore, participant_id: str, meal_row: pd.Series) -> ForecastRecord:
    """Step 2-4 of the workflow: forecast P(exceed 180) from the twin's current
    posterior, under both Model B and Model C, and persist the forecast."""
    twin = store.current_twin(participant_id)
    baseline = float(meal_row["baseline_glucose"])

    b_forecast = forecast_exceeds_180(twin.model_b, meal_row, baseline)
    c_forecast = forecast_exceeds_180(twin.model_c, meal_row, baseline)

    from glycotwin.twin.quality import assess_forecast_quality            # local import: quality.py has no dependency on this module
    record = ForecastRecord(
        forecast_id=str(uuid.uuid4()),
        participant_id=participant_id,
        meal_time=meal_row["meal_time"],
        twin_version_at_forecast=twin.version,
        model_b_forecast=b_forecast,
        model_c_forecast=c_forecast,
        meal_row=meal_row,
        data_quality=assess_forecast_quality(meal_row, int(twin.model_c.n_observations_used)),
    )
    store.save_forecast(record)
    return record


def _observation_quality(meal_row: pd.Series) -> dict:
    from glycotwin.twin.quality import assess_observation_quality
    wc = meal_row["window_completeness"] if "window_completeness" in meal_row.index else None
    flag = meal_row["data_quality_flag"] if "data_quality_flag" in meal_row.index else None
    return assess_observation_quality(None if wc is None or pd.isna(wc) else wc, None if flag is None or pd.isna(flag) else str(flag))


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
        baseline_glucose + observed_peak_rise >= 180 (same event as the forecast target).
    """
    record = store.get_forecast(forecast_id)
    if store.is_reconciled(forecast_id):
        raise ValueError(f"forecast {forecast_id!r} was already reconciled")
    if store.is_excluded(forecast_id):
        raise ValueError(f"forecast {forecast_id!r} was marked excluded; an excluded meal never updates the twin")
    if observed_through is not None and observed_through < record.meal_time + OUTCOME_WINDOW:
        raise ValueError(
            f"observation window not complete: need CGM through meal_time + {OUTCOME_WINDOW}, "
            f"have data through {observed_through}"
        )
    if not np.isfinite(observed_peak_rise):
        raise ValueError("observed_peak_rise must be finite")
    baseline = float(record.meal_row["baseline_glucose"])
    if bool(baseline + observed_peak_rise >= GLUCOSE_THRESHOLD_MG_DL - LABEL_TOLERANCE_MG_DL) != bool(observed_exceeds_180):
        raise ValueError(
            "observed_exceeds_180 is inconsistent with baseline_glucose + observed_peak_rise >= 180"
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
        profile=dict(twin.profile),
        parent_version=twin.version,
    )
    store._save_new_version(new_state)
    store.save_observation(
        ObservationRecord(
            forecast_id=forecast_id,
            observed_peak_rise=observed_peak_rise,
            observed_exceeds_180=bool(observed_exceeds_180),
            twin_version_after_update=new_version,
            observation_quality=_observation_quality(record.meal_row),
        )
    )
    return new_state


def exclude_forecast(store: TwinStore, forecast_id: str, reason: str, observed_through: pd.Timestamp | None = None) -> ExclusionRecord:
    """Blueprint decision branch "Sensor gap over 30 min? Yes -> Mark excluded, no update": record that this forecast's outcome is untrustworthy
    and leave the twin exactly as it is (no new version, no parameter change). Same guards as reconciliation: once only, never after a
    reconcile, and (if `observed_through` is given) only once the outcome window has closed."""
    record = store.get_forecast(forecast_id)
    if not str(reason).strip():
        raise ValueError("an exclusion needs a reason")
    if store.is_reconciled(forecast_id):
        raise ValueError(f"forecast {forecast_id!r} was already reconciled and cannot be excluded")
    if store.is_excluded(forecast_id):
        raise ValueError(f"forecast {forecast_id!r} was already excluded")
    if observed_through is not None and observed_through < record.meal_time + OUTCOME_WINDOW:
        raise ValueError(f"observation window not complete: need CGM through meal_time + {OUTCOME_WINDOW}, have data through {observed_through}")
    ex = ExclusionRecord(forecast_id=forecast_id, reason=str(reason).strip())
    store.save_exclusion(ex)
    return ex
