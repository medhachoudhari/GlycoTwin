"""Service layer: one database transaction per operation, the existing engine for every computation.

  create_twin      prior from a synthetic demo population or an aggregate prior artifact -> version 0 (via store.initialize_twin)
  forecast         twin.state.forecast_meal (unchanged)  -> forecasts row (+ data-quality flags); idempotent on (twin, event_id)
  observe          stores the observed outcome for a forecast (no model change); idempotent on identical resubmission
  reconcile        twin.state.reconcile_forecast or exclude_forecast (unchanged) -> new version + reconciliation, atomically; idempotent
  what_if          twin.insight.what_if (unchanged, pure) -> what_if_runs row; the twin is never modified
Any exception inside an operation rolls the whole transaction back: no partial state is ever committed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from glycotwin.backend import DISCLAIMER
from glycotwin.backend.config import Settings
from glycotwin.backend.models import DataQualityFlag, ForecastRow, ObservationRow, ParameterSnapshot, ReconciliationRow, Twin, TwinStateRow, WhatIfRun
from glycotwin.backend.priors import PriorError, demo_prior, load_prior_file
from glycotwin.backend.store import SqlTwinStore, forecast_row_to_record
from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL, OUTCOME_WINDOW
from glycotwin.twin import insight
from glycotwin.twin.state import exclude_forecast, forecast_meal, reconcile_forecast
from glycotwin.twin.state_view import twin_state_view

WINDOW = timedelta(seconds=OUTCOME_WINDOW.total_seconds())


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@lru_cache(maxsize=1)
def engine_provenance() -> dict:
    from glycotwin.models.model_a_cv import _git_state
    try:
        from importlib.metadata import version
        pkg = version("glycotwin")
    except Exception:  # noqa: BLE001
        pkg = None
    return {"package_version": pkg, **_git_state(), "engine": "glycotwin.twin.state.forecast_meal / reconcile_forecast (unchanged research engine)"}


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


@contextmanager
def transaction(session: Session):
    try:
        yield
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ServiceError(409, "the request conflicts with stored data (duplicate or concurrent update); nothing was changed") from None
    except Exception:
        session.rollback()
        raise


def _twin(session: Session, twin_id: str) -> Twin:
    t = session.get(Twin, twin_id)
    if t is None:
        raise ServiceError(404, "twin not found")
    return t


def _forecast(session: Session, twin_id: str, forecast_id: str) -> ForecastRow:
    f = session.get(ForecastRow, forecast_id)
    if f is None or f.twin_id != twin_id:
        raise ServiceError(404, "forecast not found for this twin")
    return f


def _activity_support(twin: Twin) -> tuple[Optional[tuple[float, float]], str]:
    """(range, mode) of activity values the twin's prior supports. Demo priors: reject outside. Prior files that record a range: flag outside (not reject)."""
    prov = twin.prior_provenance or {}
    rng = prov.get("supported_activity_range") or prov.get("activity_range")
    if not rng:
        return None, "none"
    mode = "reject" if twin.prior_source == "synthetic_demo" else "flag"
    return (float(rng[0]), float(rng[1])), mode


def check_activity_support(twin: Twin, values) -> list[str]:
    """Raise ServiceError(422) for a synthetic-demo twin given activity outside its prior's scale; return flag messages for prior-file twins."""
    rng, mode = _activity_support(twin)
    if rng is None:
        return []
    bad = [float(v) for v in values if not (rng[0] <= float(v) <= rng[1])]
    if not bad:
        return []
    if mode == "reject":
        raise ServiceError(422, f"activity_level {bad[0]:g} is outside the range [{rng[0]:g}, {rng[1]:g}] supported by this synthetic demo twin: its prior was "
                                "estimated on a simulated 0-1 activity scale (not METs), so Model C would extrapolate and give misleading forecasts. "
                                "Use activity values on that scale, or create a twin from a prior exported from real data.")
    return [f"activity_level {bad[0]:g} is outside the range [{rng[0]:g}, {rng[1]:g}] of the population the prior was fitted on; Model C extrapolates"]


