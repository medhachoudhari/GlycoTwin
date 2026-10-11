from __future__ import annotations

from typing import Iterator

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, Path, Request
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    s = request.app.state.session_factory()
    try:
        yield s
    finally:
        s.close()


def get_settings_dep(request: Request):
    return request.app.state.settings


SESSION_COOKIE = "glycotwin_session"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_user_optional(request: Request, session: Session = Depends(get_session)):
    """The signed-in user for this request, or None. The session cookie holds a random token; only its SHA-256 is stored, and the session must be unexpired and unrevoked."""
    from glycotwin.backend.models import User, UserSession
    from glycotwin.backend.security import hash_token
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = session.scalars(select(UserSession).where(UserSession.token_hash == hash_token(token))).first()
    if row is None or row.revoked_at is not None or row.expires_at <= _now():
        return None
    return session.get(User, row.user_id)


def require_user(user=Depends(current_user_optional)):
    """401 when nobody is signed in. Stage B puts this (plus an ownership check) in front of every twin route."""
    from glycotwin.backend.services import ServiceError
    if user is None:
        raise ServiceError(401, "not signed in")
    return user


def same_origin(request: Request) -> None:
    """Defence against cross-site requests that carry the cookie: a browser-sent Origin must match the host being called. Requests without Origin (scripts, tests) pass."""
    from glycotwin.backend.services import ServiceError
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host", ""):
        raise ServiceError(403, "cross-origin request refused")


def owned_twin_id(twin_id: str = Path(..., min_length=36, max_length=36, pattern=r"^[0-9a-f-]{36}$"), user=Depends(require_user), session: Session = Depends(get_session)) -> str:
    """Put in front of EVERY route that has {twin_id}. Order matters: nobody signed in -> 401; signed in but the twin is not yours (someone else's, unowned, or it does not
    exist) -> the SAME 404 'twin not found', so a signed-in user cannot tell the difference and cannot probe for other people's twin ids."""
    from glycotwin.backend.models import TwinOwner
    from glycotwin.backend.services import ServiceError
    row = session.get(TwinOwner, twin_id)
    if row is None or row.user_id != user.id:
        raise ServiceError(404, "twin not found")
    return twin_id
