"""READ-ONLY channel-reconciliation audit: why do Libre GL and Dexcom GL give different 180 mg/dL labels?

This compares the two released CGM channels on the SAME meal events. It is NOT a validation of either sensor
against a clinical reference standard, and it says nothing about which channel is "right". It also does not
test interpolation (that was audited separately).

The events are built by exactly the code build_event_table.py uses (`build_event_table`, same defaults: leading /
internal gap <= 15 min, trailing gap <= 5 min, isolated meals only, keep_first on duplicate timestamps, baseline
lag = each channel's documented native interval unless --baseline-lag-minutes is given). The anchor is the
`Meal Type` row timestamp and the window is (t0, t0 + 120 min]; no meal_end is introduced. Events are matched
on participant + meal-row ordinal (event_id), and the matched anchors are checked to be the identical timestamp.

Three populations are kept apart: extraction-valid (window passed the gap checks), core-eligible (also has a
baseline, carbs, and is isolated) and activity-eligible (core-eligible with usable pre-meal activity). The
confusion matrix is reported for matched core-eligible events (primary) and for matched extraction-valid events.

IMPORTANT: baselines use each channel's own lag guard (Libre 15 min, Dexcom 5 min by default), so a baseline
difference mixes sensor difference with that lag difference. Use --baseline-lag-minutes to force one lag.

Output is aggregate-only: no participant identifiers, timestamps, meal rows, image paths or per-event records.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\compare_cgm_channels.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root
from glycotwin.data.discovery import discover_participant_files
from glycotwin.data.events import build_event_table
from glycotwin.data.meals import load_participant_data, participant_id_from_path
from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL

LIBRE, DEXCOM = "Libre GL", "Dexcom GL"
ABS_DIFF_WITHIN = (1, 5, 10, 20)
DISTANCE_BANDS = (5, 10, 20)
KEEP = ["participant_id", "event_id", "meal_time", "baseline_glucose", "peak_glucose", "label_exceeds_180",
        "window_completeness", "n_window_readings", "eligible_core", "eligible_activity", "isolated"]


# ----------------------------------------------------------------------------- pure comparison logic

def _summ(values) -> dict:
    v = np.asarray(pd.Series(values).dropna(), dtype=float)
    if v.size == 0:
        return {"n": 0}
    q = np.percentile(v, [5, 25, 50, 75, 95])
    return {"n": int(v.size), "mean": float(v.mean()), "sd": float(v.std(ddof=1)) if v.size > 1 else None,
            "min": float(v.min()), "p5": float(q[0]), "p25": float(q[1]), "median": float(q[2]), "p75": float(q[3]),
            "p95": float(q[4]), "max": float(v.max())}


def _corr(a, b) -> dict:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3 or np.ptp(a[ok]) == 0 or np.ptp(b[ok]) == 0:
        return {"n": int(ok.sum()), "pearson": None, "spearman": None}
    return {"n": int(ok.sum()), "pearson": float(stats.pearsonr(a[ok], b[ok])[0]),
            "spearman": float(stats.spearmanr(a[ok], b[ok])[0])}


def _kappa(tp, fp, fn, tn):
    n = tp + fp + fn + tn
    if n == 0:
        return None
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
    return None if pe == 1 else float((po - pe) / (1 - pe))


def compare_matched(m: pd.DataFrame, delta: float = 10.0, threshold: float = GLUCOSE_THRESHOLD_MG_DL) -> dict:
    """Aggregate comparison of Libre (`*_l`) vs Dexcom (`*_d`) on already-matched events.
    Confusion convention: rows = Libre label, columns = Dexcom label. Signed differences are Libre - Dexcom."""
    n = len(m)
    out: dict = {"n_matched_events": int(n), "n_participants": int(m["participant_id"].nunique()) if n else 0}
    if n == 0:
        return out
    ll, ld = m["label_exceeds_180_l"].astype(int).to_numpy(), m["label_exceeds_180_d"].astype(int).to_numpy()
    tp, fn = int(((ll == 1) & (ld == 1)).sum()), int(((ll == 1) & (ld == 0)).sum())
    fp, tn = int(((ll == 0) & (ld == 1)).sum()), int(((ll == 0) & (ld == 0)).sum())
    dis = ll != ld
    out["confusion_libre_rows_dexcom_columns"] = {"libre_pos_dexcom_pos": tp, "libre_pos_dexcom_neg": fn,
                                                  "libre_neg_dexcom_pos": fp, "libre_neg_dexcom_neg": tn}
    out["labels"] = {"n_agree": int((~dis).sum()), "n_disagree": int(dis.sum()), "share_disagree": float(dis.mean()),
                     "libre_positive_dexcom_negative": fn, "libre_negative_dexcom_positive": fp,
                     "libre_positive_rate": float(ll.mean()), "dexcom_positive_rate": float(ld.mean()),
                     "cohen_kappa": _kappa(tp, fp, fn, tn)}
    mx_l, mx_d = m["peak_glucose_l"].to_numpy(float), m["peak_glucose_d"].to_numpy(float)
    diff = mx_l - mx_d
    out["window_max_difference_libre_minus_dexcom_mg_dl"] = _summ(diff)
    out["window_max_abs_difference_mg_dl"] = _summ(np.abs(diff))
    out["window_max_abs_difference_within"] = {f"<={k}_mg_dl": float((np.abs(diff) <= k).mean()) for k in ABS_DIFF_WITHIN}
    out["window_max_correlation"] = _corr(mx_l, mx_d)
    out["window_max_by_channel"] = {"libre": _summ(mx_l), "dexcom": _summ(mx_d)}
    bl, bd = m["baseline_glucose_l"].to_numpy(float), m["baseline_glucose_d"].to_numpy(float)
    bdiff = bl - bd
    out["baseline_difference_libre_minus_dexcom_mg_dl"] = _summ(bdiff)
    out["baseline_abs_difference_mg_dl"] = _summ(np.abs(bdiff))
    out["baseline_correlation"] = _corr(bl, bd)
    out["baseline_missing"] = {"libre": int(np.isnan(bl).sum()), "dexcom": int(np.isnan(bd).sum()),
                               "either": int((np.isnan(bl) | np.isnan(bd)).sum())}
    # threshold proximity
    dist_l, dist_d = np.abs(mx_l - threshold), np.abs(mx_d - threshold)
    nearest = np.minimum(dist_l, dist_d)
    close_pair = np.abs(diff) <= delta
    out["threshold_proximity"] = {
        "threshold_mg_dl": threshold, "delta_mg_dl": delta,
        "events_with_either_max_within_delta_of_threshold": int((nearest <= delta).sum()),
        "disagreements_with_abs_max_difference_within_delta": int((dis & close_pair).sum()),
        "disagreements_with_abs_max_difference_beyond_delta": int((dis & ~close_pair).sum()),
        "share_of_disagreements_within_delta": float((dis & close_pair).sum() / dis.sum()) if dis.any() else None,
        "disagreements_by_distance_of_nearer_channel_max_to_threshold": {
            **{f"<{b}_mg_dl": int((dis & (nearest < b)).sum()) for b in DISTANCE_BANDS},
            f">={DISTANCE_BANDS[-1]}_mg_dl": int((dis & (nearest >= DISTANCE_BANDS[-1])).sum())},
        "straddle_definition": "one channel max < threshold and the other >= threshold (identical to a label disagreement)",
    }
    # direction of the offset among disagreements
    out["disagreement_direction_of_max_difference"] = {
        "libre_higher_max_in_disagreements": int((dis & (diff > 0)).sum()),
        "dexcom_higher_max_in_disagreements": int((dis & (diff < 0)).sum()),
        "equal_max_in_disagreements": int((dis & (diff == 0)).sum())}
    # completeness
    cl, cd = m["window_completeness_l"].to_numpy(float), m["window_completeness_d"].to_numpy(float)
    out["window_completeness"] = {"libre": _summ(cl), "dexcom": _summ(cd),
                                  "events_either_channel_below_1": int(((cl < 1) | (cd < 1)).sum()),
                                  "disagreements_where_either_channel_below_1": int((dis & ((cl < 1) | (cd < 1))).sum())}
    # concentration (counts only, no identifiers)
    per = pd.Series(dis).groupby(m["participant_id"].to_numpy()).sum()
    out["disagreement_concentration"] = {
        "participants_with_at_least_one": int((per > 0).sum()),
        "max_share_from_a_single_participant": float(per.max() / per.sum()) if per.sum() else None,
        "participant_disagreement_counts_distribution": _summ(per.to_numpy())}
    return out


def match_channels(tab_l: pd.DataFrame, tab_d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Inner-join the two channels' event tables on participant + event_id; the anchors must be identical."""
    l, d = tab_l[KEEP].copy(), tab_d[KEEP].copy()
    m = l.merge(d, on=["participant_id", "event_id"], how="inner", suffixes=("_l", "_d"))
    mismatch = int((m["meal_time_l"] != m["meal_time_d"]).sum()) if len(m) else 0
    m = m[m["meal_time_l"] == m["meal_time_d"]].copy() if len(m) else m
    return m, {"anchor_timestamp_mismatches_dropped": mismatch}


