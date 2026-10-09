"""Model A (population XGBoost baseline): participant-level, group-stratified 5-fold out-of-fold evaluation.

Reads the LOCAL event table written by build_event_table.py (core-eligible events of the chosen channel) and bio.csv
(glycaemic group via the verified `subject` identifier; a positional mapping is never used). Prints aggregate results
only: counts, fold composition and metrics. Participant-level files (the fold assignment and the out-of-fold
predictions) are written to git-ignored local folders.

Research baseline only: fixed configuration, no tuning, no imputation, no resampling, no clinical claim.
Primary channel: Libre GL (proposed decision D14). Dexcom is a later sensitivity analysis; channels are never averaged.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\build_event_table.py --channel "Libre GL"      # if the table does not exist yet
    python scripts\\run_model_a.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root
from glycotwin.data.groups import GroupMappingError, participant_groups
from glycotwin.models.prior_schemes import event_table_info
from glycotwin.models.model_a_cv import DEFAULT_THRESHOLD, run_model_a


def _find_bio(root: Path):
    for dirpath, _d, files in os.walk(root):
        for f in sorted(files):
            if f.lower() == "bio.csv":
                return Path(dirpath) / f
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT (used to find bio.csv).")
    ap.add_argument("--bio-path", default=None)
    ap.add_argument("--channel", default="Libre GL", choices=["Libre GL", "Dexcom GL"])
    ap.add_argument("--event-table", default=None, help="Default: data/processed/event_table_<channel>.csv")
    ap.add_argument("--seed", type=int, default=0, help="Seed for the fold assignment and the bootstrap.")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Fixed decision threshold for sensitivity/specificity/precision/F1.")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--report-out", default=None, help="Local JSON copy (default data/interim/audit_local/model_a_<channel>.json).")
    ap.add_argument("--oof-out", default=None, help="Local out-of-fold predictions CSV (default data/processed/model_a_oof_<channel>.csv).")
    ap.add_argument("--folds-out", default=None, help="Local fold assignment JSON (default data/interim/audit_local/model_a_folds_<channel>.json).")
    args = ap.parse_args(argv)

    safe = args.channel.replace(" ", "_")
    table_path = Path(args.event_table) if args.event_table else REPO_ROOT / "data" / "processed" / f"event_table_{safe}.csv"
    if not table_path.exists():
        print("error: the event table was not found; run build_event_table.py for this channel first (or pass --event-table).", file=sys.stderr)
        return 2
    if safe.split("_")[0].lower() not in table_path.name.lower():
        print(f"error: the event table file name does not mention the channel '{args.channel}'; refusing to guess which CGM channel it holds "
              "(rename it or pass the right file).", file=sys.stderr)
        return 2
    try:
        root = get_dataset_root(args.data_root)
    except DatasetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    bio_path = Path(args.bio_path) if args.bio_path else _find_bio(root)
    if bio_path is None or not bio_path.exists():
        print("error: bio.csv was not found (use --bio-path).", file=sys.stderr)
        return 2

    table = pd.read_csv(table_path)
    if "eligible_core" not in table.columns:
        print("error: the event table has no eligible_core column.", file=sys.stderr)
        return 2
    events = table[table["eligible_core"].astype(bool)].copy()
    try:
        group_of = participant_groups(pd.read_csv(bio_path), events["participant_id"].unique())
    except GroupMappingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report, oof, folds = run_model_a(events, group_of, seed=args.seed, threshold=args.threshold, n_boot=args.n_boot,
                                     channel=args.channel, event_table_name=table_path.name)
    report["manifest"].update(event_table_info(table_path))
    report["manifest"]["protocol_arguments"] = {"channel": args.channel, "seed": args.seed, "n_bootstrap": args.n_boot, "threshold": args.threshold}
    report_out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / f"model_a_{safe}.json"
    oof_out = Path(args.oof_out) if args.oof_out else REPO_ROOT / "data" / "processed" / f"model_a_oof_{safe}.csv"
    folds_out = Path(args.folds_out) if args.folds_out else REPO_ROOT / "data" / "interim" / "audit_local" / f"model_a_folds_{safe}.json"
    for p in (report_out, oof_out, folds_out):
        p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    report_out.write_text(text, encoding="utf-8")
    oof.to_csv(oof_out, index=False)
    folds_out.write_text(json.dumps({"_note": "participant-level; local only, never commit", "assignment": folds, "groups": group_of}, indent=2), encoding="utf-8")
    print(text)
    print("\n(aggregate-only; participant-level fold assignment and out-of-fold predictions were written to git-ignored local files)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
