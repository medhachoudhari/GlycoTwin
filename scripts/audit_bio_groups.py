"""READ-ONLY audit of bio.csv: which glycaemic group does each CGMacros participant belong to?

Sources (nothing here is invented):
  * The official CGMacros README states the cohort is 15 healthy, 16 pre-diabetes and 14 T2D participants
    (45 in total; participants 24, 25, 37 and 40 did not complete the study and are not in the dataset).
  * The authors' released analysis notebook (`parse_data.ipynb`, PSI-TAMU/CGMacros) derives the group from the
    `A1c PDL (Lab)` column of bio.csv: A1c < 5.7 -> healthy; 5.7 <= A1c <= 6.4 -> pre-diabetes; A1c > 6.4 -> T2D.
    The same notebook links bio.csv rows to participants BY POSITION (row i <-> i-th participant folder in sorted
    order) and uses no identifier column. Neither the README nor the notebook documents that alignment as a
    guarantee, so this script reports the mapping as VERIFIED only if bio.csv carries an identifier column that
    matches the participant files; otherwise it is reported as POSITIONAL and UNVERIFIED.
The script does not assume more than that. It reports what it can establish from the file and lists what stays
unresolved (identifier, official label vs derived label, A1c timing, medication status).

Output is aggregate-only: field (column) names, category names and counts. No participant identifiers, no
per-participant values, no timestamps. A1c values are never printed; only counts of values in each class.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\audit_bio_groups.py
    python scripts\\audit_bio_groups.py --event-table data\\processed\\event_table_Libre_GL.csv   # adds per-group event counts
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root
from glycotwin.data.discovery import discover_participant_files

# Official README (cohort composition). Not per-participant labels.
README_GROUP_SIZES = {"healthy": 15, "pre-diabetes": 16, "t2d": 14}
README_MISSING_PARTICIPANT_NUMBERS = (24, 25, 37, 40)
A1C_COLUMN_FROM_NOTEBOOK = "A1c PDL (Lab)"
FASTING_GLUCOSE_COLUMN_FROM_NOTEBOOK = "Fasting GLU - PDL (Lab)"
GROUPS = ("healthy", "pre-diabetes", "t2d")
UNKNOWN = "unknown"
PLANNED_FOLDS = 5          # blueprint: seeded 5-fold participant CV stratified by glycaemic group

_ID_NAME = re.compile(r"(?i)(^|[^a-z])(id|subject|participant|patient|sub)([^a-z]|$)")
_GROUP_NAME = re.compile(r"(?i)group|diagnos|status|class|categor|diabet|glyc")
_MED_NAME = re.compile(r"(?i)medic|drug|metformin|therap|treat")
_NUM_PREFIX = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)")


# ----------------------------------------------------------------------------- pure logic

def parse_numeric(value):
    """(number or NaN, annotated?) - accepts '5.4' and annotated lab strings such as '5.4 (low)'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan, False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value), False
    s = str(value)
    m = _NUM_PREFIX.match(s)
    if not m:
        return np.nan, False
    return float(m.group(1)), s.strip() != m.group(1)


def classify_a1c(a1c: float) -> str:
    """The authors' notebook rule. Both cut-offs are inclusive on the pre-diabetes side."""
    if a1c is None or not np.isfinite(a1c):
        return UNKNOWN
    if a1c < 5.7:
        return "healthy"
    if a1c <= 6.4:
        return "pre-diabetes"
    return "t2d"


def classify_fasting_glucose(g: float) -> str:
    """DIAGNOSTIC ONLY (general clinical convention, not CGMacros documentation): <100 / 100-125 / >=126 mg/dL."""
    if g is None or not np.isfinite(g):
        return UNKNOWN
    return "healthy" if g < 100 else "pre-diabetes" if g < 126 else "t2d"


def participant_number(stem: str):
    m = re.search(r"(\d+)\s*$", str(stem))
    return int(m.group(1)) if m else None


