from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from glycotwin.backend import DISCLAIMER
from glycotwin.backend.db import ping
from glycotwin.backend.deps import get_session
from glycotwin.backend.services import engine_provenance

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    try:
        ok = ping(session)
        tables = sorted(inspect(session.get_bind()).get_table_names())
    except Exception:  # noqa: BLE001 - health must report, not crash
        ok, tables = False, []
    return {"status": "ok" if ok else "degraded", "database": "ok" if ok else "unavailable", "tables": tables,
            "engine": engine_provenance(), "disclaimer": DISCLAIMER}