def model_version(twin: Twin) -> str:
    g = f", gamma_relative_sd={twin.gamma_relative_sd:g}" if twin.gamma_relative_sd is not None else ""
    return f"B[carbs_g] + C[carbs_g, carbs_x_activity]; prior={twin.prior_scheme}{g}"


# ----------------------------------------------------------------------------- twins

def create_twin(session: Session, settings: Settings, req) -> dict:
    if session.scalars(select(Twin).where(Twin.label == req.label)).first() is not None:
        raise ServiceError(409, "a twin with this label already exists")
    try:
        if req.prior.source == "synthetic_demo":
            prior_b, prior_c, prov = demo_prior(req.prior.prior_scheme, req.prior.gamma_relative_sd)
        else:
            prior_b, prior_c, prov = load_prior_file(settings.prior_dir, req.prior.name)
            if prov.get("prior_scheme") != req.prior.prior_scheme or prov.get("gamma_relative_sd") != req.prior.gamma_relative_sd:
                raise PriorError("the requested prior_scheme / gamma_relative_sd do not match the prior file's provenance")
    except PriorError as exc:
        raise ServiceError(422, str(exc)) from None
    tid = str(uuid.uuid4())
    profile = {"glycaemic_group": req.glycaemic_group} if req.glycaemic_group else {}
    with transaction(session):
        session.add(Twin(id=tid, label=req.label, prior_source=req.prior.source, prior_scheme=req.prior.prior_scheme,
                         gamma_relative_sd=prov.get("gamma_relative_sd"), prior_provenance=prov, profile=profile,
                         config={"reference_activity": req.reference_activity if req.reference_activity is not None else settings.default_reference_activity,
                                 "outcome_window_minutes": OUTCOME_WINDOW.total_seconds() / 60, "threshold_mg_dl": GLUCOSE_THRESHOLD_MG_DL},
                         is_synthetic=bool(prov.get("SYNTHETIC", False))))
        session.flush()
        SqlTwinStore(session, tid).initialize_twin(tid, prior_b, prior_c, profile)
    return get_twin(session, tid)


def _twin_summary(t: Twin) -> dict:
    return {"twin_id": t.id, "label": t.label, "created_at": t.created_at.isoformat(), "prior_source": t.prior_source, "prior_scheme": t.prior_scheme,
            "gamma_relative_sd": t.gamma_relative_sd, "prior_provenance": t.prior_provenance, "profile": t.profile, "config": t.config,
            "is_synthetic": t.is_synthetic}


def get_twin(session: Session, twin_id: str, reference_activity: Optional[float] = None) -> dict:
    t = _twin(session, twin_id)
    store = SqlTwinStore(session, twin_id)
    ref = reference_activity if reference_activity is not None else t.config.get("reference_activity")
    return {**_twin_summary(t), "state": twin_state_view(store, twin_id, ref), "insight": insight.twin_insight(store, twin_id, ref)}


def history(session: Session, twin_id: str, reference_activity: Optional[float] = None) -> dict:
    t = _twin(session, twin_id)
    store = SqlTwinStore(session, twin_id)
    ref = reference_activity if reference_activity is not None else t.config.get("reference_activity")
    rows = session.scalars(select(TwinStateRow).where(TwinStateRow.twin_id == twin_id).order_by(TwinStateRow.version)).all()
    versions = []
    for r in rows:
        params = {p.model: {"beta_mean": p.beta_mean, "beta_var": p.beta_var, "gamma_mean": p.gamma_mean, "gamma_var": p.gamma_var,
                            "beta_gamma_cov": p.beta_gamma_cov, "noise_variance": p.noise_variance, "n_observations_used": p.n_observations_used,
                            "prior_source": p.prior_source} for p in r.parameters}
        versions.append({"version": r.version, "parent_version": r.parent_version, "created_at": r.created_at.isoformat(),
                         "n_observations": r.n_observations, "reconciliation_id": r.reconciliation_id, "parameters": params})
    return {"twin_id": twin_id, "reference_activity": ref, "versions": versions,
            "parameter_history": insight.parameter_history(store, twin_id, ref),
            "posterior_convergence": insight.posterior_convergence(store, twin_id, ref),
            "hit_rate_trend": insight.hit_rate_trend(store, twin_id),
            "exclusions": [{"forecast_id": e.forecast_id, "reason": e.reason} for e in store.exclusions(twin_id)]}


