from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    s = request.app.state.session_factory()
    try:
        yield s
    finally:
        s.close()


def get_settings_dep(request: Request):
    return request.app.state.settings
