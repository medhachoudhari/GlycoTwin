"""Run the key experiment (Models A, B, C and controls) on the local event table. Aggregate output only.

Reads the participant-level event table written by scripts/build_event_table.py (git-ignored), keeps
meals eligible for the activity comparison, runs the leave-one-participant-out prequential harness
and prints paired, participant-clustered differences with intervals.

It REFUSES to run when the data are too thin for the planned comparisons (override with
--force-underpowered, which stamps the report as underpowered). The minimums below are placeholders
to be confirmed by the researcher BEFORE looking at results (Human Action Queue, docs/PROJECT_STATUS.md).

Interpretation rules baked into the report: an interval containing 0 is inconclusive, not "no effect";
nothing here is clinical evidence; every comparison is reported, none is chosen after the fact.

Usage (PowerShell):
    python scripts\\run_experiment.py [--table data\\processed\\event_table_Dexcom_GL.csv]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from glycotwin.config import REPO_ROOT
from glycotwin.models.experiment import build_manifest, paired_cluster_bootstrap, run_prequential_experiment

PLACEHOLDER_MINIMUMS = {"participants": 20, "events_per_participant_median": 8, "positives": 30, "negatives": 30}
COMPARISONS = [  # (a, b, metric, subset) fixed in advance; negative estimate favours a
    ("B", "frozen_B", "brier", "all"), ("B", "B_shuffled", "brier", "all"), ("B", "personal_rate", "brier", "all"),
    ("C", "B", "brier", "all"), ("C", "B", "brier", "active"), ("C", "B", "brier", "sedentary"),
    ("C", "C_perm_activity", "brier", "all"), ("B", "A", "brier", "all"), ("C", "A", "brier", "all"),
    ("C", "B", "log_loss", "active"), ("B", "frozen_B", "mae_rise", "all"), ("C", "B", "mae_rise", "active"),
]


def sample_size_check(ev: pd.DataFrame) -> dict:
    per = ev.groupby("participant_id").size()
    got = {"participants": int(per.size), "events_per_participant_median": float(per.median()) if len(per) else 0.0,
           "positives": int((ev["label_exceeds_180"] == 1).sum()), "negatives": int((ev["label_exceeds_180"] == 0).sum())}
    short = {k: {"have": got[k], "need": v} for k, v in PLACEHOLDER_MINIMUMS.items() if got[k] < v}
    return {"observed": got, "placeholder_minimums": PLACEHOLDER_MINIMUMS, "shortfalls": short, "adequate": not short}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--table", default=str(REPO_ROOT / "data" / "processed" / "event_table_Dexcom_GL.csv"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--force-underpowered", action="store_true", help="Run anyway; the report is stamped underpowered.")
    ap.add_argument("--no-model-a", action="store_true", help="Skip the population XGBoost.")
    ap.add_argument("--out", default=None, help="Local JSON (default data/interim/audit_local/experiment_report.json).")
    args = ap.parse_args(argv)

    table = Path(args.table)
    if not table.exists():
        print("error: event table not found. Create it first with scripts\\build_event_table.py (the path was not printed on purpose).", file=sys.stderr)
        return 2
    ev = pd.read_csv(table, parse_dates=["meal_time"])
    ev = ev[ev["eligible_activity"].astype(bool)].copy()
    check = sample_size_check(ev)
    if not check["adequate"] and not args.force_underpowered:
        print(json.dumps({"ran": False, "reason": "insufficient data for the planned comparisons", "sample_size": check,
                          "next": "resolve rules R6/R7/R9 or collect more events; or rerun with --force-underpowered for an explicitly underpowered look"}, indent=2))
        return 3

    records = run_prequential_experiment(ev, seed=args.seed, include_model_a=not args.no_model_a)
    results = []
    for a, b, metric, sub in COMPARISONS:
        if a not in set(records["model"]) or b not in set(records["model"]):
            continue
        subset = None if sub == "all" else (records["is_active"] if sub == "active" else ~records["is_active"])
        results.append({"subset": sub, **paired_cluster_bootstrap(records, a, b, metric, subset=subset, n_boot=args.n_boot, seed=args.seed)})
    report = {"_privacy": "aggregate-only", "underpowered": not check["adequate"], "sample_size": check,
              "manifest": build_manifest({"n_boot": args.n_boot, "comparisons": [list(c) for c in COMPARISONS],
                                          "model_a": not args.no_model_a, "cv": "leave-one-participant-out"}, ev, args.seed),
              "comparisons": results,
              "reading_rules": ["an interval containing 0 is inconclusive, not 'no effect'",
                                "negative estimate favours model_a (lower Brier, log loss, MAE is better)",
                                "all comparisons are pre-listed; none were chosen after seeing results",
                                "not clinical evidence; Model A is raw XGBoost (isotonic calibration not applied)"]}
    text = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out = Path(args.out) if args.out else REPO_ROOT / "data" / "interim" / "audit_local" / "experiment_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
