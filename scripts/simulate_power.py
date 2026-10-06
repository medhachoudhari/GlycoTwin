"""SIMULATION: what could the planned experiment detect, for assumed effect sizes and sample sizes?

This is a power analysis on SIMULATED data with a known generating process. It estimates how often the
harness (leave-one-participant-out prequential forecasts + participant-clustered bootstrap) would
report an interval that excludes zero, when the true effect is as assumed. It does NOT estimate any
effect in CGMacros; the heterogeneity, noise and effect sizes below are assumptions, not findings.

Use it to choose the minimum sample sizes (Human Action H8) BEFORE looking at real results.

Parameters (assumed, adjustable): sensitivity mean 0.7 mg/dL per gram of carbohydrate; the interaction
coefficient is the change in that sensitivity per unit of activity (activity in [0, 1]); an interaction
of -0.1 is roughly a 14% fall in sensitivity from sedentary to very active, -0.35 roughly 50%.

Usage:
    python scripts/simulate_power.py [--participants 20 45] [--events 8 15] [--effects 0 -0.1 -0.35] [--reps 12]
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from glycotwin.models.experiment import paired_cluster_bootstrap, run_prequential_experiment
from glycotwin.models.simulation import make_hierarchical_meals

ASSUMED = {"sens_mean": 0.7, "sens_sd": 0.2, "interaction_sd": 0.1, "noise_sd": 12.0, "intercept": 5.0}


def one_scenario(n_participants: int, n_events: int, effect: float, reps: int, seed: int, n_boot: int) -> dict:
    hits = {"C_beats_B_active": 0, "C_beats_B_all": 0, "B_beats_frozen": 0, "C_worse_than_B_active": 0}
    for r in range(reps):
        df = make_hierarchical_meals(n_participants, n_events, seed=seed * 1000 + r, interaction_mean=effect, **ASSUMED_KW)
        rec = run_prequential_experiment(df, seed=r)
        for key, a, b, sub in (("C_beats_B_active", "C", "B", rec["is_active"]), ("C_beats_B_all", "C", "B", None),
                               ("B_beats_frozen", "B", "frozen_B", None)):
            res = paired_cluster_bootstrap(rec, a, b, "brier", subset=sub, n_boot=n_boot, seed=r)
            if res["interval_excludes_zero"] and res["estimate"] < 0:
                hits[key] += 1
            if key == "C_beats_B_active" and res["interval_excludes_zero"] and res["estimate"] > 0:
                hits["C_worse_than_B_active"] += 1
    return {"n_participants": n_participants, "events_per_participant": n_events, "assumed_interaction": effect, "reps": reps,
            **{k: round(v / reps, 3) for k, v in hits.items()}}


ASSUMED_KW = {"sens_mean": ASSUMED["sens_mean"], "sens_sd": ASSUMED["sens_sd"], "interaction_sd": ASSUMED["interaction_sd"],
              "noise_sd": ASSUMED["noise_sd"], "intercept": ASSUMED["intercept"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--participants", type=int, nargs="+", default=[20, 45])
    ap.add_argument("--events", type=int, nargs="+", default=[8, 15])
    ap.add_argument("--effects", type=float, nargs="+", default=[0.0, -0.1, -0.35])
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--n-boot", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    if min(args.participants + args.events) < 2 or args.reps < 1:
        print("error: participants and events must be >= 2 and reps >= 1", file=sys.stderr)
        return 2
    rows = [one_scenario(n, e, eff, args.reps, args.seed, args.n_boot)
            for n in args.participants for e in args.events for eff in args.effects]
    report = {
        "WHAT_THIS_IS": "SIMULATION under assumed parameters; not an estimate of any effect in CGMacros",
        "assumed_parameters": ASSUMED, "reps_per_scenario": args.reps, "n_boot": args.n_boot, "seed": args.seed,
        "how_to_read": ["rows with assumed_interaction == 0 estimate the FALSE-POSITIVE rate (C_beats_B_* should be near 0.05 or below)",
                        "rows with a nonzero interaction estimate POWER: the share of simulated studies whose interval excludes zero",
                        "with few reps the rates are coarse; raise --reps before relying on a number"],
        "scenarios": rows,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
