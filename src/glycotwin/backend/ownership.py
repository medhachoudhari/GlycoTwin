"""Twin ownership: who may see which twin. Used by the API (listing) and by scripts/claim_twin.py (explicit, one-way claiming of old twins)."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from glycotwin.backend import security
from glycotwin.backend.models import ForecastRow, Twin, TwinOwner, TwinStateRow, User


class ClaimError(Exception):
    """A claim was refused. The message says why; nothing was changed."""


def list_owned_twins(session: Session, user_id: str) -> List[dict]:
    q = (select(Twin, func.max(TwinStateRow.version)).join(TwinOwner, TwinOwner.twin_id == Twin.id).outerjoin(TwinStateRow, TwinStateRow.twin_id == Twin.id)
         .where(TwinOwner.user_id == user_id).group_by(Twin.id).order_by(Twin.created_at.desc()))
    return [{"twin_id": t.id, "label": t.label, "created_at": t.created_at.isoformat(), "prior_source": t.prior_source, "prior_scheme": t.prior_scheme,
             "is_synthetic": t.is_synthetic, "current_version": int(v) if v is not None else 0} for t, v in session.execute(q).all()]


def list_unowned(session: Session) -> List[dict]:
    """READ-ONLY view for the person running the claim script (never exposed through the API)."""
    q = (select(Twin, func.count(ForecastRow.id)).outerjoin(ForecastRow, ForecastRow.twin_id == Twin.id).outerjoin(TwinOwner, TwinOwner.twin_id == Twin.id)
         .where(TwinOwner.twin_id.is_(None)).group_by(Twin.id).order_by(Twin.created_at))
    return [{"twin_id": t.id, "label": t.label, "created_at": t.created_at.isoformat(), "is_synthetic": t.is_synthetic, "n_forecasts": int(n)} for t, n in session.execute(q).all()]


def claim_twin(session: Session, twin_id: str, email: str, *, apply: bool) -> dict:
    """Give an UNOWNED twin to an existing, non-guest account. One-way and refusal-first:
    * a twin that already has an owner is NEVER reassigned (there is no force option and no transfer feature);
    * the account must already exist and must not be a guest;
    * with apply=False nothing is written (dry run).
    The primary key on twin_owners.twin_id makes a race between two claimers safe: the second one fails and nothing changes."""
    twin = session.get(Twin, twin_id)
    if twin is None:
        raise ClaimError("no twin with that id exists")
    current = session.get(TwinOwner, twin_id)
    if current is not None:
        raise ClaimError("this twin already has an owner; ownership is never transferred or overwritten")
    user = session.scalars(select(User).where(User.email == security.normalise_email(email))).first()
    if user is None:
        raise ClaimError("no account with that email exists (the person must register first)")
    if user.is_guest:
        raise ClaimError("temporary guest accounts cannot own claimed twins")
    result = {"twin_id": twin.id, "label": twin.label, "claimed_by": user.email, "user_id": user.id, "applied": False}
    if not apply:
        return result
    try:
        session.add(TwinOwner(twin_id=twin.id, user_id=user.id, source="claimed"))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ClaimError("this twin was claimed by someone else just now; nothing was changed") from None
    result["applied"] = True
    return result
