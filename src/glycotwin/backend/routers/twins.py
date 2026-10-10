from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from glycotwin.backend import schemas, services
from glycotwin.backend.deps import get_session, get_settings_dep

router = APIRouter(prefix="/twins", tags=["twins"])
TwinId = Path(..., min_length=36, max_length=36, pattern=r"^[0-9a-f-]{36}$")


@router.post("", status_code=201)
def create_twin(req: schemas.TwinCreate, session: Session = Depends(get_session), settings=Depends(get_settings_dep)) -> dict:
    return services.envelope(services.create_twin(session, settings, req))


@router.get("/{twin_id}")
def get_twin(twin_id: str = TwinId, reference_activity: Optional[float] = Query(None, ge=0, le=25), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.get_twin(session, twin_id, reference_activity))


@router.get("/{twin_id}/history")
def history(twin_id: str = TwinId, reference_activity: Optional[float] = Query(None, ge=0, le=25), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.history(session, twin_id, reference_activity))


@router.post("/{twin_id}/forecast", status_code=201)
def forecast(req: schemas.ForecastRequest, response: Response, twin_id: str = TwinId, session: Session = Depends(get_session)) -> dict:
    data, created = services.forecast(session, twin_id, req)
    response.status_code = 201 if created else 200
    return services.envelope({**data, "created": created})


@router.get("/{twin_id}/forecasts")
def forecasts(twin_id: str = TwinId, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.list_forecasts(session, twin_id, limit, offset))


@router.post("/{twin_id}/observe", status_code=201)
def observe(req: schemas.ObserveRequest, response: Response, twin_id: str = TwinId, session: Session = Depends(get_session)) -> dict:
    data, created = services.observe(session, twin_id, req)
    response.status_code = 201 if created else 200
    return services.envelope({**data, "created": created})


@router.post("/{twin_id}/reconcile", status_code=201)
def reconcile(req: schemas.ReconcileRequest, response: Response, twin_id: str = TwinId, session: Session = Depends(get_session)) -> dict:
    data, created = services.reconcile(session, twin_id, req)
    response.status_code = 201 if created else 200
    return services.envelope({**data, "created": created})


@router.post("/{twin_id}/what-if")
def what_if(req: schemas.WhatIfRequest, twin_id: str = TwinId, session: Session = Depends(get_session)) -> dict:
    return services.envelope(services.what_if(session, twin_id, req))
