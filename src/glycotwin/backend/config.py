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


def get_settings() -> Settings:
    url = os.environ.get("GLYCOTWIN_DATABASE_URL", "").strip() or f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"
    prior_dir = Path(os.environ.get("GLYCOTWIN_PRIOR_DIR", "").strip() or DEFAULT_PRIOR_DIR)
    ref = float(os.environ.get("GLYCOTWIN_REFERENCE_ACTIVITY", "1.0"))
    return Settings(database_url=url, prior_dir=prior_dir, default_reference_activity=ref)
