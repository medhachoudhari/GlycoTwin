"""Read-only, AGGREGATE-ONLY meal-event semantics audit for CGMacros-style participant CSVs.

Purpose: gather the empirical evidence needed to decide what a non-null `Meal Type` row
means (meal start? end? logging time?), how reliable macro/`Amount Consumed` values are, and
whether a post-meal glucose outcome can be defined without leakage. It describes; it does
not decide, model, interpolate, or modify anything.

Privacy: opens CSVs read-only; prints/writes ONLY aggregates (counts, quantiles, medians).
It never emits participant identifiers, file names, row values, timestamps, or image paths.
The only strings it can emit are `Meal Type` labels (capped in length and number) and
timestamp *format shapes* (digits replaced by 'd'). Read errors are reported by exception
type only. Output goes to stdout and to a git-ignored local file.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\audit_meal_events.py
Paste the printed JSON back; it contains no row-level data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root

GLUCOSE_COLS = ["Libre GL", "Dexcom GL"]
MACRO_COLS = ["Calories", "Carbs", "Protein", "Fat", "Fiber"]
ACTIVITY_COLS = ["HR", "METs", "Calories (Activity)"]
OFFSETS_MIN = [-60, -30, -15, 0, 15, 30, 45, 60, 90, 120, 150, 180]
WINDOW = pd.Timedelta(hours=2)
THRESHOLD = 180.0  # descriptive event counts only; NOT a decision to use this target
GAP_EDGES_MIN = [0, 1, 5, 15, 30, 60, 120, 240]
MAX_LABELS = 40


def _q(values, qs=(0, 0.05, 0.25, 0.5, 0.75, 0.95, 1)):
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    return {f"q{int(q * 100):02d}": round(float(np.quantile(a, q)), 3) for q in qs} | {"n": int(a.size)}


def _share(x, pred):
    """Share of FINITE values satisfying pred (missing values are excluded, not counted as False)."""
    x = x[np.isfinite(x)]
    return round(float(pred(x).mean()), 3) if x.size else None


def _shape(s: str) -> str:
    return re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "d", s))[:40]


def _top(counter: Counter, k: int):
    total = sum(counter.values())
    return {str(key)[:30]: int(v) for key, v in counter.most_common(k)}, int(total)


def find_participant_csvs(root: Path) -> list[Path]:
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".csv"):
                p = Path(dirpath) / f
                try:
                    cols = set(pd.read_csv(p, nrows=0).columns)
                except Exception:  # noqa: BLE001
                    continue
                if {"Timestamp", "Meal Type"} <= cols:
                    found.append(p)
    return sorted(found)


def new_acc() -> dict:
    return defaultdict(list) | {
        "ts_shapes": Counter(), "steps": Counter(), "label_raw": Counter(), "label_norm": Counter(),
        "meals_per_day": Counter(), "gap_bucket": Counter(), "errors": Counter(),
        "amount_nonnumeric": Counter(), "n": Counter(),
        "hours_by_label": defaultdict(list), "probe": defaultdict(list),
    }


def process_file(path: Path, acc: dict) -> None:
    df = pd.read_csv(path, low_memory=False)
    n = acc["n"]
    n["files"] += 1
    n["rows"] += len(df)
    acc["rows_per_file"].append(len(df))

    # ---- timestamps -------------------------------------------------------------
    raw_ts = df["Timestamp"]
    if raw_ts.notna().any():
        acc["ts_shapes"][_shape(str(raw_ts.dropna().iloc[0]))] += 1
    ts = pd.to_datetime(raw_ts, errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        n["files_tz_aware"] += 1
        ts = ts.dt.tz_localize(None)
    keep = ts.notna().to_numpy()
    n["timestamp_unparseable_rows"] += int((~keep).sum())
    df, ts = df.loc[keep].reset_index(drop=True), ts[keep].reset_index(drop=True)
    if len(df) < 2:
        n["files_too_short"] += 1
        return
    if not ts.is_monotonic_increasing:
        n["files_not_time_sorted"] += 1
        order = np.argsort(ts.to_numpy(), kind="stable")
        df, ts = df.iloc[order].reset_index(drop=True), ts.iloc[order].reset_index(drop=True)
    n["duplicate_timestamp_rows"] += int(ts.duplicated().sum())
    steps = ts.diff().dt.total_seconds().dropna()
    for v, c in zip(*np.unique(steps.round(0), return_counts=True)):
        acc["steps"][float(v)] += int(c)
    acc["median_step_s"].append(float(steps.median()))
    acc["span_days"].append((ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400)

    # ---- glucose columns: null patterns and sampling/interpolation fingerprint ---------
    g = {c: pd.to_numeric(df[c], errors="coerce") for c in GLUCOSE_COLS if c in df.columns}
    for c, s in g.items():
        n[f"{c}|null_rows"] += int(s.isna().sum())
        n[f"{c}|nonnumeric_cells"] += int(df[c].notna().sum() - s.notna().sum())
        v = s.dropna().to_numpy()
        if v.size > 1:
            runs = np.diff(np.r_[np.flatnonzero(np.r_[True, v[1:] != v[:-1]]), v.size])
            acc[f"{c}|run_lengths"].append(runs)
            n[f"{c}|consecutive_equal_pairs"] += int((v[1:] == v[:-1]).sum())
            n[f"{c}|consecutive_pairs"] += int(v.size - 1)
        else:
            n[f"{c}|files_all_null"] += 1
    if len(g) == 2:
        n["both_glucose_null_rows"] += int((g["Libre GL"].isna() & g["Dexcom GL"].isna()).sum())

    # ---- meal rows -----------------------------------------------------------------------
    mt = df["Meal Type"]
    is_meal = mt.notna().to_numpy()
    n["meal_rows"] += int(is_meal.sum())
    if not is_meal.any():
        n["files_with_zero_meal_rows"] += 1
        return
    lab = mt[is_meal].astype(str)
    acc["label_raw"].update(lab.str.slice(0, 30))
    acc["label_norm"].update(lab.str.strip().str.lower().str.slice(0, 30))
    n["label_blank_after_strip"] += int((lab.str.strip() == "").sum())
    acc["meals_per_file"].append(int(is_meal.sum()))

    present = [c for c in MACRO_COLS if c in df.columns]
    macro_any = df[present].notna().any(axis=1).to_numpy() if present else np.zeros(len(df), bool)
    n["meal_and_macro"] += int((is_meal & macro_any).sum())
    n["meal_without_any_macro"] += int((is_meal & ~macro_any).sum())
    n["macro_without_meal_label"] += int((~is_meal & macro_any).sum())
    for c in present:
        x = pd.to_numeric(df.loc[is_meal, c], errors="coerce")
        n[f"{c}|meal_rows_null"] += int(x.isna().sum())
        n[f"{c}|meal_rows_zero"] += int((x == 0).sum())
        n[f"{c}|meal_rows_negative"] += int((x < 0).sum())
        acc[f"{c}|values"].append(x.dropna().to_numpy())
    if {"Calories", "Carbs", "Protein", "Fat"} <= set(present):
        m = df.loc[is_meal]
        atw = 4 * pd.to_numeric(m["Carbs"], errors="coerce") + 4 * pd.to_numeric(m["Protein"], errors="coerce") \
            + 9 * pd.to_numeric(m["Fat"], errors="coerce")
        cal = pd.to_numeric(m["Calories"], errors="coerce")
        acc["calorie_to_atwater_ratio"].append((cal / atw.where(atw > 0)).to_numpy())

    if "Amount Consumed" in df.columns:
        raw = df["Amount Consumed"]
        num = pd.to_numeric(raw, errors="coerce")
        n["amount_nonnull_on_meal_rows"] += int(raw[is_meal].notna().sum())
        n["amount_nonnull_on_nonmeal_rows"] += int(raw[~is_meal].notna().sum())
        bad = raw[raw.notna() & num.isna()].astype(str)
        acc["amount_nonnumeric"].update(bad.str.slice(0, 20))
        acc["amount_values"].append(num[is_meal].dropna().to_numpy())
    if "Image path" in df.columns:
        has_img = df["Image path"].notna().to_numpy()
        n["image_on_meal_rows"] += int((has_img & is_meal).sum())
        n["image_on_nonmeal_rows"] += int((has_img & ~is_meal).sum())

    # ---- meal timing: duplicates, spacing, per-day counts, time of day ------------------------
    mts = ts[is_meal]
    sorted_mt = np.sort(mts.to_numpy())
    d = np.diff(sorted_mt) / np.timedelta64(1, "m")
    n["meal_pairs"] += int(d.size)
    n["meal_exact_duplicate_timestamps"] += int((d == 0).sum())
    n["meal_pairs_closer_than_120min"] += int((d < 120).sum())
    for b in np.searchsorted(GAP_EDGES_MIN, d, side="right") - 1:
        acc["gap_bucket"][int(b)] += 1
    for day_n in mts.dt.normalize().value_counts():
        acc["meals_per_day"][int(day_n)] += 1
    hours = (mts.dt.hour + mts.dt.minute / 60).to_numpy()
    for key, h in zip(lab.str.strip().str.lower().str.slice(0, 30), hours):
        acc["hours_by_label"][key].append(float(h))

    # ---- glucose around the meal row (semantic probe) + descriptive outcome feasibility ------
    meal_times = pd.DatetimeIndex(pd.unique(mts.to_numpy()))
    for c, s in g.items():
        sv = pd.Series(s.to_numpy(), index=ts).dropna()
        sv = sv[~sv.index.duplicated()].sort_index()
        if len(sv) < 3:
            continue
        step = max(float(sv.index.to_series().diff().dt.total_seconds().median()), 60.0)
        tol = pd.Timedelta(seconds=step)
        offs = np.array(OFFSETS_MIN, dtype="timedelta64[m]")
        targets = pd.DatetimeIndex((meal_times.values[:, None] + offs[None, :]).ravel())
        idx = sv.index.get_indexer(targets, method="nearest", tolerance=tol)
        vals = np.where(idx >= 0, sv.to_numpy()[np.clip(idx, 0, None)], np.nan).reshape(len(meal_times), -1)
        base = vals[:, OFFSETS_MIN.index(0)]
        acc["probe"][c].append(vals - base[:, None])

        lo = sv.index.searchsorted(meal_times, side="left")
        hi = sv.index.searchsorted(meal_times + WINDOW, side="right")
        expected = WINDOW.total_seconds() / step + 1
        comp = (hi - lo) / expected
        peak = np.array([sv.to_numpy()[a:b].max() if b > a else np.nan for a, b in zip(lo, hi)])
        base_ok = np.isfinite(base)
        eligible = base_ok & (comp >= 0.8) & (base < THRESHOLD)
        n[f"{c}|meals"] += len(meal_times)
        n[f"{c}|meals_with_baseline"] += int(base_ok.sum())
        n[f"{c}|meals_window_complete_80pct"] += int((comp >= 0.8).sum())
        n[f"{c}|meals_baseline_ge_180"] += int((base_ok & (base >= THRESHOLD)).sum())
        n[f"{c}|meals_eligible"] += int(eligible.sum())
        pos = int((eligible & (peak > THRESHOLD)).sum())
        n[f"{c}|meals_eligible_peak_gt_180"] += pos
        acc[f"{c}|eligible_per_file"].append(int(eligible.sum()))
        acc[f"{c}|positives_per_file"].append(pos)

    # ---- pre-meal activity/HR coverage in [t-120min, t) ------------------------------------------
    ts_np = ts.to_numpy()
    mt_np = meal_times.values
    lo = np.searchsorted(ts_np, mt_np - np.timedelta64(120, "m"), side="left")
    hi = np.searchsorted(ts_np, mt_np, side="left")
    for c in ACTIVITY_COLS:
        if c not in df.columns:
            continue
        nn = df[c].notna().to_numpy()
        n[f"{c}|null_rows"] += int((~nn).sum())
        if not nn.any():
            n[f"{c}|files_all_null"] += 1
        cum = np.r_[0, np.cumsum(nn)]
        rows = hi - lo
        acc[f"{c}|premeal_cov"].append(np.where(rows > 0, (cum[hi] - cum[lo]) / np.maximum(rows, 1), np.nan))


def summarize(acc: dict) -> dict:
    n = acc["n"]
    cat = lambda k: np.concatenate(acc[k]) if acc[k] else np.array([])  # noqa: E731
    out: dict = {"_privacy": "aggregate-only: no identifiers, file names, rows, timestamps or image paths"}

    steps_top, steps_total = _top(acc["steps"], 8)
    out["files_and_rows"] = {
        "files_analysed": n["files"], "rows": n["rows"], "read_errors_by_exception_type": dict(acc["errors"]),
        "rows_per_file": _q(acc["rows_per_file"]), "span_days_per_file": _q(acc["span_days"]),
        "files_with_zero_meal_rows": n["files_with_zero_meal_rows"], "meal_rows": n["meal_rows"],
        "meals_per_file": _q(acc["meals_per_file"]),
    }
    out["timestamps"] = {
        "format_shapes_digits_as_d": dict(acc["ts_shapes"]), "unparseable_rows": n["timestamp_unparseable_rows"],
        "files_tz_aware": n["files_tz_aware"], "files_not_time_sorted": n["files_not_time_sorted"],
        "duplicate_timestamp_rows": n["duplicate_timestamp_rows"],
        "row_step_seconds_top_values_count": steps_top, "row_step_total_pairs": steps_total,
        "median_row_step_seconds_per_file": _q(acc["median_step_s"]),
    }
    out["glucose_columns"] = {}
    for c in GLUCOSE_COLS:
        runs = np.concatenate(acc[f"{c}|run_lengths"]) if acc[f"{c}|run_lengths"] else np.array([])
        pairs = n[f"{c}|consecutive_pairs"]
        out["glucose_columns"][c] = {
            "null_rows": n[f"{c}|null_rows"], "nonnumeric_cells": n[f"{c}|nonnumeric_cells"],
            "files_all_null": n[f"{c}|files_all_null"],
            "share_consecutive_equal_values": round(n[f"{c}|consecutive_equal_pairs"] / pairs, 4) if pairs else None,
            "constant_run_length_rows": _q(runs),
        }
    out["glucose_columns"]["rows_with_both_null"] = n["both_glucose_null_rows"]

    labels, _ = _top(acc["label_raw"], MAX_LABELS)
    norm, _ = _top(acc["label_norm"], MAX_LABELS)
    out["meal_type_labels"] = {
        "distinct_raw": len(acc["label_raw"]), "distinct_after_strip_lower": len(acc["label_norm"]),
        "raw_counts_top": labels, "normalised_counts_top": norm, "blank_after_strip": n["label_blank_after_strip"],
    }
    out["macros"] = {
        "meal_rows_with_any_macro": n["meal_and_macro"], "meal_rows_without_any_macro": n["meal_without_any_macro"],
        "macro_rows_without_meal_label": n["macro_without_meal_label"],
        "per_column": {c: {"meal_rows_null": n[f"{c}|meal_rows_null"], "meal_rows_zero": n[f"{c}|meal_rows_zero"],
                           "meal_rows_negative": n[f"{c}|meal_rows_negative"], "values": _q(cat(f"{c}|values"))}
                       for c in MACRO_COLS},
        "calories_over_atwater_4c_4p_9f_ratio": _q(cat("calorie_to_atwater_ratio")),
    }
    amt_top, _ = _top(acc["amount_nonnumeric"], 15)
    amt = cat("amount_values")
    out["amount_consumed"] = {
        "nonnull_on_meal_rows": n["amount_nonnull_on_meal_rows"], "nonnull_on_nonmeal_rows": n["amount_nonnull_on_nonmeal_rows"],
        "numeric_values": _q(amt), "share_equal_to_max": round(float((amt == amt.max()).mean()), 4) if amt.size else None,
        "nonnumeric_distinct_values_top": amt_top,
    }
    out["image_path_presence_counts_only"] = {"on_meal_rows": n["image_on_meal_rows"], "on_nonmeal_rows": n["image_on_nonmeal_rows"]}

    gb = [f"[{a},{b})" for a, b in zip(GAP_EDGES_MIN, GAP_EDGES_MIN[1:])] + [f">={GAP_EDGES_MIN[-1]}"]
    out["meal_timing"] = {
        "consecutive_meal_pairs": n["meal_pairs"], "exact_duplicate_timestamps": n["meal_exact_duplicate_timestamps"],
        "pairs_closer_than_120min": n["meal_pairs_closer_than_120min"],
        "gap_minutes_bucket_counts": {gb[i]: int(acc["gap_bucket"].get(i, 0)) for i in range(len(gb))},
        "participant_days_by_meals_that_day": {str(k): v for k, v in sorted(acc["meals_per_day"].items())},
        "hour_of_day_quantiles_by_label": {k: _q(v, (0.05, 0.25, 0.5, 0.75, 0.95)) for k, v in sorted(acc["hours_by_label"].items())
                                           if len(v) >= 20},
    }
    out["glucose_change_vs_meal_row_median_mg_dl"] = {}
    for c, parts in acc["probe"].items():
        m = np.vstack(parts)
        i0, im30, ip30 = OFFSETS_MIN.index(0), OFFSETS_MIN.index(-30), OFFSETS_MIN.index(30)
        # the -30 and +30 deltas are relative to offset 0, so sign = direction of travel into/out of the row
        out["glucose_change_vs_meal_row_median_mg_dl"][c] = {
            "median_delta_by_offset_min": {str(o): (None if not np.isfinite(m[:, j]).any() else round(float(np.nanmedian(m[:, j])), 2))
                                           for j, o in enumerate(OFFSETS_MIN)},
            "n_by_offset_min": {str(o): int(np.isfinite(m[:, j]).sum()) for j, o in enumerate(OFFSETS_MIN)},
            "share_rising_in_30min_before_row": _share(m[:, im30], lambda x: x < 0),
            "share_rising_in_30min_after_row": _share(m[:, ip30], lambda x: x > 0),
        }
    out["descriptive_outcome_feasibility_NOT_a_target_decision"] = {}
    for c in GLUCOSE_COLS:
        ep, pp = acc[f"{c}|eligible_per_file"], acc[f"{c}|positives_per_file"]
        out["descriptive_outcome_feasibility_NOT_a_target_decision"][c] = {
            "meals": n[f"{c}|meals"], "with_baseline_value": n[f"{c}|meals_with_baseline"],
            "window_ge_80pct_complete": n[f"{c}|meals_window_complete_80pct"],
            "baseline_already_ge_180": n[f"{c}|meals_baseline_ge_180"],
            "eligible_(baseline<180,window_complete)": n[f"{c}|meals_eligible"],
            "eligible_with_peak_gt_180_in_2h": n[f"{c}|meals_eligible_peak_gt_180"],
            "eligible_per_participant": _q(ep), "positives_per_participant": _q(pp),
            "participants_with_ge5_positives_and_ge5_negatives": int(sum(p >= 5 and e - p >= 5 for e, p in zip(ep, pp))),
        }
    out["premeal_120min_coverage_nonnull_share"] = {
        c: {"null_rows": n[f"{c}|null_rows"], "files_all_null": n[f"{c}|files_all_null"],
            "meals_with_coverage_ge_80pct": int(np.nansum(cat(f"{c}|premeal_cov") >= 0.8)),
            "meals_total": int(cat(f"{c}|premeal_cov").size), "coverage_quantiles": _q(cat(f"{c}|premeal_cov"))}
        for c in ACTIVITY_COLS if acc[f"{c}|premeal_cov"]
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--out", default=None, help="Local JSON (default: data/interim/audit_local/meal_event_semantics.json).")
    args = ap.parse_args(argv)
    try:
        root = get_dataset_root(args.data_root)
    except DatasetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    files = find_participant_csvs(root)
    if not files:
        print("error: no CSV with both 'Timestamp' and 'Meal Type' columns was found under the dataset root.",
              file=sys.stderr)
        return 2
    acc = new_acc()
    for p in files:
        try:
            process_file(p, acc)
        except Exception as exc:  # noqa: BLE001 - never echo paths/messages
            acc["errors"][type(exc).__name__] += 1
    result = summarize(acc)

    out_path = Path(args.out) if args.out else REPO_ROOT / "data" / "interim" / "audit_local" / "meal_event_semantics.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    out_path.write_text(text, encoding="utf-8")
    print(text)
    print("\n(aggregate-only; also saved to the git-ignored local file; no data was modified)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