def build_report(tabs_l, tabs_d, delta: float = 10.0) -> dict:
    """tabs_*: participant -> EventTable for each channel (built from the same files and settings)."""
    ids = sorted(set(tabs_l) & set(tabs_d))
    def stack(tabs):
        parts = [tabs[p].table for p in ids if len(tabs[p].table)]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame({c: pd.Series(dtype="object") for c in KEEP})
    rows_l, rows_d = stack(tabs_l), stack(tabs_d)
    universe_l = {(p, e) for p in ids for e in list(tabs_l[p].table.get("event_id", [])) + [x["event_id"] for x in tabs_l[p].exclusions]}
    universe_d = {(p, e) for p in ids for e in list(tabs_d[p].table.get("event_id", [])) + [x["event_id"] for x in tabs_d[p].exclusions]}
    valid_l = {(r.participant_id, r.event_id) for r in rows_l.itertuples()}
    valid_d = {(r.participant_id, r.event_id) for r in rows_d.itertuples()}
    universe = universe_l | universe_d

    def counts(rows):
        core = rows[rows["eligible_core"].astype(bool)] if len(rows) else rows
        return {"extraction_valid": int(len(rows)), "core_eligible": int(len(core)),
                "activity_eligible": int(rows["eligible_activity"].astype(bool).sum()) if len(rows) else 0,
                "core_eligible_positive": int((core["label_exceeds_180"] == 1).sum()),
                "core_eligible_negative": int((core["label_exceeds_180"] == 0).sum())}

    excl_l = Counter(x["reason"] for p in ids for x in tabs_l[p].exclusions)
    excl_d = Counter(x["reason"] for p in ids for x in tabs_d[p].exclusions)
    matched, integrity = match_channels(rows_l, rows_d)
    core = matched[matched["eligible_core_l"].astype(bool) & matched["eligible_core_d"].astype(bool)] if len(matched) else matched
    act = matched[matched["eligible_activity_l"].astype(bool) & matched["eligible_activity_d"].astype(bool)] if len(matched) else matched
    both, only_l, only_d = valid_l & valid_d, valid_l - valid_d, valid_d - valid_l
    report = {
        "_privacy": "aggregate-only; no identifiers, timestamps, meal rows or per-event records",
        "_what_this_is": "a Libre-vs-Dexcom channel reconciliation on identical meal anchors; NOT a validation of either sensor "
                         "against a reference standard and NOT a test of interpolation",
        "n_participants": len(ids), "n_meal_rows": len(universe),
        "meal_row_universe_identical_in_both_channels": universe_l == universe_d,
        "per_channel_counts_same_as_build_event_table": {"libre": counts(rows_l), "dexcom": counts(rows_d)},
        "extraction_exclusion_reasons": {"libre": dict(excl_l), "dexcom": dict(excl_d)},
        "window_availability_over_all_meal_rows": {
            "valid_in_both": len(both), "valid_in_libre_only": len(only_l), "valid_in_dexcom_only": len(only_d),
            "valid_in_neither": len(universe) - len(valid_l | valid_d),
            "share_either_channel_missing_or_incomplete": float((len(universe) - len(both)) / len(universe)) if universe else None},
        "integrity": integrity,
        "populations_matched": {"extraction_valid_both": int(len(matched)), "core_eligible_both": int(len(core)),
                                "activity_eligible_both": int(len(act)),
                                "core_eligible_in_one_channel_only": int((matched["eligible_core_l"].astype(bool) ^ matched["eligible_core_d"].astype(bool)).sum()) if len(matched) else 0},
        "comparison_core_eligible_matched_PRIMARY": compare_matched(core, delta),
        "comparison_extraction_valid_matched": compare_matched(matched, delta),
        "comparison_activity_eligible_matched": compare_matched(act, delta),
        "caveats": [
            "baseline_glucose uses each channel's own lag guard by default (Libre 15 min, Dexcom 5 min), so baseline differences mix "
            "sensor difference with that lag difference",
            "the label uses the maximum AVAILABLE reading; a channel with lower window completeness can only under-report its maximum",
            "agreement or disagreement between two released channels does not show which one is closer to true glucose",
            "the released grid may be interpolated (see the separate CGM audits); nothing here tests that",
        ],
    }
    return report


