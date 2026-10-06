"""Build the meal event table for every participant file and report AGGREGATE counts only.

One command answers, from the real data: how many meals exist, how many pass the window checks, why
the rest were excluded, how many are isolated / eligible for Models A-B and for the activity
comparison, how many exceed the threshold (the blueprint's Week-1 event-count checkpoint), and
which columns differ between participant files (schema groups).

Privacy: stdout and the JSON report contain only counts, reason names, column NAMES and anonymous
labels (P1..Pn, seeded). The full event table (one row per meal, participant-level) is written to
data/processed/ which is git-ignored; never commit it.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\build_event_table.py                      # Dexcom channel
    python scripts\\build_event_table.py --channel "Libre GL"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root
from glycotwin.data.events import build_event_table, event_count_report
from glycotwin.data.meals import load_participant_data, participant_id_from_path


def discover_participant_files(root: Path) -> list[Path]:
    found = []
    for dirpath, _d, files in os.walk(root):
        for f in sorted(files):
            if f.lower().endswith(".csv"):
                p = Path(dirpath) / f
                try:
                    cols = {str(c).strip() for c in pd.read_csv(p, nrows=0).columns}
                except Exception:  # noqa: BLE001
                    continue
                if {"Timestamp", "Meal Type"} <= cols:
                    found.append(p)
    return sorted(found)


def schema_report(headers: dict[str, list[str]]) -> dict:
    """Group participants by their exact column set. Column NAMES are not identifying; group sizes and
    the names that differ answer 'which columns do participants lack?' without naming anyone."""
    groups = Counter(tuple(sorted(h)) for h in headers.values())
    common = set.intersection(*(set(h) for h in headers.values())) if headers else set()
    union = set.union(*(set(h) for h in headers.values())) if headers else set()
    return {
        "n_files": len(headers), "n_distinct_column_sets": len(groups),
        "columns_in_every_file": sorted(common), "columns_missing_from_some_files": sorted(union - common),
        "availability_counts": {c: sum(c in h for h in headers.values()) for c in sorted(union)},
        "column_set_groups": [{"n_files": n, "columns_beyond_common": sorted(set(cols) - common),
                               "n_columns": len(cols)} for cols, n in groups.most_common()],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--channel", default="Dexcom GL", choices=["Dexcom GL", "Libre GL"])
    ap.add_argument("--max-gap-minutes", type=float, default=15, help="Leading/internal CGM gap limit (rule R6 is open).")
    ap.add_argument("--baseline-lag-minutes", type=float, default=None, help="Default: the channel's documented native interval.")
    ap.add_argument("--allow-overlap", action="store_true", help="Keep meals whose windows overlap another meal as eligible.")
    ap.add_argument("--on-duplicates", choices=["raise", "keep_first"], default="keep_first",
                    help="Duplicate timestamps within a file (rule R11 is open); keep_first counts what it drops.")
    ap.add_argument("--seed", type=int, default=0, help="Seed for the anonymous participant labels.")
    ap.add_argument("--table-out", default=None, help="Local event table CSV (default data/processed/event_table_<channel>.csv).")
    ap.add_argument("--report-out", default=None, help="Local JSON report (default data/interim/audit_local/event_counts_<channel>.json).")
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

    tables, headers, errors, dup_dropped = {}, {}, Counter(), 0
    for p in files:
        pid = participant_id_from_path(p)
        try:
            df = load_participant_data(p)
            headers[pid] = [str(c) for c in df.columns if c != "Normalized Meal Type"]
            et = build_event_table(df, pid, cgm_col=args.channel, max_cgm_gap_minutes=args.max_gap_minutes,
                                   baseline_lag_minutes=args.baseline_lag_minutes, require_isolated=not args.allow_overlap,
                                   on_duplicate_timestamps=args.on_duplicates)
            tables[pid] = et
            dup_dropped += et.notes.get("duplicate_timestamp_rows_dropped", 0)
        except Exception as exc:  # noqa: BLE001 - never echo paths or messages
            errors[type(exc).__name__] += 1

    report = {
        "_privacy": "aggregate-only: anonymous labels, counts, reason names and column names; no rows or identifiers",
        "settings": {"channel": args.channel, "max_gap_minutes": args.max_gap_minutes, "baseline_lag_minutes": args.baseline_lag_minutes,
                     "require_isolated": not args.allow_overlap, "on_duplicates": args.on_duplicates, "files_found": len(files)},
        "read_errors_by_exception_type": dict(errors), "duplicate_timestamp_rows_dropped": dup_dropped,
        "schema": schema_report(headers),
        "event_counts": event_count_report(tables, anonymize_seed=args.seed),
        "not_established": ["glycaemic-group counts (bio.csv is not ingested yet)", "meal-row semantics (rule R1)",
                            "whether the 180 mg/dL target has enough events (compare counts to the planned comparisons)"],
    }
    safe = args.channel.replace(" ", "_")
    table_out = Path(args.table_out) if args.table_out else REPO_ROOT / "data" / "processed" / f"event_table_{safe}.csv"
    report_out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / f"event_counts_{safe}.json"
    table_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([t.table for t in tables.values()], ignore_index=True).to_csv(table_out, index=False) if tables else None
    text = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    report_out.write_text(text, encoding="utf-8")
    print(text)
    print("\n(aggregate-only; the participant-level table was written to a git-ignored local file)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