# ----------------------------------------------------------------------------- forecast

def _forecast_out(f: ForecastRow) -> dict:
    out = {"forecast_id": f.id, "event_id": f.event_id, "meal_time": f.meal_time.isoformat(), "created_at": f.created_at.isoformat(),
           "twin_version_at_forecast": f.twin_version_at_forecast, "model_version": f.model_version, "inputs": f.inputs,
           "model_b": {"p_peak_at_least_180": f.b_probability, "mean_rise_mg_dl": f.b_mean_rise, "sd_mg_dl": f.b_sd, "interval90_rise_mg_dl": [f.b_interval_low, f.b_interval_high],
                       "description": "personalised carbohydrate sensitivity, no activity term"},
           "model_c": {"p_peak_at_least_180": f.c_probability, "mean_rise_mg_dl": f.c_mean_rise, "sd_mg_dl": f.c_sd, "interval90_rise_mg_dl": [f.c_interval_low, f.c_interval_high],
                       "description": "activity-conditioned sensitivity (research hypothesis; not shown to be better than Model B)"},
           "horizon_minutes": OUTCOME_WINDOW.total_seconds() / 60, "data_quality": f.data_quality, "engine_provenance": f.engine_provenance,
           "status": "pending"}
    if f.observation is not None:
        out["status"] = "observed"
        out["observation_id"] = f.observation.id
    if f.reconciliation is not None:
        out["status"] = "excluded" if f.reconciliation.outcome == "excluded" else "reconciled"
        out["reconciliation_id"] = f.reconciliation.id
    return out


def forecast(session: Session, twin_id: str, req) -> tuple[dict, bool]:
    twin_row = _twin(session, twin_id)
    inputs = {k: v for k, v in req.model_dump().items()}
    inputs["meal_time"] = req.meal_time.isoformat()
    h = _sha(inputs)
    existing = session.scalars(select(ForecastRow).where(ForecastRow.twin_id == twin_id, ForecastRow.event_id == req.event_id)).first()
    extra_quality = check_activity_support(twin_row, [req.activity_level]) if existing is None else []
    if existing is not None:
        if existing.input_sha256 == h:
            return _forecast_out(existing), False                     # idempotent repeat: nothing new is computed or stored
        raise ServiceError(409, "this event_id was already forecast with different inputs")
    # leakage guard: the twin must not already contain outcomes observed after this meal time (a back-dated forecast would see the future)
    latest_close = session.scalar(select(func.max(ForecastRow.meal_time)).join(ReconciliationRow, ReconciliationRow.forecast_id == ForecastRow.id)
                                  .where(ForecastRow.twin_id == twin_id, ReconciliationRow.outcome == "updated"))
    if latest_close is not None and req.meal_time < latest_close + WINDOW:
        raise ServiceError(409, "the twin already learned from an outcome window that closes after this meal time; a back-dated forecast is refused")
    store = SqlTwinStore(session, twin_id)
    t = _twin(session, twin_id)
    store.context = {"event_id": req.event_id, "inputs": inputs, "input_sha256": h, "model_version": model_version(t), "engine_provenance": engine_provenance(),
                     "extra_quality_reasons": extra_quality}
    row = pd.Series({**{k: v for k, v in inputs.items() if k not in ("event_id", "meal_time") and v is not None},   # optional fields only if supplied
                     "meal_time": pd.Timestamp(req.meal_time)})
    with transaction(session):
        rec = forecast_meal(store, twin_id, row)
        if not (np.isfinite(rec.model_b_forecast.probability_exceeds_180) and np.isfinite(rec.model_c_forecast.probability_exceeds_180)):
            raise ServiceError(422, "the forecast was not finite; nothing was stored")
        for reason in rec.data_quality.get("reasons", []):
            session.add(DataQualityFlag(twin_id=twin_id, forecast_id=rec.forecast_id, stage="forecast", code="low_data_quality", message=reason))
        for msg in extra_quality:
            session.add(DataQualityFlag(twin_id=twin_id, forecast_id=rec.forecast_id, stage="forecast", code="activity_outside_prior_range", message=msg))
        if rec.data_quality.get("insufficient_history"):
            session.add(DataQualityFlag(twin_id=twin_id, forecast_id=rec.forecast_id, stage="forecast", code="insufficient_history",
                                        message=rec.data_quality["warnings"][-1]))
    return _forecast_out(session.get(ForecastRow, rec.forecast_id)), True


