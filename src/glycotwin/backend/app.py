"""FastAPI application factory. Run with:  uvicorn glycotwin.backend.app:app  (interactive docs at /docs)."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from glycotwin.backend import DISCLAIMER
from glycotwin.backend.config import Settings, get_settings
from glycotwin.backend.db import init_db, make_engine, session_factory
from glycotwin.backend.routers import health, twins
from glycotwin.backend.services import ServiceError


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)                                                   # creates missing tables only; never drops data
    app = FastAPI(title="GlycoTwin research API", version="0.1.0",
                  description=DISCLAIMER + " Every response carries this disclaimer. Units: mg/dL, grams, METs.")
    app.state.settings, app.state.engine, app.state.session_factory = settings, engine, session_factory(engine)

    @app.exception_handler(ServiceError)
    def _service_error(_request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message, "disclaimer": DISCLAIMER})

    app.include_router(health.router)
    app.include_router(twins.router)
    return app


def __getattr__(name):                                                # `app` is created lazily so importing the module has no side effects
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
