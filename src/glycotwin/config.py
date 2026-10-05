"""Dataset path configuration.

Only locates the local dataset; it never reads or transforms data. Scientific/model
settings belong in a separate module, added after the data audit.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_ROOT_ENV_VAR = "GLYCOTWIN_DATA_ROOT"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Reserved for the audit script: where small, aggregate (non-participant-level)
# audit summaries are written. Not used yet in this scaffolding stage.
AUDIT_DIR = REPO_ROOT / "data" / "audit"


class DatasetNotFoundError(FileNotFoundError):
    """Raised when the local dataset root is unset or does not exist."""


def get_dataset_root(path: str | os.PathLike[str] | None = None) -> Path:
    """Return the validated dataset root directory.

    Uses ``path`` if given, otherwise the ``GLYCOTWIN_DATA_ROOT`` environment variable.
    Raises ``DatasetNotFoundError`` with an actionable message if unset or invalid.
    """
    raw = os.fspath(path) if path is not None else os.environ.get(DATA_ROOT_ENV_VAR, "")
    raw = raw.strip()
    if not raw:
        raise DatasetNotFoundError(
            f"Dataset location is not configured. Set the {DATA_ROOT_ENV_VAR} environment "
            "variable to your local CGMacros directory (see .env.example and README)."
        )
    root = Path(raw).expanduser()
    if not root.exists():
        raise DatasetNotFoundError(f"Dataset path does not exist: {root}")
    if not root.is_dir():
        raise DatasetNotFoundError(f"Dataset path is not a directory: {root}")
    return root.resolve()