def list_forecasts(session: Session, twin_id: str, limit: int, offset: int) -> dict:
    _twin(session, twin_id)
    total = session.scalar(select(func.count()).select_from(ForecastRow).where(ForecastRow.twin_id == twin_id))
    rows = session.scalars(select(ForecastRow).where(ForecastRow.twin_id == twin_id).order_by(ForecastRow.meal_time, ForecastRow.event_id)
                           .limit(limit).offset(offset)).all()
    return {"twin_id": twin_id, "total": int(total), "limit": limit, "offset": offset, "forecasts": [_forecast_out(r) for r in rows]}


# ----------------------------------------------------------------------------- observe

def _observation_out(o: ObservationRow) -> dict:
    return {"observation_id": o.id, "forecast_id": o.forecast_id, "observed_through": o.observed_through.isoformat(),
            "peak_glucose_mg_dl": o.peak_glucose_mg_dl, "peak_glucose_rise_mg_dl": o.peak_glucose_rise, "label_peak_at_least_180": o.label_exceeds_180,
            "window_completeness": o.window_completeness, "excluded_reason": o.excluded_reason, "kind": "OBSERVED outcome (not yet applied to the twin)"
            if o.forecast.reconciliation is None else "OBSERVED outcome (reconciled)"}


def observe(session: Session, twin_id: str, req) -> tuple[dict, bool]:
    _twin(session, twin_id)
    f = _forecast(session, twin_id, req.forecast_id)
    payload = req.model_dump()
    payload["observed_through"] = req.observed_through.isoformat()
    h = _sha(payload)
    if f.observation is not None:
        if f.observation.input_sha256 == h:
            return _observation_out(f.observation), False
        raise ServiceError(409, "an observation was already recorded for this forecast; it cannot be replaced")
    if req.observed_through < f.meal_time + WINDOW:
        raise ServiceError(422, f"the outcome window is not complete: observed_through must be at or after meal_time + {int(WINDOW.total_seconds() // 60)} minutes")
    base = float(f.inputs["baseline_glucose"])
    peak = req.peak_glucose_mg_dl
    oid = str(uuid.uuid4())
    with transaction(session):
        o = ObservationRow(id=oid, forecast_id=f.id, observed_through=req.observed_through, peak_glucose_mg_dl=peak,
                           peak_glucose_rise=None if peak is None else float(peak - base),
                           label_exceeds_180=None if peak is None else bool(peak >= GLUCOSE_THRESHOLD_MG_DL),
                           window_completeness=req.window_completeness, excluded_reason=req.excluded_reason, input_sha256=h)
        session.add(o)
        session.flush()
        if req.excluded_reason:
            session.add(DataQualityFlag(twin_id=twin_id, forecast_id=f.id, observation_id=oid, stage="observation", code="excluded", message=req.excluded_reason))
        elif req.window_completeness is not None and req.window_completeness < 1.0:
            session.add(DataQualityFlag(twin_id=twin_id, forecast_id=f.id, observation_id=oid, stage="observation", code="partial_window",
                                        message="the observed maximum over a partly observed window is a lower bound"))
    session.refresh(f)
    return _observation_out(session.get(ObservationRow, oid)), True


