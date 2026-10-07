"""Model B (personalised Bayesian carbohydrate sensitivity, no activity term): sequential forecast -> observe -> update
inside the same participant-level, group-stratified 5-fold CV as Model A, with a paired comparison against Model A.

Reads the LOCAL core-eligible event table of the channel (default Libre GL) and bio.csv (groups via the verified
`subject` identifier only). Prints aggregate results only. Participant-level files (sequential forecasts, posterior
trajectories, fold assignment) go to git-ignored local folders. Research model; not clinically validated.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\run_model_b.py
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
from glycotwin.models.model_a_cv import DEFAULT_THRESHOLD
from glycotwin.models.model_b_cv import run_model_b


def _find_bio(root: Path):
    for dirpath, _d, files in os.walk(root):
        for f in sorted(files):
            if f.lower() == "bio.csv":
                return Path(dirpath) / f
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--bio-path", default=None)
    ap.add_argument("--channel", default="Libre GL", choices=["Libre GL", "Dexcom GL"])
    ap.add_argument("--event-table", default=None, help="Default: data/processed/event_table_<channel>.csv")
    ap.add_argument("--seed", type=int, default=0, help="Same default seed as Model A, so the folds are identical.")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out-dir", default=None, help="Local output folder for the JSON report (default data/interim/audit_local).")
    args = ap.parse_args(argv)

    safe = args.channel.replace(" ", "_")
    table_path = Path(args.event_table) if args.event_table else REPO_ROOT / "data" / "processed" / f"event_table_{safe}.csv"
    if not table_path.exists():
        print("error: the event table was not found; run build_event_table.py for this channel first (or pass --event-table).", file=sys.stderr)
        return 2
    if safe.split("_")[0].lower() not in table_path.name.lower():
        print(f"error: the event table file name does not mention the channel '{args.channel}'; refusing to guess.", file=sys.stderr)
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
    try:
        report, oof_b, oof_a, trajs, folds = run_model_b(events, group_of, seed=args.seed, threshold=args.threshold,
                                                         n_boot=args.n_boot, channel=args.channel, event_table_name=table_path.name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "data" / "interim" / "audit_local"
    proc = REPO_ROOT / "data" / "processed" if not args.out_dir else out_dir
    out_dir.mkdir(parents=True, exist_ok=True); proc.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    (out_dir / f"model_b_{safe}.json").write_text(text, encoding="utf-8")
    oof_b.to_csv(proc / f"model_b_sequential_forecasts_{safe}.csv", index=False)
    (out_dir / f"model_b_trajectories_{safe}.json").write_text(
        json.dumps({"_note": "participant-level; local only, never commit", "folds": folds, "trajectories": trajs}, indent=1,
                   default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
    print(text)
    print("\n(aggregate-only; participant-level forecasts and posterior trajectories were written to git-ignored local files)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
