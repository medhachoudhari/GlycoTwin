"""Model C (activity-conditioned personalised Bayesian carbohydrate sensitivity): sequential forecast -> observe -> update inside the
same participant-level, group-stratified 5-fold CV and seed as Models A and B.

    rise = (beta_i + gamma_i * activity) * carbs      (no intercept; raw, un-centred pre-meal activity; blueprint form)

Reads the LOCAL event table of the channel (default Libre GL) and bio.csv (groups via the verified `subject` identifier only).
Population: core-eligible AND activity-eligible events. The folds are built from ALL core-eligible participants, exactly as for
Models A and B. Prints aggregate results only; participant-level files (sequential forecasts, posterior trajectories) go to
git-ignored local folders. The paired C-vs-B comparison needs Model B re-run on the SAME activity-eligible subset and is a
separate step. Research model; not clinically validated.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\run_model_c.py
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
from glycotwin.models.prior_schemes import GAMMA_WIDTHS, PRIOR_SCHEMES, event_table_info
from glycotwin.models.model_a_cv import DEFAULT_THRESHOLD
from glycotwin.models.model_c_cv import run_model_c, select_activity_eligible


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
    ap.add_argument("--seed", type=int, default=0, help="Same default seed as Models A and B, so the folds are identical.")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out-dir", default=None, help="Local output folder (default data/interim/audit_local).")
    ap.add_argument("--prior-scheme", default="empirical_bayes", choices=list(PRIOR_SCHEMES),
                    help="empirical_bayes (default, the primary protocol) or blueprint (opt-in sensitivity analyses S2/S3). Non-default outputs get a "
                         "_prior-blueprint_gamma<width> suffix and never overwrite the primary run.")
    ap.add_argument("--gamma-relative-sd", type=float, default=None, choices=list(GAMMA_WIDTHS),
                    help="Blueprint prior only: prior sd of gamma = this x |beta| / rms(activity); prespecified widths 0.25, 0.5, 1, 2 (default 0.5 with --prior-scheme blueprint).")
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
    try:
        core = table[table["eligible_core"].astype(bool)].copy()
        events = select_activity_eligible(table)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        group_of = participant_groups(pd.read_csv(bio_path), core["participant_id"].unique())   # ALL core participants, as for A and B
    except GroupMappingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        report, oof, trajs, folds = run_model_c(events, group_of, seed=args.seed, threshold=args.threshold, n_boot=args.n_boot,
                                                channel=args.channel, event_table_name=table_path.name, n_core_events=int(len(core)),
                                                prior_scheme=args.prior_scheme, gamma_relative_sd=args.gamma_relative_sd)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report["manifest"].update(event_table_info(table_path))
    report["manifest"]["protocol_arguments"] = {"channel": args.channel, "prior_scheme": args.prior_scheme,
                                                "gamma_relative_sd": report["manifest"]["prior"]["gamma_relative_sd"], "seed": args.seed, "n_bootstrap": args.n_boot}
    if args.prior_scheme != "empirical_bayes":
        safe += f"_prior-{args.prior_scheme}_gamma{report['manifest']['prior']['gamma_relative_sd']:g}"          # never overwrite the primary run
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "data" / "interim" / "audit_local"
    proc = out_dir if args.out_dir else REPO_ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True); proc.mkdir(parents=True, exist_ok=True)
    dump = lambda o: o.item() if hasattr(o, "item") else str(o)
    text = json.dumps(report, indent=2, default=dump)
    (out_dir / f"model_c_{safe}.json").write_text(text, encoding="utf-8")
    oof.to_csv(proc / f"model_c_sequential_forecasts_{safe}.csv", index=False)
    (out_dir / f"model_c_trajectories_{safe}.json").write_text(
        json.dumps({"_note": "participant-level; local only, never commit", "folds": folds, "trajectories": trajs}, indent=1, default=dump), encoding="utf-8")
    print(text)
    print("\n(aggregate-only; participant-level forecasts and posterior trajectories were written to git-ignored local files)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