# ----------------------------------------------------------------------------- reconcile

def _metrics(f: ForecastRow, o: ObservationRow) -> dict:
    out = {}
    y = bool(o.label_exceeds_180)
    for m, p, mean, sd, lo, hi in (("model_b", f.b_probability, f.b_mean_rise, f.b_sd, f.b_interval_low, f.b_interval_high),
                                    ("model_c", f.c_probability, f.c_mean_rise, f.c_sd, f.c_interval_low, f.c_interval_high)):
        out[m] = {"hit_at_50pct": bool((p >= 0.5) == y), "brier_component": float((p - float(y)) ** 2),
                  "observed_inside_interval90": bool(lo <= o.peak_glucose_rise <= hi), "standardised_error": float((o.peak_glucose_rise - mean) / sd)}
    return out


def _reconciliation_out(r: ReconciliationRow) -> dict:
    return {"reconciliation_id": r.id, "forecast_id": r.forecast_id, "observation_id": r.observation_id, "outcome": r.outcome,
            "twin_version_before": r.twin_version_before, "twin_version_after": r.twin_version_after, "reconciled_at": r.reconciled_at.isoformat(),
            "metrics": r.metrics}


def reconcile(session: Session, twin_id: str, req) -> tuple[dict, bool]:
    _twin(session, twin_id)
    f = _forecast(session, twin_id, req.forecast_id)
    if f.reconciliation is not None:
        return _reconciliation_out(f.reconciliation), False            # idempotent repeat: the twin is never updated twice
    o = f.observation
    if o is None:
        raise ServiceError(409, "no observation has been submitted for this forecast yet")
    store = SqlTwinStore(session, twin_id)
    rid = str(uuid.uuid4())
    store.context = {"reconciliation_id": rid, "observation_id": o.id}
    through = pd.Timestamp(o.observed_through)
    try:
        with transaction(session):
            if o.excluded_reason:
                exclude_forecast(store, f.id, o.excluded_reason, observed_through=through)
            else:
                reconcile_forecast(store, f.id, float(o.peak_glucose_rise), bool(o.label_exceeds_180), observed_through=through)
                r = session.get(ReconciliationRow, rid)
                r.metrics = _metrics(f, o)
                session.flush()
    except (ValueError, KeyError) as exc:
        raise ServiceError(409, f"reconciliation refused: {exc}") from None
    session.expire_all()
    return _reconciliation_out(session.get(ReconciliationRow, rid)), True


# ----------------------------------------------------------------------------- what-if

def what_if(session: Session, twin_id: str, req) -> dict:
    twin_row = _twin(session, twin_id)
    flags = check_activity_support(twin_row, [s.activity_level for s in req.scenarios])
    store = SqlTwinStore(session, twin_id)
    tw = store.current_twin(twin_id)
    rows = session.scalars(select(ForecastRow).where(ForecastRow.twin_id == twin_id)).all()
    ranges = None
    if rows:
        cs, acts = [r.inputs["carbs_g"] for r in rows], [r.inputs["activity_level"] for r in rows]
        ranges = {"carbs_g": (min(cs), max(cs)), "activity_level": (min(acts), max(acts))}
    scenarios = [s.model_dump(exclude_none=True) for s in req.scenarios]
    try:
        result = insight.what_if(tw, scenarios, baseline_glucose=req.baseline_glucose, reference_ranges=ranges)
    except ValueError as exc:
        raise ServiceError(422, str(exc)) from None
    result = json.loads(json.dumps(result, default=float))
    run_id = str(uuid.uuid4())
    with transaction(session):
        session.add(WhatIfRun(id=run_id, twin_id=twin_id, twin_version_used=tw.version, request=req.model_dump(), result=result))
    return {"what_if_id": run_id, **result, "prior_support_warnings": flags}


def envelope(data: dict) -> dict:
    return {"disclaimer": DISCLAIMER, "data": data}
