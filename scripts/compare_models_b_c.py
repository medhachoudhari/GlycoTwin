"""Paired Model B versus Model C comparison from the two LOCAL sequential-forecast files (aggregate output only).

Inputs (written by run_model_b.py --population activity-eligible and run_model_c.py; participant-level, git-ignored):
  data/processed/model_b_sequential_forecasts_<channel>_activity_eligible.csv
  data/processed/model_c_sequential_forecasts_<channel>.csv
The comparison REFUSES to run unless both files hold exactly the same events, participants, folds and observed outcomes
(optionally with expected counts). Nothing is re-run; no model is refitted; the original outputs are only read.

Usage (PowerShell):
    python scripts\\compare_models_b_c.py --expect-events 963 --expect-participants 34
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from glycotwin.config import REPO_ROOT
from glycotwin.models.model_bc_compare import ComparisonIntegrityError, paired_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", default="Libre GL", choices=["Libre GL", "Dexcom GL"])
    ap.add_argument("--model-b", default=None, help="Default: data/processed/model_b_sequential_forecasts_<channel>_activity_eligible.csv")
    ap.add_argument("--model-c", default=None, help="Default: data/processed/model_c_sequential_forecasts_<channel>.csv")
    ap.add_argument("--expect-events", type=int, default=None, help="Refuse to run unless exactly this many matched events are found.")
    ap.add_argument("--expect-participants", type=int, default=None, help="Refuse to run unless exactly this many participants are found.")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model-a", default=None, help="Optional: Model A out-of-fold file (data/processed/model_a_oof_<channel>.csv). Adds the Model A vs B vs C key experiment; "
                                                    "refused unless Model A's shared events agree with B/C on participant, fold and label.")
    ap.add_argument("--groups-file", default=None, help="Optional CSV with columns participant_id,group. Adds the per-glycaemic-group breakdown; every participant needs a group.")
    ap.add_argument("--seed-check", default=None, help="Optional comma-separated extra bootstrap seeds (e.g. 1,2,3): reports how far the interval endpoints move with the seed.")
    ap.add_argument("--svg-out", default=None, help="Optional: write the aggregate reliability diagram (Model B and C) to this SVG file.")
    ap.add_argument("--report-out", default=None, help="Local JSON copy (default data/interim/audit_local/model_b_vs_c_<channel>.json); never overwrites the model outputs.")
    args = ap.parse_args(argv)
    safe = args.channel.replace(" ", "_")
    pb = Path(args.model_b) if args.model_b else REPO_ROOT / "data" / "processed" / f"model_b_sequential_forecasts_{safe}_activity_eligible.csv"
    pc = Path(args.model_c) if args.model_c else REPO_ROOT / "data" / "processed" / f"model_c_sequential_forecasts_{safe}.csv"
    for p in (pb, pc):
        if not p.exists():
            print("error: a forecast file was not found; run the Model B (--population activity-eligible) and Model C scripts first.", file=sys.stderr)
            return 2
    if "activity_eligible" not in pb.name:
        print("error: the Model B file name does not say activity_eligible; the paired comparison needs Model B run on Model C's exact events.", file=sys.stderr)
        return 2
    out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / f"model_b_vs_c_{safe}.json"
    if out.resolve() in (pb.resolve(), pc.resolve()):
        print("error: the report path would overwrite a model output.", file=sys.stderr)
        return 2
    try:
        oof_a = None
        if args.model_a:
            if not Path(args.model_a).exists():
                print("error: the Model A file was not found.", file=sys.stderr)
                return 2
            oof_a = pd.read_csv(args.model_a)
        group_of = None
        if args.groups_file:
            if not Path(args.groups_file).exists():
                print("error: the groups file was not found.", file=sys.stderr)
                return 2
            gdf = pd.read_csv(args.groups_file)
            if not {"participant_id", "group"} <= set(gdf.columns):
                print("error: the groups file needs the columns participant_id and group.", file=sys.stderr)
                return 2
            group_of = dict(zip(gdf["participant_id"], gdf["group"]))
        b_df, c_df = pd.read_csv(pb), pd.read_csv(pc)
        report = paired_report(b_df, c_df, n_boot=args.n_boot, seed=args.seed, expected_events=args.expect_events,
                               expected_participants=args.expect_participants, oof_a=oof_a, group_of=group_of)
        if args.seed_check:
            seeds = [int(x) for x in args.seed_check.split(",") if x.strip()]
            spread = {}
            runs = [report] + [paired_report(b_df, c_df, n_boot=args.n_boot, seed=sd) for sd in seeds]
            for k in report["metrics"]:
                los = [r["metrics"][k]["ci95"][0] for r in runs]
                his = [r["metrics"][k]["ci95"][1] for r in runs]
                spread[k] = {"lower_endpoint_range": [min(los), max(los)], "upper_endpoint_range": [min(his), max(his)],
                             "ci_excludes_zero_in_every_run": bool(all(r["metrics"][k]["ci_excludes_zero"] for r in runs)),
                             "ci_excludes_zero_in_some_runs_only": bool(0 < sum(r["metrics"][k]["ci_excludes_zero"] for r in runs) < len(runs))}
            report["bootstrap_seed_sensitivity"] = {"seeds": [args.seed] + seeds, "n_boot": args.n_boot, "metrics": spread,
                                                    "note": "Monte Carlo variation of the interval endpoints only; it says nothing about sampling variability of the participants."}
    except ComparisonIntegrityError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    report["channel"] = args.channel
    if args.svg_out:
        from glycotwin.models.reliability_svg import reliability_svg
        svg = reliability_svg({"Model B": report["reliability_bins_10"]["model_b"], "Model C": report["reliability_bins_10"]["model_c"]},
                              title="Reliability: Model B vs Model C", subtitle=f"{report['integrity']['n_events']} matched events, {report['integrity']['n_participants']} participants ({args.channel})")
        Path(args.svg_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.svg_out).write_text(svg, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
