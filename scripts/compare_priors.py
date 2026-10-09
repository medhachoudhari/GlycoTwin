"""Prior-versus-prior comparison (empirical Bayes vs blueprint) for Models B and C, from the four LOCAL forecast files and their run reports (aggregate output only).

Inputs (all produced by run_model_b.py / run_model_c.py on the SAME event table, folds and seed; see docs/REAL_DATA_RUNBOOK.md section 3):
  --b-eb / --b-eb-report   Model B, empirical Bayes (primary), activity-eligible population
  --b-bp / --b-bp-report   Model B, --prior-scheme blueprint, activity-eligible population
  --c-eb / --c-eb-report   Model C, empirical Bayes (primary)
  --c-bp / --c-bp-report   Model C, --prior-scheme blueprint --gamma-relative-sd <w>
The comparison REFUSES (exit 3) unless the four arms are an identical evaluation (events, participants, folds, labels, rises, event table file and settings,
seed, channel, fold hash) and the prior metadata matches each arm. Nothing is re-run, aligned or dropped; no input file is modified; the report path may not
be an input path. Differences are second-named minus first-named; negative favours the blueprint prior / Model C.

Usage (PowerShell): see docs/REAL_DATA_RUNBOOK.md section 3b.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from glycotwin.config import REPO_ROOT
from glycotwin.models.prior_compare import ARMS, PriorComparisonError, prior_comparison_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for a in ARMS:
        flag = a.replace("_", "-")
        ap.add_argument(f"--{flag}", required=True, help=f"Forecast CSV of arm {a}.")
        ap.add_argument(f"--{flag}-report", required=True, help=f"Run report JSON (with its manifest) of arm {a}.")
    ap.add_argument("--expect-events", type=int, default=None)
    ap.add_argument("--expect-participants", type=int, default=None)
    ap.add_argument("--expect-gamma", type=float, default=None, help="Refuse unless the blueprint Model C arm used exactly this gamma relative sd.")
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--report-out", default=None, help="Local JSON (default data/interim/audit_local/prior_comparison.json); may not be an input path.")
    args = ap.parse_args(argv)
    csvs = {a: Path(getattr(args, a)) for a in ARMS}
    reps = {a: Path(getattr(args, a + "_report")) for a in ARMS}
    for p in list(csvs.values()) + list(reps.values()):
        if not p.exists():
            print("error: an input file was not found.", file=sys.stderr)
            return 2
    out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / "prior_comparison.json"
    if out.resolve() in {p.resolve() for p in list(csvs.values()) + list(reps.values())}:
        print("error: the report path would overwrite an input file.", file=sys.stderr)
        return 2
    try:
        report = prior_comparison_report({a: pd.read_csv(p) for a, p in csvs.items()}, {a: json.loads(p.read_text(encoding="utf-8")) for a, p in reps.items()},
                                         n_boot=args.n_boot, seed=args.seed, expected_events=args.expect_events,
                                         expected_participants=args.expect_participants, expected_gamma=args.expect_gamma)
    except PriorComparisonError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
