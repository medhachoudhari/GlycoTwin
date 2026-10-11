from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from glycotwin.backend import auth_service, schemas, services
from glycotwin.backend.deps import SESSION_COOKIE, current_user_optional, get_session, get_settings_dep, require_user, same_origin
from glycotwin.backend.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, settings, token: str, expires: datetime) -> None:
    from glycotwin.backend.auth_service import _now
    max_age = max(1, int((expires - _now()).total_seconds()))
    # HttpOnly: page scripts cannot read it. SameSite=Lax: not sent on cross-site POSTs. Secure only over HTTPS (setting).
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")


@router.post("/register", status_code=201, dependencies=[Depends(same_origin)])
def register(req: schemas.RegisterRequest, response: Response, session: Session = Depends(get_session), settings=Depends(get_settings_dep)) -> dict:
    user, token, expires = auth_service.register(session, settings, req)
    _set_cookie(response, settings, token, expires)
    return services.envelope({"user": auth_service.user_out(user)})


@router.post("/login", dependencies=[Depends(same_origin)])
def login(req: schemas.LoginRequest, request: Request, response: Response, session: Session = Depends(get_session), settings=Depends(get_settings_dep)) -> dict:
    user, token, expires = auth_service.login(session, settings, request.app.state.login_throttle, req)
    _set_cookie(response, settings, token, expires)
    return services.envelope({"user": auth_service.user_out(user)})


@router.post("/guest", status_code=201, dependencies=[Depends(same_origin)])
def guest(request: Request, response: Response, session: Session = Depends(get_session), settings=Depends(get_settings_dep)) -> dict:
    ip = request.client.host if request.client else "unknown"
    throttle = request.app.state.guest_throttle
    wait = throttle.retry_after(ip)
    if wait:
        raise services.ServiceError(429, "too many guest sessions from this address; try again later", headers={"Retry-After": str(wait)})
    throttle.record(ip)
    user, token, expires = auth_service.guest(session, settings)
    _set_cookie(response, settings, token, expires)
    return services.envelope({"user": auth_service.user_out(user)})


@router.post("/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    auth_service.logout(session, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return services.envelope({"signed_out": True})


@router.get("/me")
def me(user: User = Depends(require_user)) -> dict:
    return services.envelope({"user": auth_service.user_out(user)})
