"""Replay ONE participant of a LOCAL event table through the in-memory twin (forecast -> observe -> reconcile -> update).

The twin's prior is fitted on all OTHER participants' activity-eligible events (the participant's own events are excluded automatically),
then the participant's events are replayed in time order with the outcome-window rule (an outcome is learned only after its 120-minute window
closes, and never before its own forecast). This is deployment-style initialisation, not the 5-fold evaluation protocol of the model comparison.

Privacy: the full trajectory (forecasts, observations, parameter history) is written to a git-ignored LOCAL file; stdout shows counts only.
The participant is chosen by an anonymous index into the sorted list of eligible participants. In-memory only: no database, no web framework.

Usage (PowerShell):
    python scripts\\replay_participant.py --participant-index 0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from glycotwin.config import REPO_ROOT
from glycotwin.twin.adapter import initialize_twin_from_population, prepare_participant_events
from glycotwin.twin.insight import hit_rate_trend, parameter_history, posterior_convergence, reconciliation_report, twin_insight
from glycotwin.twin.state_view import twin_state_view
from glycotwin.twin.replay import replay_lifecycle
from glycotwin.twin.state import TwinStore


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", default="Libre GL", choices=["Libre GL", "Dexcom GL"])
    ap.add_argument("--event-table", default=None, help="Default: data/processed/event_table_<channel>.csv")
    ap.add_argument("--participant-index", type=int, default=0, help="Anonymous index into the sorted eligible participants.")
    ap.add_argument("--reference-activity", type=float, default=None,
                    help="Activity level at which Model C's sensitivity is reported (default: the median activity of the replayed events).")
    ap.add_argument("--out-dir", default=None, help="Local output folder (default data/interim/audit_local).")
    args = ap.parse_args(argv)
    safe = args.channel.replace(" ", "_")
    table_path = Path(args.event_table) if args.event_table else REPO_ROOT / "data" / "processed" / f"event_table_{safe}.csv"
    if not table_path.exists():
        print("error: the event table was not found; run build_event_table.py for this channel first (or pass --event-table).", file=sys.stderr)
        return 2
    if safe.split("_")[0].lower() not in table_path.name.lower():
        print(f"error: the event table file name does not mention the channel '{args.channel}'; refusing to guess.", file=sys.stderr)
        return 2
    table = pd.read_csv(table_path)
    try:
        need = ["participant_id", "eligible_core", "eligible_activity"]
        if any(c not in table.columns for c in need):
            raise ValueError("the event table lacks eligibility columns")
        pop = table[table["eligible_core"].astype(bool) & table["eligible_activity"].astype(bool)]
        ids = sorted(pop["participant_id"].unique())
        if not 0 <= args.participant_index < len(ids):
            raise ValueError(f"participant index must be between 0 and {len(ids) - 1}")
        pid = ids[args.participant_index]
        events = prepare_participant_events(table, pid)
        store = TwinStore()
        initialize_twin_from_population(store, pid, pop, profile={"channel": args.channel})
        ref = args.reference_activity if args.reference_activity is not None else float(events["activity_level"].median())
        log = replay_lifecycle(store, pid, events)
        result = {"_note": "participant-level; local only, never commit", "participant_id": pid, "channel": args.channel, "reference_activity": ref,
                  "lifecycle_log": log, "twin_insight": twin_insight(store, pid, ref), "parameter_history": parameter_history(store, pid, ref),
                  "reconciliation": reconciliation_report(store, pid), "twin_state_view": twin_state_view(store, pid, ref),
                  "posterior_convergence": posterior_convergence(store, pid, ref), "hit_rate_trend": hit_rate_trend(store, pid)}
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "data" / "interim" / "audit_local"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"twin_replay_{safe}_participant{args.participant_index}.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    summary = {"_privacy": "counts only; the trajectory is in a git-ignored local file", "participant_index": args.participant_index,
               "n_eligible_participants": len(ids), "n_events_replayed": int(len(events)), "n_forecasts": sum(s["action"].startswith("forecast") for s in log),
               "n_reconciliations": sum(s["action"].startswith("reconcile") for s in log), "final_twin_version": store.current_twin(pid).version,
               "n_versions_stored": len(store.twin_history(pid)), "own_events_excluded_from_prior": store.current_twin(pid).profile["population_prior"]["own_events_excluded_from_prior"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
