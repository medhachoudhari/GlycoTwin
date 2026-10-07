"""Glycaemic group per participant from bio.csv (A1c rule from the authors' released notebook).

healthy: A1c < 5.7;  pre-diabetes: 5.7 <= A1c <= 6.4;  t2d: A1c > 6.4   (column `A1c PDL (Lab)`).
The README gives the cohort sizes 15 / 16 / 14. This module links bio.csv rows to participants ONLY through an
identifier column whose values match the participants; it never falls back to row position (that mapping is
undocumented). Groups are used for stratification and reporting, never as model features.
Errors report counts only, never identifiers.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

GROUPS = ("healthy", "pre-diabetes", "t2d")
A1C_COLUMN = "A1c PDL (Lab)"
_ID_NAME = re.compile(r"(?i)(^|[^a-z])(id|subject|participant|patient|sub)([^a-z]|$)")
_NUM_PREFIX = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)")


class GroupMappingError(ValueError):
    """The participant-to-group link cannot be established without guessing."""


def parse_numeric(value):
    """(number or NaN, annotated?) - accepts 5.4 and annotated lab strings such as '5.4 (low)'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan, False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value), False
    s = str(value)
    m = _NUM_PREFIX.match(s)
    if not m:
        return np.nan, False
    return float(m.group(1)), s.strip() != m.group(1)


def classify_a1c(a1c) -> Optional[str]:
    if a1c is None or not np.isfinite(a1c):
        return None
    return "healthy" if a1c < 5.7 else "pre-diabetes" if a1c <= 6.4 else "t2d"


def participant_number(stem) -> Optional[int]:
    m = re.search(r"(\d+)\s*$", str(stem))
    return int(m.group(1)) if m else None


def to_number(v) -> Optional[int]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return int(v) if float(v) == int(v) else None
    return participant_number(v)


def participant_groups(bio: pd.DataFrame, participant_ids: Iterable[str], id_column: Optional[str] = None,
                       a1c_column: Optional[str] = None) -> Dict[str, str]:
    """participant_id (e.g. 'CGMacros-007') -> group. Raises GroupMappingError rather than guess."""
    bio = bio.copy()
    bio.columns = [str(c).strip() for c in bio.columns]
    pids = list(participant_ids)
    numbers = {p: participant_number(p) for p in pids}
    if any(n is None for n in numbers.values()):
        raise GroupMappingError(f"{sum(n is None for n in numbers.values())} participant ids have no trailing number")
    a1c_col = a1c_column or (A1C_COLUMN if A1C_COLUMN in bio.columns else None)
    if a1c_col is None:
        cands = [c for c in bio.columns if re.search(r"(?i)a1c", c)]
        a1c_col = cands[0] if len(cands) == 1 else None
    if a1c_col is None or a1c_col not in bio.columns:
        raise GroupMappingError("no unambiguous A1c column in bio.csv")
    wanted = set(numbers.values())
    candidates = [id_column] if id_column else [c for c in bio.columns if _ID_NAME.search(c)]
    ok = []
    for c in candidates:
        if c not in bio.columns:
            continue
        nums = [to_number(v) for v in bio[c].tolist()]
        got = [n for n in nums if n is not None]
        if got and len(got) == len(nums) and len(set(got)) == len(got) and set(got) & wanted:
            ok.append((c, nums))
    if len(ok) != 1:
        raise GroupMappingError(f"need exactly one identifier column in bio.csv matching the participants; found {len(ok)} "
                                "(a positional row mapping is deliberately not used)")
    _, nums = ok[0]
    group_by_number = {n: classify_a1c(parse_numeric(v)[0]) for n, v in zip(nums, bio[a1c_col].tolist())}
    missing = [p for p, n in numbers.items() if n not in group_by_number]
    if missing:
        raise GroupMappingError(f"{len(missing)} participants have no row in bio.csv")
    out = {p: group_by_number[n] for p, n in numbers.items()}
    unknown = [p for p, g in out.items() if g is None]
    if unknown:
        raise GroupMappingError(f"{len(unknown)} participants have a missing or unparseable A1c; they cannot be stratified")
    return out
