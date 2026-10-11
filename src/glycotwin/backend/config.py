"""Backend configuration from environment variables (see .env.example). SQLite is the default; no other database is required."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from glycotwin.config import REPO_ROOT

DEFAULT_DB_PATH = REPO_ROOT / "data" / "interim" / "glycotwin_backend.sqlite3"     # git-ignored folder
DEFAULT_PRIOR_DIR = REPO_ROOT / "data" / "interim" / "priors"                      # git-ignored folder


@dataclass(frozen=True)
class Settings:
    database_url: str
    prior_dir: Path
    default_reference_activity: float = 1.0      # METs; a REPORTING convention for Model C's sensitivity, not a model parameter
    session_days: float = 7.0                    # how long a normal sign-in lasts
    guest_hours: float = 24.0                    # how long a temporary guest (demo) account and its session last
    cookie_secure: bool = False                  # set true when the site is served over HTTPS (the cookie is then only sent over HTTPS)
    allow_registration: bool = True              # false: POST /auth/register is refused (existing accounts still sign in)
    allow_guest: bool = True                     # false: POST /auth/guest is refused


def get_settings() -> Settings:
    url = os.environ.get("GLYCOTWIN_DATABASE_URL", "").strip() or f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    prior_dir = Path(os.environ.get("GLYCOTWIN_PRIOR_DIR", "").strip() or DEFAULT_PRIOR_DIR)
    ref = float(os.environ.get("GLYCOTWIN_REFERENCE_ACTIVITY", "1.0"))
    def flag(name: str, default: bool) -> bool:
        v = os.environ.get(name, "").strip().lower()
        return default if v == "" else v in ("1", "true", "yes", "on")
    return Settings(database_url=url, prior_dir=prior_dir, default_reference_activity=ref,
                    session_days=float(os.environ.get("GLYCOTWIN_SESSION_DAYS", "7") or 7), guest_hours=float(os.environ.get("GLYCOTWIN_GUEST_HOURS", "24") or 24),
                    cookie_secure=flag("GLYCOTWIN_COOKIE_SECURE", False), allow_registration=flag("GLYCOTWIN_ALLOW_REGISTRATION", True),
                    allow_guest=flag("GLYCOTWIN_ALLOW_GUEST", True))
