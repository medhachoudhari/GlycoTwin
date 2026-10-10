"""Request/response validation (Pydantic v2). Units: glucose mg/dL, carbohydrate g, activity = mean METs over the 4 h before the meal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from glycotwin.models.prior_schemes import GAMMA_WIDTHS

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"


def _utc_naive(v: datetime) -> datetime:
    return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo is not None else v


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriorSpec(Strict):
    source: Literal["synthetic_demo", "prior_file"] = "synthetic_demo"
    name: Optional[str] = Field(None, description="Prior artifact file name in the configured prior directory (source=prior_file).")
    prior_scheme: Literal["empirical_bayes", "blueprint"] = "empirical_bayes"
    gamma_relative_sd: Optional[float] = Field(None, description="Blueprint prior only: one of 0.25, 0.5, 1, 2.")

    @model_validator(mode="after")
    def _check(self):
        if self.source == "prior_file" and not self.name:
            raise ValueError("source=prior_file needs a name")
        if self.source == "synthetic_demo" and self.name:
            raise ValueError("name is only used with source=prior_file")
        if self.gamma_relative_sd is not None:
            if self.prior_scheme != "blueprint":
                raise ValueError("gamma_relative_sd applies only to the blueprint prior")
            if self.gamma_relative_sd not in GAMMA_WIDTHS:
                raise ValueError(f"gamma_relative_sd must be one of {GAMMA_WIDTHS}")
        return self


class TwinCreate(Strict):
    label: str = Field(..., pattern=ID_PATTERN, description="Pseudonymous label. Never a name, e-mail or research participant id.")
    prior: PriorSpec = PriorSpec()
    glycaemic_group: Optional[Literal["healthy", "pre-diabetes", "t2d"]] = None
    reference_activity: Optional[float] = Field(None, ge=0, le=25, description="METs at which Model C's sensitivity is reported (reporting only).")

    @field_validator("label")
    @classmethod
    def _not_research_id(cls, v: str) -> str:
        if "cgmacros" in v.lower():
            raise ValueError("labels that look like CGMacros research participant ids are not accepted")
        return v


class ForecastRequest(Strict):
    event_id: str = Field(..., pattern=ID_PATTERN, description="Client meal identifier; the same id is never forecast twice.")
    meal_time: datetime
    carbs_g: float = Field(..., ge=0, le=500)
    activity_level: float = Field(..., ge=0, le=25, description="Mean METs over the 4 h strictly before the meal.")
    baseline_glucose: float = Field(..., ge=20, le=600, description="Pre-meal glucose, mg/dL.")
    activity_coverage: Optional[float] = Field(None, ge=0, le=1)
    baseline_age_minutes: Optional[float] = Field(None, ge=0, le=1440)
    trend_slope_30min: Optional[float] = Field(None, ge=-20, le=20, description="mg/dL per minute over the 30 min before the meal.")
    time_since_last_meal_min: Optional[float] = Field(None, ge=0, le=100000)

    @field_validator("meal_time")
    @classmethod
    def _norm(cls, v: datetime) -> datetime:
        return _utc_naive(v)


class ObserveRequest(Strict):
    forecast_id: str = Field(..., min_length=8, max_length=36)
    observed_through: datetime = Field(..., description="Latest CGM time available; must be at or after meal_time + 120 min.")
    peak_glucose_mg_dl: Optional[float] = Field(None, ge=20, le=600, description="Maximum glucose in (meal_time, meal_time + 120 min].")
    window_completeness: Optional[float] = Field(None, ge=0, le=1)
    excluded_reason: Optional[str] = Field(None, min_length=3, max_length=200, description="e.g. 'sensor gap over 30 minutes': the meal will not update the twin.")

    @field_validator("observed_through")
    @classmethod
    def _norm(cls, v: datetime) -> datetime:
        return _utc_naive(v)

    @model_validator(mode="after")
    def _either(self):
        if self.excluded_reason is None and self.peak_glucose_mg_dl is None:
            raise ValueError("give peak_glucose_mg_dl, or excluded_reason when the outcome cannot be trusted")
        if self.excluded_reason is not None and self.peak_glucose_mg_dl is not None:
            raise ValueError("an excluded observation carries no peak value")
        return self


class ReconcileRequest(Strict):
    forecast_id: str = Field(..., min_length=8, max_length=36)


class Scenario(Strict):
    label: Optional[str] = Field(None, max_length=80)
    carbs_g: float = Field(..., ge=0, le=500)
    activity_level: float = Field(..., ge=0, le=25)


class WhatIfRequest(Strict):
    scenarios: List[Scenario] = Field(..., min_length=1, max_length=10)
    baseline_glucose: float = Field(..., ge=20, le=600)


class Envelope(BaseModel):
    disclaimer: str
    data: Dict[str, Any]
