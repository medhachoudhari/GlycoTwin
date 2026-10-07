"""READ-ONLY audit: how do `Meal Type` rows relate to the `Image path` rows in the released CGMacros CSVs?

Question: can the official meal_end be reconstructed from the released files WITHOUT an undocumented
assumption? The files have no meal_end column. This script does not choose an end. For every meal row
(non-null `Meal Type`) it lists the STRUCTURAL candidates and classifies how ambiguous they are:

  candidate end photo = a row with a non-null `Image path` and NO `Meal Type`, strictly after the meal
                        row and strictly before the next meal row of the same file.
                        (The next meal row is only a bound on who the photo could belong to. It is never
                        used as the meal end, and no maximum duration is applied.)

  no_candidate_photo    zero candidates
  single_candidate      exactly one candidate (structurally unique, but NOTHING in the file proves that photo
                        is an "after eating" photo rather than e.g. a snack photo)
  multiple_candidates   two or more candidates: the pairing is ambiguous and is NOT resolved here

Orthogonal flags: the meal row has no image of its own; the next meal row has the same Meal Type; the meal
row is the last in its file. Distributions (minutes) are descriptive; no cut-off is applied anywhere.

It also looks for an explicit marker in image FILE NAMES (e.g. words such as before/after) by reporting
generic alphabetic tokens that occur in at least --min-participants participants (k-anonymity). It never
prints a path, a file name, a date or a participant identifier. Participants are anonymous labels P1..Pn.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\audit_meal_photo_pairing.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root
from glycotwin.data.discovery import discover_participant_files

MIN_BIN_EDGES = [0, 5, 10, 15, 20, 30, 45, 60, 90, 120, 240]  # descriptive histogram only; not a rule
NO_CANDIDATE, SINGLE, MULTIPLE = "no_candidate_photo", "single_candidate", "multiple_candidates"
SUSPECT_TOKENS = {"before", "after", "pre", "post", "start", "end", "begin", "finish", "finished", "empty", "leftover", "b", "a"}


def _present(s: pd.Series) -> pd.Series:
    return s.notna() & (s.astype(str).str.strip() != "")


def load_rows(path) -> tuple[pd.DataFrame, dict]:
    """Timestamp, meal flag/type and photo flag/name for one participant file (read-only)."""
    head = pd.read_csv(path, nrows=0).columns
    want = [c for c in ("Timestamp", "Meal Type", "Image path") if c in head]
    df = pd.read_csv(path, usecols=want)
    notes = {"image_column_missing": "Image path" not in df.columns}
    df["t"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    notes["unparseable_timestamps"] = int(df["t"].isna().sum())
    df = df[df["t"].notna()].copy()
    df["row_order"] = np.arange(len(df))
    df = df.sort_values(["t", "row_order"], kind="stable").reset_index(drop=True)
    df["is_meal"] = _present(df["Meal Type"]) if "Meal Type" in df.columns else False
    df["is_photo"] = _present(df["Image path"]) if "Image path" in df.columns else False
    notes["duplicate_timestamps"] = int(df["t"].duplicated().sum())
    return df, notes


def pair_candidates(df: pd.DataFrame) -> list[dict]:
    """One record per meal row. Pure structure; no end is chosen."""
    meals = df.index[df["is_meal"]].to_list()
    non_meal_photos = df[df["is_photo"] & ~df["is_meal"]]
    out = []
    for j, i in enumerate(meals):
        t0 = df.at[i, "t"]
        nxt = meals[j + 1] if j + 1 < len(meals) else None
        t_next = df.at[nxt, "t"] if nxt is not None else None
        sel = non_meal_photos[(non_meal_photos["t"] > t0) & ((non_meal_photos["t"] < t_next) if t_next is not None else True)]
        offs = ((sel["t"] - t0).dt.total_seconds() / 60).to_list()
        out.append({
            "n_candidates": len(offs), "offsets_min": offs, "own_photo": bool(df.at[i, "is_photo"]),
            "has_next_meal_row": nxt is not None,
            "next_meal_gap_min": float((t_next - t0).total_seconds() / 60) if nxt is not None else None,
            "next_same_type": bool(nxt is not None and str(df.at[nxt, "Meal Type"]).strip().lower() == str(df.at[i, "Meal Type"]).strip().lower()),
            "class": NO_CANDIDATE if not offs else SINGLE if len(offs) == 1 else MULTIPLE,
        })
    return out


def photos_before_first_meal(df: pd.DataFrame) -> int:
    meals = df.index[df["is_meal"]]
    if len(meals) == 0:
        return int((df["is_photo"]).sum())
    return int((df["is_photo"] & ~df["is_meal"] & (df["t"] < df.at[meals[0], "t"])).sum())


def _dist(values) -> dict:
    v = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=float)
    if v.size == 0:
        return {"n": 0}
    q = np.percentile(v, [5, 25, 50, 75, 95])
    edges = MIN_BIN_EDGES + [np.inf]
    hist = {f"[{edges[k]},{'inf' if np.isinf(edges[k + 1]) else int(edges[k + 1])})": int(((v >= edges[k]) & (v < edges[k + 1])).sum())
            for k in range(len(edges) - 1)}
    return {"n": int(v.size), "min": float(v.min()), "p5": float(q[0]), "p25": float(q[1]), "median": float(q[2]),
            "p75": float(q[3]), "p95": float(q[4]), "max": float(v.max()), "histogram_minutes": hist}


def _tokens(name: str) -> set[str]:
    base = re.split(r"[\\/]", str(name))[-1]
    base = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", base)
    return {t for t in re.split(r"[^A-Za-z]+", base.lower()) if t}


def token_report(per_participant_tokens: dict[str, dict[str, Counter]], min_participants: int) -> dict:
    """Generic alphabetic file-name tokens present in >= min_participants participants, split by
    whether the row carrying the image is a meal row. Rarer tokens (could identify someone) are never listed."""
    seen: dict[str, set] = {}
    for pid, byrole in per_participant_tokens.items():
        for role, cnt in byrole.items():
            for tok in cnt:
                seen.setdefault(tok, set()).add(pid)
    shown = {tok for tok, who in seen.items() if len(who) >= min_participants}
    rows = {}
    for tok in sorted(shown):
        rows[tok] = {role: sum(byrole.get(role, Counter()).get(tok, 0) for byrole in per_participant_tokens.values())
                     for role in ("on_meal_rows", "on_non_meal_rows")}
        rows[tok]["n_participants"] = len(seen[tok])
    suspects = sorted(t for t in shown if t in SUSPECT_TOKENS)
    return {"min_participants_to_list": min_participants, "generic_tokens": rows,
            "n_tokens_suppressed_for_rarity": int(len(seen) - len(shown)), "possible_before_after_marker_tokens_present": suspects}


def audit(files: list[Path], seed: int = 0, min_participants: int = 5) -> dict:
    order = np.random.default_rng(seed).permutation(len(files))
    labels = {i: f"P{int(k) + 1}" for i, k in enumerate(order)}
    per_part, all_recs, tok = {}, [], {}
    gaps_same, gaps_all, spacing, post_meal_nonmeal = [], [], [], []
    notes_total, errors = Counter(), Counter()
    orphan_photos = 0
    n_photo_rows = n_meal_rows = n_meal_with_photo = 0
    for i, p in enumerate(files):
        lab = labels[i]
        try:
            df, notes = load_rows(p)
        except Exception as exc:  # noqa: BLE001 - never echo paths or messages
            errors[type(exc).__name__] += 1
            continue
        for k, v in notes.items():
            notes_total[k] += int(v)
        recs = pair_candidates(df)
        all_recs += recs
        n_meal_rows += len(recs)
        n_photo_rows += int(df["is_photo"].sum())
        n_meal_with_photo += int((df["is_photo"] & df["is_meal"]).sum())
        orphan_photos += photos_before_first_meal(df)
        counts = Counter(r["class"] for r in recs)
        per_part[lab] = {"n_meal_rows": len(recs), **{c: counts.get(c, 0) for c in (NO_CANDIDATE, SINGLE, MULTIPLE)}}
        for r in recs:
            o = r["offsets_min"]
            spacing += list(np.diff(o)) if len(o) > 1 else []
            if r["has_next_meal_row"]:
                gaps_all.append(r["next_meal_gap_min"])
                if r["next_same_type"]:
                    gaps_same.append(r["next_meal_gap_min"])
        # offset of EVERY non-meal photo from the nearest PRECEDING meal row, with no bound at all
        meal_t = df.loc[df["is_meal"], "t"].to_numpy()
        for t in df.loc[df["is_photo"] & ~df["is_meal"], "t"].to_numpy():
            k = np.searchsorted(meal_t, t, side="left") - 1
            if k >= 0:
                post_meal_nonmeal.append(float((t - meal_t[k]) / np.timedelta64(1, "m")))
        if "Image path" in df.columns:
            tok[lab] = {"on_meal_rows": Counter(), "on_non_meal_rows": Counter()}
            for name, is_meal in zip(df.loc[df["is_photo"], "Image path"], df.loc[df["is_photo"], "is_meal"]):
                tok[lab]["on_meal_rows" if is_meal else "on_non_meal_rows"].update(_tokens(name))
    cls = Counter(r["class"] for r in all_recs)
    n = len(all_recs)
    first_off = [r["offsets_min"][0] for r in all_recs if r["offsets_min"]]
    last_off = [r["offsets_min"][-1] for r in all_recs if r["offsets_min"]]
    single_off = [r["offsets_min"][0] for r in all_recs if r["class"] == SINGLE]
    return {
        "_privacy": "aggregate-only: counts, minute distributions, generic file-name tokens listed only when present in >= "
                    f"{min_participants} participants, anonymous labels; no paths, file names, dates or identifiers",
        "n_files": len(files), "read_errors_by_exception_type": dict(errors), "file_notes": dict(notes_total),
        "rows": {"meal_rows": n_meal_rows, "photo_rows": n_photo_rows, "meal_rows_with_own_photo": n_meal_with_photo,
                 "meal_rows_without_own_photo": n_meal_rows - n_meal_with_photo, "photo_rows_before_first_meal_row": orphan_photos},
        "classification": {c: {"n": cls.get(c, 0), "share": (cls.get(c, 0) / n) if n else None} for c in (NO_CANDIDATE, SINGLE, MULTIPLE)},
        "reconciles": sum(cls.values()) == n_meal_rows,
        "flags": {"last_meal_row_in_file": n - sum(r["has_next_meal_row"] for r in all_recs),
                  "next_meal_row_has_same_type": sum(r["next_same_type"] for r in all_recs),
                  "no_candidate_and_followed_by_meal_row": sum(r["class"] == NO_CANDIDATE and r["has_next_meal_row"] for r in all_recs),
                  "multiple_candidates_with_next_meal_row_same_type": sum(r["class"] == MULTIPLE and r["next_same_type"] for r in all_recs)},
        "candidate_count_distribution": dict(sorted(Counter(r["n_candidates"] for r in all_recs).items())),
        "minutes_from_meal_row_to_first_candidate": _dist(first_off),
        "minutes_from_meal_row_to_last_candidate": _dist(last_off),
        "minutes_to_the_only_candidate_when_unique": _dist(single_off),
        "minutes_between_consecutive_candidates": _dist(spacing),
        "minutes_between_consecutive_meal_rows": _dist(gaps_all),
        "minutes_between_consecutive_meal_rows_same_type": _dist(gaps_same),
        "minutes_from_preceding_meal_row_to_every_non_meal_photo_unbounded": _dist(post_meal_nonmeal),
        "file_name_markers": token_report(tok, min_participants),
        "per_participant": per_part,
        "not_established": [
            "which photo (if any) is the official 'after eating' photo",
            "whether the Timestamp of a meal row is the before-photo time, the meal start, or a logging time",
            "whether additional non-meal photos are snacks, retakes, or after-photos",
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--seed", type=int, default=0, help="Seed for anonymous participant labels.")
    ap.add_argument("--min-participants", type=int, default=5, help="k-anonymity floor for listing file-name tokens.")
    ap.add_argument("--report-out", default=None, help="Local JSON copy (default data/interim/audit_local/meal_photo_pairing.json).")
    args = ap.parse_args(argv)
    try:
        root = get_dataset_root(args.data_root)
    except DatasetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    files = discover_participant_files(root)
    if not files:
        print("error: no CSV with both 'Timestamp' and 'Meal Type' columns was found under the dataset root.", file=sys.stderr)
        return 2
    rep = audit(files, seed=args.seed, min_participants=args.min_participants)
    out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / "meal_photo_pairing.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rep, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