# ----------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--max-gap-minutes", type=float, default=15, help="Same default as build_event_table.py (rule R6 is open).")
    ap.add_argument("--baseline-lag-minutes", type=float, default=None,
                    help="Same default as build_event_table.py: each channel's documented native interval. Set to force one lag for both.")
    ap.add_argument("--allow-overlap", action="store_true", help="Keep meals whose windows overlap another meal as eligible.")
    ap.add_argument("--on-duplicates", choices=["raise", "keep_first"], default="keep_first")
    ap.add_argument("--delta", type=float, default=10.0, help="mg/dL band for 'close to the threshold' (default 10).")
    ap.add_argument("--report-out", default=None, help="Local JSON copy (default data/interim/audit_local/channel_comparison.json).")
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

    tabs = {LIBRE: {}, DEXCOM: {}}
    errors = Counter()
    for p in files:
        pid = participant_id_from_path(p)
        try:
            df = load_participant_data(p)
            for ch in (LIBRE, DEXCOM):
                tabs[ch][pid] = build_event_table(df, pid, cgm_col=ch, max_cgm_gap_minutes=args.max_gap_minutes,
                                                  baseline_lag_minutes=args.baseline_lag_minutes,
                                                  require_isolated=not args.allow_overlap,
                                                  on_duplicate_timestamps=args.on_duplicates)
        except Exception as exc:  # noqa: BLE001 - never echo paths or messages
            errors[type(exc).__name__] += 1
            tabs[LIBRE].pop(pid, None); tabs[DEXCOM].pop(pid, None)
    if not tabs[LIBRE]:
        print("error: no participant file could be processed.", file=sys.stderr)
        return 2
    rep = build_report(tabs[LIBRE], tabs[DEXCOM], delta=args.delta)
    rep["settings"] = {"max_gap_minutes": args.max_gap_minutes, "baseline_lag_minutes": args.baseline_lag_minutes,
                       "require_isolated": not args.allow_overlap, "on_duplicates": args.on_duplicates, "delta_mg_dl": args.delta,
                       "anchor": "Meal Type row timestamp", "window": "(t0, t0 + 120 min]", "target": "max available glucose >= 180"}
    rep["read_errors_by_exception_type"] = dict(errors)
    out = Path(args.report_out) if args.report_out else REPO_ROOT / "data" / "interim" / "audit_local" / "channel_comparison.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rep, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
