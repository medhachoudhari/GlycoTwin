"""Relational schema (SQLAlchemy 2.0 ORM).

twins                   profile and configuration of one live twin (pseudonymous label, prior provenance, settings)
twin_states             versioned snapshots (version 0 = prior; one new version per reconciled meal), parent link, append-only
parameter_snapshots     the Bayesian posterior of Model B and Model C at each version (mean, covariance, noise, counts)
forecasts               one per (twin, client event id): inputs, both models' predictive distributions, version used, provenance
observations            the observed outcome submitted for a forecast (at most one per forecast)
reconciliations         the result of reconciling a forecast with its observation (at most one per forecast and per observation)
what_if_runs            hypothetical scenarios and results; never linked to a state change
data_quality_flags      forecast-time and observation-time quality findings, with their stage
Uniqueness constraints are the duplicate-processing guards: (twin_id, event_id), (twin_id, version), one observation and one reconciliation per forecast.
No raw CGM traces are stored; only the per-meal summaries the engine needs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from glycotwin.backend.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Twin(Base):
    __tablename__ = "twins"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prior_source: Mapped[str] = mapped_column(String(32))                    # synthetic_demo | prior_file
    prior_scheme: Mapped[str] = mapped_column(String(32))                    # empirical_bayes | blueprint
    gamma_relative_sd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prior_provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)                 # static, non-identifying labels only
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    states: Mapped[list["TwinStateRow"]] = relationship(back_populates="twin", order_by="TwinStateRow.version", cascade="all, delete-orphan")
    forecasts: Mapped[list["ForecastRow"]] = relationship(back_populates="twin", cascade="all, delete-orphan")


class TwinStateRow(Base):
    __tablename__ = "twin_states"
    __table_args__ = (UniqueConstraint("twin_id", "version", name="uq_twin_version"), Index("ix_twin_states_twin_version", "twin_id", "version"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twins.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    n_observations: Mapped[int] = mapped_column(Integer, default=0)
    reconciliation_id: Mapped[Optional[str]] = mapped_column(ForeignKey("reconciliations.id"), nullable=True)
    twin: Mapped[Twin] = relationship(back_populates="states")
    parameters: Mapped[list["ParameterSnapshot"]] = relationship(back_populates="state", cascade="all, delete-orphan")


class ParameterSnapshot(Base):
    __tablename__ = "parameter_snapshots"
    __table_args__ = (UniqueConstraint("twin_state_id", "model", name="uq_state_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    twin_state_id: Mapped[int] = mapped_column(ForeignKey("twin_states.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(1))                             # B | C
    feature_names: Mapped[list] = mapped_column(JSON)
    mean: Mapped[list] = mapped_column(JSON)
    covariance: Mapped[list] = mapped_column(JSON)
    noise_variance: Mapped[float] = mapped_column(Float)
    activity_center: Mapped[float] = mapped_column(Float, default=0.0)
    n_observations_used: Mapped[int] = mapped_column(Integer, default=0)
    prior_source: Mapped[str] = mapped_column(String(64))
    beta_mean: Mapped[float] = mapped_column(Float)
    beta_var: Mapped[float] = mapped_column(Float)
    gamma_mean: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gamma_var: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    beta_gamma_cov: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[TwinStateRow] = relationship(back_populates="parameters")


class ForecastRow(Base):
    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("twin_id", "event_id", name="uq_twin_event"), Index("ix_forecasts_twin_time", "twin_id", "meal_time"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)                    # the engine's forecast_id
    twin_id: Mapped[str] = mapped_column(ForeignKey("twins.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(64))
    meal_time: Mapped[datetime] = mapped_column(DateTime)
    inputs: Mapped[dict] = mapped_column(JSON)
    input_sha256: Mapped[str] = mapped_column(String(64))
    twin_version_at_forecast: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    model_version: Mapped[str] = mapped_column(String(128))
    engine_provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    data_quality: Mapped[dict] = mapped_column(JSON, default=dict)
    b_probability: Mapped[float] = mapped_column(Float)
    b_mean_rise: Mapped[float] = mapped_column(Float)
    b_sd: Mapped[float] = mapped_column(Float)
    b_interval_low: Mapped[float] = mapped_column(Float)
    b_interval_high: Mapped[float] = mapped_column(Float)
    c_probability: Mapped[float] = mapped_column(Float)
    c_mean_rise: Mapped[float] = mapped_column(Float)
    c_sd: Mapped[float] = mapped_column(Float)
    c_interval_low: Mapped[float] = mapped_column(Float)
    c_interval_high: Mapped[float] = mapped_column(Float)
    twin: Mapped[Twin] = relationship(back_populates="forecasts")
    observation: Mapped[Optional["ObservationRow"]] = relationship(back_populates="forecast", uselist=False, cascade="all, delete-orphan")
    reconciliation: Mapped[Optional["ReconciliationRow"]] = relationship(back_populates="forecast", uselist=False, cascade="all, delete-orphan",
                                                                         foreign_keys="ReconciliationRow.forecast_id")


class ObservationRow(Base):
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    forecast_id: Mapped[str] = mapped_column(ForeignKey("forecasts.id", ondelete="CASCADE"), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    observed_through: Mapped[datetime] = mapped_column(DateTime)
    peak_glucose_mg_dl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peak_glucose_rise: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    label_exceeds_180: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    window_completeness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    excluded_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    forecast: Mapped[ForecastRow] = relationship(back_populates="observation")


class ReconciliationRow(Base):
    __tablename__ = "reconciliations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    forecast_id: Mapped[str] = mapped_column(ForeignKey("forecasts.id", ondelete="CASCADE"), unique=True, index=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id", ondelete="CASCADE"), unique=True)
    reconciled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    outcome: Mapped[str] = mapped_column(String(16))                             # updated | excluded
    twin_version_before: Mapped[int] = mapped_column(Integer)
    twin_version_after: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)                   # hits, Brier components, interval coverage, standardised errors
    forecast: Mapped[ForecastRow] = relationship(back_populates="reconciliation", foreign_keys=[forecast_id])


class WhatIfRun(Base):
    __tablename__ = "what_if_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twins.id", ondelete="CASCADE"), index=True)
    twin_version_used: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)


class DataQualityFlag(Base):
    __tablename__ = "data_quality_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twins.id", ondelete="CASCADE"), index=True)
    forecast_id: Mapped[Optional[str]] = mapped_column(ForeignKey("forecasts.id", ondelete="CASCADE"), nullable=True, index=True)
    observation_id: Mapped[Optional[str]] = mapped_column(ForeignKey("observations.id", ondelete="CASCADE"), nullable=True)
    stage: Mapped[str] = mapped_column(String(16))                             # forecast | observation
    code: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