def to_number(v):
    """Participant number from an identifier cell: 7, 7.0, '7', 'CGMacros-007' -> 7; anything else -> None."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return int(v) if float(v) == int(v) else None
    return participant_number(v)


def find_id_column(bio: pd.DataFrame, file_numbers: set[int]) -> tuple[str | None, dict]:
    """A column whose NAME looks like an identifier AND whose values parse as unique participant numbers that
    match the participant files. Returns (column or None, evidence counts)."""
    ev: dict = {"candidate_columns_by_name": [], "columns_whose_values_match_participant_files": []}
    for c in bio.columns:
        if not _ID_NAME.search(str(c)):
            continue
        ev["candidate_columns_by_name"].append(str(c).strip())
        nums = [to_number(v) for v in bio[c].tolist()]
        ok = [n for n in nums if n is not None]
        if ok and len(set(ok)) == len(ok) and len(ok) == len(nums) and set(ok) & file_numbers:
            ev["columns_whose_values_match_participant_files"].append(str(c).strip())
    chosen = ev["columns_whose_values_match_participant_files"]
    return (next(c for c in bio.columns if str(c).strip() == chosen[0]) if len(chosen) == 1 else None), ev


def map_participants(bio: pd.DataFrame, file_numbers: list[int]) -> dict:
    """Row index -> participant number. Never guesses silently: says which method was used and whether it is verified."""
    nums = sorted(file_numbers)
    idcol, ev = find_id_column(bio, set(nums))
    res = {"identifier_evidence": ev, "n_participant_files": len(nums), "n_bio_rows": int(len(bio))}
    if idcol is not None:
        by = {i: to_number(v) for i, v in enumerate(bio[idcol].tolist())}
        res.update(method="identifier_column", verified=True, identifier_column_name=str(idcol).strip(), row_to_number=by)
    elif len(bio) == len(nums):
        res.update(method="positional", verified=False, row_to_number={i: n for i, n in enumerate(nums)},
                   caveat="no identifier column matches the participant files; rows are assumed to follow the sorted participant "
                          "order, as in the authors' notebook. This alignment is NOT documented in the files read and cannot be "
                          "checked from bio.csv alone.")
    else:
        res.update(method="none", verified=False, row_to_number={},
                   caveat="no identifier column and the number of rows differs from the number of participant files: a positional "
                          "mapping would be a guess, so none is made.")
    return res


def group_table(bio: pd.DataFrame, a1c_col, mapping: dict, file_numbers: list[int]) -> tuple[pd.DataFrame, dict]:
    """One row per participant file: its group (from A1c), or unknown / unmapped. Returns the table and counts."""
    values = [parse_numeric(v) for v in bio[a1c_col].tolist()]
    group_by_number = {}
    for i, n in mapping["row_to_number"].items():
        if n is None:
            continue
        group_by_number[n] = classify_a1c(values[i][0])
    rows = []
    for n in sorted(file_numbers):
        if n in group_by_number:
            rows.append({"number": n, "mapped": True, "group": group_by_number[n]})
        else:
            rows.append({"number": n, "mapped": False, "group": UNKNOWN})
    t = pd.DataFrame(rows)
    counts = {"n_participant_files": len(file_numbers), "n_bio_rows": int(len(bio)),
              "n_mapped": int(t["mapped"].sum()), "n_unmapped_participants": int((~t["mapped"]).sum()),
              "n_bio_rows_without_a_participant_file": int(sum(1 for n in mapping["row_to_number"].values() if n is None or n not in set(file_numbers))
                                                               + (len(bio) - len(mapping["row_to_number"]))),
              "n_unknown_group_among_mapped": int(((t["group"] == UNKNOWN) & t["mapped"]).sum())}
    dist = t[t["mapped"] & (t["group"] != UNKNOWN)]["group"].value_counts()
    tot = int(dist.sum())
    counts["participants_by_group"] = {g: {"n": int(dist.get(g, 0)), "percent_of_classified": (100.0 * int(dist.get(g, 0)) / tot) if tot else None} for g in GROUPS}
    counts["n_classified"] = tot
    return t, counts


def blueprint_compatibility(by_group: dict, n_folds: int = PLANNED_FOLDS) -> dict:
    sizes = {g: by_group[g]["n"] for g in GROUPS}
    return {"planned": f"seeded {n_folds}-fold participant CV stratified by glycaemic group, group sizes 15/16/14 (blueprint)",
            "group_sizes": sizes,
            "matches_readme_group_sizes": sizes == README_GROUP_SIZES,
            "readme_group_sizes": README_GROUP_SIZES,
            "every_group_has_at_least_n_folds_participants": all(v >= n_folds for v in sizes.values()),
            "stratified_kfold_feasible": all(v >= n_folds for v in sizes.values()),
            "smallest_group_participants": min(sizes.values()) if sizes else None}


def event_counts_by_group(events: pd.DataFrame, group_table_df: pd.DataFrame) -> dict:
    """Aggregate event counts per group from a local event table (participant_id like 'CGMacros-001')."""
    g = {int(r.number): r.group for r in group_table_df.itertuples()}
    ev = events.copy()
    ev["_group"] = [g.get(participant_number(p), UNKNOWN) for p in ev["participant_id"]]
    out = {}
    for name in list(GROUPS) + [UNKNOWN]:
        sub = ev[ev["_group"] == name]
        core = sub[sub["eligible_core"].astype(bool)] if "eligible_core" in sub else sub
        out[name] = {"n_participants_with_events": int(sub["participant_id"].nunique()), "n_extraction_valid": int(len(sub)),
                     "n_core_eligible": int(len(core)),
                     "n_positive": int((core["label_exceeds_180"] == 1).sum()), "n_negative": int((core["label_exceeds_180"] == 0).sum())}
    return out


# ----------------------------------------------------------------------------- orchestration

def find_bio(root: Path) -> Path | None:
    for dirpath, _d, files in os.walk(root):
        for f in sorted(files):
            if f.lower() == "bio.csv":
                return Path(dirpath) / f
    return None


def audit(bio_path: Path, participant_files: list[Path], event_table: pd.DataFrame | None = None) -> dict:
    bio = pd.read_csv(bio_path)
    raw_cols = [str(c) for c in bio.columns]
    bio.columns = [str(c).strip() for c in bio.columns]
    nums = [participant_number(p.stem) for p in participant_files]
    file_numbers = sorted(n for n in nums if n is not None)
    rep: dict = {
        "_privacy": "aggregate-only: field names, category names and counts; no identifiers, no per-participant values, no A1c values",
        "bio_table": {"n_rows": int(len(bio)), "n_columns": int(bio.shape[1]), "column_names": [c for c in raw_cols],
                      "column_names_with_leading_or_trailing_spaces": [c for c in raw_cols if c != c.strip()]},
        "participant_files": {"n": len(participant_files), "n_with_a_trailing_number_in_the_file_name": len(file_numbers),
                              "numbers_match_readme_missing_set": (len(file_numbers) == 45 and
                                  not set(README_MISSING_PARTICIPANT_NUMBERS) & set(file_numbers) and
                                  set(file_numbers) <= set(range(1, 50)))},
    }
    # candidate fields
    a1c_candidates = [c for c in bio.columns if re.search(r"(?i)a1c", c)]
    rep["candidate_fields"] = {
        "a1c_columns": a1c_candidates,
        "fasting_glucose_columns": [c for c in bio.columns if re.search(r"(?i)fasting.*(glu|bg)", c)],
        "explicit_group_like_columns_by_name": [c for c in bio.columns if _GROUP_NAME.search(c)],
        "medication_or_treatment_like_columns_by_name": [c for c in bio.columns if _MED_NAME.search(c)],
        "identifier_like_columns_by_name": [c for c in bio.columns if _ID_NAME.search(c)],
    }
    a1c_col = A1C_COLUMN_FROM_NOTEBOOK if A1C_COLUMN_FROM_NOTEBOOK in bio.columns else (a1c_candidates[0] if len(a1c_candidates) == 1 else None)
    rep["group_definition"] = {
        "source": "authors' notebook (A1c-based): healthy A1c < 5.7; pre-diabetes 5.7 <= A1c <= 6.4; t2d A1c > 6.4; README gives cohort sizes 15/16/14",
        "a1c_column_used": a1c_col,
        "a1c_column_name_matches_the_notebook_exactly": a1c_col == A1C_COLUMN_FROM_NOTEBOOK,
        "official_per_participant_group_label_found_in_bio_csv": bool(rep["candidate_fields"]["explicit_group_like_columns_by_name"]),
    }
    if a1c_col is None:
        rep["status"] = "UNRESOLVED: no unambiguous A1c column; no group assigned (nothing guessed)"
        rep["unresolved"] = _unresolved(rep, None)
        return rep
    vals = [parse_numeric(v) for v in bio[a1c_col].tolist()]
    arr = np.array([v[0] for v in vals], dtype=float)
    rep["a1c_column_quality"] = {"n_rows": len(arr), "n_missing_or_unparseable": int(np.isnan(arr).sum()),
                                 "n_annotated_strings_such_as_low_high": int(sum(v[1] for v in vals)),
                                 "n_exactly_at_5.7": int((arr == 5.7).sum()), "n_exactly_at_6.4": int((arr == 6.4).sum())}
    mapping = map_participants(bio, file_numbers)
    t, counts = group_table(bio, a1c_col, mapping, file_numbers)
    rep["mapping"] = {k: v for k, v in mapping.items() if k != "row_to_number"}
    rep["mapping_completeness"] = counts
    rep["glycaemic_groups"] = counts["participants_by_group"]
    rep["blueprint_compatibility"] = blueprint_compatibility(counts["participants_by_group"])
    fg = FASTING_GLUCOSE_COLUMN_FROM_NOTEBOOK if FASTING_GLUCOSE_COLUMN_FROM_NOTEBOOK in bio.columns else None
    if fg and mapping["row_to_number"]:
        glu = [parse_numeric(v)[0] for v in bio[fg].tolist()]
        cross: Counter = Counter()
        for i, n in mapping["row_to_number"].items():
            if n in set(file_numbers):
                cross[(classify_a1c(vals[i][0]), classify_fasting_glucose(glu[i]))] += 1
        rep["diagnostic_a1c_group_vs_fasting_glucose_category"] = {
            "_note": "DIAGNOSTIC ONLY: fasting-glucose categories use the general clinical convention (<100, 100-125, >=126 mg/dL), not CGMacros "
                     "documentation; this is not a second definition of the group",
            "counts_rows_a1c_group_columns_fasting_category": {f"{a}|{b}": int(n) for (a, b), n in sorted(cross.items())}}
    if event_table is not None:
        rep["event_counts_by_group"] = event_counts_by_group(event_table, t)
    rep["unresolved"] = _unresolved(rep, mapping)
    verified = mapping["verified"]
    sizes_ok = rep["blueprint_compatibility"]["matches_readme_group_sizes"]
    if mapping["method"] == "none":
        rep["status"] = "UNRESOLVED mapping"
    elif verified and sizes_ok:
        rep["status"] = "GROUPS ESTABLISHED (identifier-verified mapping; sizes match the README)"
    elif not sizes_ok:
        rep["status"] = ("GROUPS DERIVED BUT SIZES DO NOT MATCH THE README: check the A1c rule and the mapping before using them"
                         + ("" if verified else " (mapping is also positional and unverified)"))
    else:
        rep["status"] = "GROUPS DERIVED BUT MAPPING UNVERIFIED: rows are linked to participants by position only (sizes match the README)"
    return rep


def _unresolved(rep: dict, mapping) -> list:
    out = [
        "whether the official per-participant group label is the A1c-derived one: the README gives only cohort sizes; the derivation comes from the authors' notebook",
        "when the A1c was measured relative to the CGM recording (the file has 'Collection time' style columns; their meaning is not documented in what was read)",
        "medication / treatment status (the blueprint targets non-insulin-managed participants): " + (
            "candidate columns by name: " + ", ".join(rep["candidate_fields"]["medication_or_treatment_like_columns_by_name"]) if
            rep["candidate_fields"]["medication_or_treatment_like_columns_by_name"] else "no column with a medication-like name was found; "
            "note that an 'Insulin' column, if present, is a fasting lab value, not therapy"),
    ]
    if mapping is not None and not mapping.get("verified"):
        out.insert(0, "the link between bio.csv rows and participant files (positional only)")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--bio-path", default=None, help="Path to bio.csv (default: found under the dataset root).")
    ap.add_argument("--event-table", default=None, help="Optional local event table CSV (from build_event_table.py) for per-group event counts.")
    ap.add_argument("--report-out", default=None, help="Local JSON copy (default data/interim/audit_local/bio_groups.json).")
    args = ap.parse_args(argv)
    try:
        root = get_dataset_root(args.data_root)
    except DatasetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bio_path = Path(args.bio_path) if args.bio_path else find_bio(root)
    if bio_path is None or not bio_path.exists():
        print("error: bio.csv was not found under the dataset root (use --bio-path).", file=sys.stderr)
        return 2
    files = discover_participant_files(root)
    if not files:
        print("error: no participant CSV (Timestamp + Meal Type header) was found under the dataset root.", file=sys.stderr)
        return 2
    ev = pd.read_csv(args.event_table) if args.event_table else None
    rep = audit(bio_path, files, ev)
    out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / "bio_groups.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rep, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
