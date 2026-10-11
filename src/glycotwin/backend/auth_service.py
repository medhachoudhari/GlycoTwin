"""Accounts and sessions. Sits beside the twin services; it never touches twins, forecasts or the research engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from glycotwin.backend import security
from glycotwin.backend.config import Settings
from glycotwin.backend.models import User, UserSession
from glycotwin.backend.services import ServiceError, transaction

BAD_LOGIN = "incorrect email or password"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def user_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "is_guest": bool(u.is_guest), "created_at": u.created_at.isoformat()}


def _issue_session(session: Session, user: User, lifetime: timedelta) -> Tuple[str, datetime]:
    """A fresh random token for every sign-in (no token is ever reused). Only its hash is stored. Caller commits."""
    token = security.new_token()
    expires = _now() + lifetime
    session.add(UserSession(token_hash=security.hash_token(token), user_id=user.id, expires_at=expires))
    return token, expires


def register(session: Session, settings: Settings, req) -> Tuple[User, str, datetime]:
    if not settings.allow_registration:
        raise ServiceError(403, "registration is disabled on this server")
    problem = security.password_problem(req.password, email=req.email, name=req.name)
    if problem:
        raise ServiceError(422, problem)
    if session.scalars(select(User).where(User.email == req.email)).first() is not None:
        raise ServiceError(409, "an account with this email already exists")
    pw_hash = security.hash_password(req.password)                       # slow on purpose; done before the transaction
    user = User(id=str(uuid.uuid4()), name=req.name, email=req.email, password_hash=pw_hash, is_guest=False)
    with transaction(session):                                           # a concurrent duplicate hits the unique email index and becomes a 409
        session.add(user)
        session.flush()
        token, expires = _issue_session(session, user, timedelta(days=settings.session_days))
        user.last_login_at = _now()
    return user, token, expires


def login(session: Session, settings: Settings, throttle: security.Throttle, req) -> Tuple[User, str, datetime]:
    wait = throttle.retry_after(req.email)
    if wait:
        raise ServiceError(429, "too many failed sign-in attempts; try again later", headers={"Retry-After": str(wait)})
    user = session.scalars(select(User).where(User.email == req.email)).first()
    stored = user.password_hash if user is not None else None
    ok = security.verify_password(req.password, stored if stored else security.DUMMY_HASH) and user is not None and bool(stored)
    if not ok:
        throttle.record(req.email)
        raise ServiceError(401, BAD_LOGIN)                               # same message and similar timing whether or not the email exists
    throttle.clear(req.email)
    with transaction(session):
        if security.needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(req.password)    # quietly upgrade old cost parameters
        user.last_login_at = _now()
        token, expires = _issue_session(session, user, timedelta(days=settings.session_days))
    return user, token, expires


def guest(session: Session, settings: Settings) -> Tuple[User, str, datetime]:
    """A temporary, isolated account for demonstration: no email, no password (it can never be signed in to again), a short session."""
    if not settings.allow_guest:
        raise ServiceError(403, "guest access is disabled on this server")
    user = User(id=str(uuid.uuid4()), name="Guest", email=None, password_hash=None, is_guest=True)
    with transaction(session):
        session.add(user)
        session.flush()
        token, expires = _issue_session(session, user, timedelta(hours=settings.guest_hours))
        user.last_login_at = _now()
    return user, token, expires


def logout(session: Session, token: Optional[str]) -> bool:
    """Revoke this session on the server. Idempotent: an unknown or already-revoked token is not an error."""
    if not token:
        return False
    row = session.scalars(select(UserSession).where(UserSession.token_hash == security.hash_token(token))).first()
    if row is None or row.revoked_at is not None:
        return False
    with transaction(session):
        row.revoked_at = _now()
    return True
