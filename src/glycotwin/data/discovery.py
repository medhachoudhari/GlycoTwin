"""Locate participant CSV files under a dataset root (read-only; opens only the header row)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {"Timestamp", "Meal Type"}


def discover_participant_files(root: Path | str) -> list[Path]:
    """CSV files whose header contains both `Timestamp` and `Meal Type`, in sorted order.

    Matches by header, not by file name, so it does not assume the dataset's naming or layout.
    """
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(".csv"):
                p = Path(dirpath) / f
                try:
                    cols = {str(c).strip() for c in pd.read_csv(p, nrows=0).columns}
                except Exception:  # noqa: BLE001 - unreadable files are simply not candidates
                    continue
                if REQUIRED_COLUMNS <= cols:
                    found.append(p)
    return sorted(found)
