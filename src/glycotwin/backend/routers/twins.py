from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from glycotwin.backend import ownership, schemas, services
from glycotwin.backend.deps import get_session, get_settings_dep, owned_twin_id, require_user

router = APIRouter(prefix="/twins", tags=["twins"])
TwinId = Path(..., min_length=36, max_length=36, pattern=r"^[0-9a-f-]{36}$")


@router.get("")
def list_my_twins(user=Depends(require_user), session: Session = Depends(get_session)) -> dict:
    """Only the signed-in user's own twins. There is no way to list anyone else's, or unowned ones."""
    return services.envelope({"twins": ownership.list_owned_twins(session, user.id)})


@router.post("", status_code=201)
def create_twin(req: schemas.TwinCreate, user=Depends(require_user), session: Session = Depends(get_session), settings=Depends(get_settings_dep)) -> dict:
    return services.envelope(services.create_twin(session, settings, req, owner_id=user.id))


@router.get("/{twin_id}")
def get_twin(twin_id: str = Depends(owned_twin_id), reference_activity: Optional[float] = Query(None, ge=0, le=25), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.get_twin(session, twin_id, reference_activity))


@router.get("/{twin_id}/history")
def history(twin_id: str = Depends(owned_twin_id), reference_activity: Optional[float] = Query(None, ge=0, le=25), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.history(session, twin_id, reference_activity))


@router.post("/{twin_id}/forecast", status_code=201)
def forecast(req: schemas.ForecastRequest, response: Response, twin_id: str = Depends(owned_twin_id), session: Session = Depends(get_session)) -> dict:
    data, created = services.forecast(session, twin_id, req)
    response.status_code = 201 if created else 200
    return services.envelope({**data, "created": created})


@router.get("/{twin_id}/forecasts")
def forecasts(twin_id: str = Depends(owned_twin_id), limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.list_forecasts(session, twin_id, limit, offset))


@router.get("/{twin_id}/forecasts/{forecast_id}/explanation")
def explanation(twin_id: str = Depends(owned_twin_id), forecast_id: str = Path(..., min_length=8, max_length=36), model: str = Query("model_c", pattern="^model_[bc]$"),
                session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.explanation(session, twin_id, forecast_id, model))


@router.get("/{twin_id}/sensitivity")
def sensitivity(twin_id: str = Depends(owned_twin_id), activities: str = Query(..., description="Comma-separated pre-meal activity values (0 to 25, up to 25 values), same scale as forecasts."),
                session: Session = Depends(get_session)) -> dict:
    try:
        vals = [float(x) for x in activities.split(",") if x.strip()]
    except ValueError:
        raise services.ServiceError(422, "activities must be comma-separated numbers") from None
    if any((not 0 <= v <= 25) or v != v for v in vals):
        raise services.ServiceError(422, "each activity value must lie between 0 and 25")
    return services.envelope(services.sensitivity(session, twin_id, vals))


@router.get("/{twin_id}/reconciliations")
def reconciliations(twin_id: str = Depends(owned_twin_id), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.reconciliation_view(session, twin_id))


@router.post("/{twin_id}/observe", status_code=201)
def observe(req: schemas.ObserveRequest, response: Response, twin_id: str = Depends(owned_twin_id), session: Session = Depends(get_session)) -> dict:
    data, created = services.observe(session, twin_id, req)
    response.status_code = 201 if created else 200
    return services.envelope({**data, "created": created})


@router.post("/{twin_id}/reconcile", status_code=201)
def reconcile(req: schemas.ReconcileRequest, response: Response, twin_id: str = Depends(owned_twin_id), session: Session = Depends(get_session)) -> dict:
    data, created = services.reconcile(session, twin_id, req)
    response.status_code = 201 if created else 200
    return services.envelope({**data, "created": created})


@router.post("/{twin_id}/what-if")
def what_if(req: schemas.WhatIfRequest, twin_id: str = Depends(owned_twin_id), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.what_if(session, twin_id, req))
