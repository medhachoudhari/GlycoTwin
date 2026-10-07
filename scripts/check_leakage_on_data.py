"""Run the blueprint's leakage unit test on REAL participant files (aggregate output only).

For each participant file: pick one window-valid meal, build its features with the real pipeline,
mutate everything after the meal (and, separately, the Fitbit-type columns AT the meal row), rebuild, and require the features to be identical. The blueprint
requires this to pass for at least one meal per participant before any model training.

Output has counts and column names only. Exit code 0 only if every checked participant passes.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\check_leakage_on_data.py [--channel "Libre GL"]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from glycotwin.config import DatasetNotFoundError, get_dataset_root
from glycotwin.data.discovery import discover_participant_files
from glycotwin.data.leakage_check import check_feature_leakage
from glycotwin.data.meals import load_participant_data, participant_id_from_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--channel", default="Dexcom GL", choices=["Dexcom GL", "Libre GL"])
    ap.add_argument("--max-gap-minutes", type=float, default=15)
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

    tally, failing, errors = Counter(), Counter(), Counter()
    for p in files:
        try:
            r = check_feature_leakage(load_participant_data(p), participant_id_from_path(p), cgm_col=args.channel,
                                      max_cgm_gap_minutes=args.max_gap_minutes, on_duplicate_timestamps="keep_first")
        except Exception as exc:  # noqa: BLE001 - never echo paths or messages
            errors[type(exc).__name__] += 1
            continue
        if not r["checked"]:
            tally["no_window_valid_event"] += 1
            continue
        tally["passed" if r["passed"] else "failed"] += 1
        failing.update(r["blueprint_mismatched_columns"] + r["lag_guard_mismatched_columns"] + r["anchor_inclusive_mismatched_columns"])
    report = {"_privacy": "aggregate-only", "channel": args.channel, "files": len(files), "result": dict(tally),
              "failing_feature_columns": dict(failing), "read_errors_by_exception_type": dict(errors),
              "all_checked_participants_pass": tally.get("failed", 0) == 0 and tally.get("passed", 0) > 0,
              "note": "passing shows the feature code does not read the future; it does not prove the released grid is free "
                      "of interpolation leakage (see rule R3/R4)."}
    print(json.dumps(report, indent=2))
    return 0 if report["all_checked_participants_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
