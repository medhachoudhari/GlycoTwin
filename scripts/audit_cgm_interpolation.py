"""Read-only, aggregate-only diagnostic: can original CGM sampling times be inferred from the
released one-minute CGMacros grid?

HYPOTHESIS UNDER TEST (H): each released glucose channel is the LINEAR interpolation of native
sensor readings taken every P minutes (documented, per the project blueprint and NOT verified
here: Dexcom P=5, Libre P=15) at a fixed offset. The script measures whether the data show the
fingerprint H predicts. It reports OBSERVED patterns and, separately, an INFERRED candidate
phase. It never claims that native timestamps were recovered: that needs independent evidence
(a native export or the device documentation).

WHY SECOND DIFFERENCES: between two native readings an interpolated series is a straight line,
so d2[t] = v[t-1] - 2 v[t] + v[t+1] is 0 there and nonzero only where the slope changes, i.e. at
native readings. If H holds, mean |d2| concentrates on one residue (minute index mod P).

ASSUMPTIONS (a failure of any of these weakens or defeats the test):
  * the released series is exactly piecewise-linear between native readings;
  * a fixed period P, with native readings landing on whole minutes (timestamp jitter or
    sub-minute times smear the signal across neighbouring residues);
  * rounding of released values (if any) is fine enough that slope changes at knots exceed it:
    otherwise knots are invisible and the verdict is "inconclusive_low_power", not "no";
  * a stable phase (device restarts, clock changes or gap handling can shift it).

Privacy: opens CSVs read-only and reads ONLY the Timestamp and glucose columns. Prints/writes
aggregates and anonymous participant labels (P1..P5 in random-draw order). No file names,
timestamps, rows or identifiers. Phases are offsets from each file's own first minute. Read
errors are reported by exception type only.

Usage (PowerShell):
    $env:GLYCOTWIN_DATA_ROOT = "C:\\path\\to\\CGMacros"
    python scripts\\audit_cgm_interpolation.py                 # pilot: 5 random participants
    python scripts\\audit_cgm_interpolation.py --n-participants 45
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from glycotwin.config import REPO_ROOT, DatasetNotFoundError, get_dataset_root

DOCUMENTED_PERIODS = {"Dexcom GL": 5, "Libre GL": 15}  # blueprint-reported, configurable by flag
SCAN_MAX_PERIOD = 30
ALPHA = 0.01                # permutation-test significance level
MIN_CONCENTRATION = 0.5     # top residue must hold >= half of the mean-|d2| mass (flat is 1/P)
MIN_PHASE_AGREEMENT = 0.8   # share of day-blocks whose top residue equals the dominant residue
MIN_DETECTABLE_KNOTS = 0.3  # detected slope changes per expected native interval, else low power
CLIP_QUANTILE = 0.99        # |d2| clipped here so a few spikes cannot fake concentration
MIN_POINTS_PER_PERIOD = 20  # need >= this many d2 points per residue-cycle to evaluate at all
BLOCK_MINUTES = 1440
# A permutation test with n shuffles cannot return a p-value below 1/(n+1); require enough
# shuffles that p <= ALPHA is attainable at all, otherwise a strong signal could never register.
MIN_PERMUTATIONS = int(round(1 / ALPHA)) - 1


# ----------------------------------------------------------------------------- grid / QC

def to_minute_series(timestamps, values):
    """Return (v, qc): v[m] = value at whole minute m since the earliest timestamp, NaN where
    there is no row or no value. v is None when the grid cannot be trusted (reason in qc)."""
    qc = {"rows": int(len(timestamps))}
    ts = pd.to_datetime(timestamps, errors="coerce")
    if not pd.api.types.is_datetime64_any_dtype(ts):
        return None, {**qc, "usable": False, "reason": "timestamp_dtype_not_datetime"}
    val = pd.to_numeric(values, errors="coerce")
    ok = ts.notna().to_numpy()
    qc["timestamp_unparseable_rows"] = int((~ok).sum())
    ts, val = ts[ok], val[ok]
    if len(ts) < 3:
        return None, {**qc, "usable": False, "reason": "too_few_rows"}
    minutes = ((ts - ts.min()).dt.total_seconds() / 60.0).to_numpy()
    on_grid = np.abs(minutes - np.round(minutes)) < 1e-6
    qc["share_on_whole_minute_grid"] = round(float(on_grid.mean()), 6)
    if on_grid.mean() < 0.99:
        return None, {**qc, "usable": False, "reason": "not_one_minute_aligned"}
    m = np.round(minutes).astype(np.int64)
    qc["rows_out_of_order"] = int((np.diff(m) < 0).sum())
    qc["duplicate_minute_rows"] = int(pd.Series(m).duplicated().sum())
    order = np.argsort(m, kind="stable")
    m, vv = m[order], val.to_numpy(dtype=float)[order]
    first = np.r_[True, m[1:] != m[:-1]]          # keep the first row of any duplicated minute
    m, vv = m[first], vv[first]
    v = np.full(int(m[-1]) + 1, np.nan)
    v[m] = vv
    qc.update(usable=True, span_minutes=int(len(v)), minutes_without_row=int(len(v) - len(m)))
    return v, qc


def estimate_resolution(v):
    """Finest rounding step the values sit on (1, 0.5, 0.1, 0.01, 0.001), or 0.0 if continuous."""
    x = v[np.isfinite(v)]
    if x.size == 0:
        return None
    for q in (1.0, 0.5, 0.1, 0.01, 0.001):
        r = x / q
        if np.mean(np.abs(r - np.round(r)) < 1e-6) >= 0.999:
            return q
    return 0.0


def zero_tolerance(q):
    """|d2| at or below this is 'zero'. Rounding each of three values by <= q/2 moves d2 by <= 2q."""
    return 2.0 * q if q else 1e-6


# ----------------------------------------------------------------------------- differences

def second_differences(v):
    d2 = np.full(v.shape, np.nan)
    d2[1:-1] = v[:-2] - 2.0 * v[1:-1] + v[2:]
    return d2


def first_differences_abs(v):
    d1 = np.full(v.shape, np.nan)
    d1[1:] = np.abs(v[1:] - v[:-1])
    return d1


def _clip(a):
    fin = a[np.isfinite(a)]
    if fin.size == 0:
        return a
    cap = np.quantile(fin, CLIP_QUANTILE)
    return np.where(np.isfinite(a), np.minimum(a, cap), np.nan) if cap > 0 else a


# ----------------------------------------------------------------------------- concentration

def residue_means(absval, period):
    idx = np.flatnonzero(np.isfinite(absval))
    res = idx % period
    counts = np.bincount(res, minlength=period)
    sums = np.bincount(res, weights=absval[idx], minlength=period)
    return sums / np.maximum(counts, 1), counts, idx, res


def concentration(means):
    """Share of mean-|x| mass on the top residue (flat = 1/P) and which residue it is."""
    total = float(means.sum())
    if total <= 0:
        return float("nan"), 0
    return float(means.max() / total), int(means.argmax())


def pair_concentration(means):
    """Mass on the best pair of ADJACENT residues (native times that fall between whole minutes)."""
    total = float(means.sum())
    if total <= 0:
        return float("nan")
    return float((means + np.roll(means, -1)).max() / total)


def concentration_test(absval, period, n_perm, rng):
    """Observed top-residue concentration, permutation p-value and null 95th percentile.
    Null: |x| values shuffled over the same positions, which keeps their distribution and the
    positions' residues but destroys any periodic structure."""
    n_perm = max(int(n_perm), MIN_PERMUTATIONS)
    absval = _clip(absval)
    means, counts, idx, res = residue_means(absval, period)
    obs, residue = concentration(means)
    if not np.isfinite(obs):
        return {"concentration": None, "residue": None, "p_value": None, "null95": None,
                "pair_concentration": None, "n_points": int(idx.size)}
    vals = absval[idx]
    nulls = np.empty(n_perm)
    for k in range(n_perm):
        s = np.bincount(res, weights=rng.permutation(vals), minlength=period) / np.maximum(counts, 1)
        nulls[k] = s.max() / s.sum() if s.sum() > 0 else 0.0
    return {"concentration": obs, "residue": residue, "p_value": float((1 + np.sum(nulls >= obs)) / (n_perm + 1)),
            "null95": float(np.quantile(nulls, 0.95)), "pair_concentration": pair_concentration(means),
            "n_points": int(idx.size)}


def scan_periods(absd2, rng, n_perm, p_max=SCAN_MAX_PERIOD):
    return {P: concentration_test(absd2, P, n_perm, rng) for P in range(2, p_max + 1)}


def estimate_fundamental_period(scan, rel=0.8):
    """Largest period that is significant and holds >= rel x the best concentration. A true
    period P0 also concentrates at its divisors (all knots share one residue mod a divisor), so
    the LARGEST such period is the fundamental; multiples of P0 only reach 1/k of the mass."""
    sig = {P: s for P, s in scan.items() if s["concentration"] is not None and s["p_value"] <= ALPHA}
    if not sig:
        return None
    cmax = max(s["concentration"] for s in sig.values())
    return max(P for P, s in sig.items() if s["concentration"] >= rel * cmax)


# ----------------------------------------------------------------------------- phase / knots

def circ_dist(a, b, period):
    d = np.abs(np.asarray(a) - np.asarray(b)) % period
    return np.minimum(d, period - d)


def block_phases(absd2, period, block_minutes=BLOCK_MINUTES, min_per_residue=5):
    """Top residue of |d2| within each block (blocks too sparse to say are skipped)."""
    phases = []
    for start in range(0, len(absd2), block_minutes):
        seg = absd2[start:start + block_minutes]
        idx = np.flatnonzero(np.isfinite(seg)) + start
        if idx.size < period * min_per_residue:
            continue
        res = idx % period
        means = np.bincount(res, weights=absd2[idx], minlength=period) / np.maximum(np.bincount(res, minlength=period), 1)
        phases.append(int(means.argmax()))
    return phases


def phase_stability(phases, dominant, period):
    if not phases:
        return {"n_blocks": 0}
    p = np.array(phases)
    shifts = circ_dist(p[1:], p[:-1], period) if len(p) > 1 else np.array([])
    return {"n_blocks": int(len(p)),
            "agreement_exact": float(np.mean(p == dominant)),
            "agreement_within_1_minute": float(np.mean(circ_dist(p, dominant, period) <= 1)),
            "chance_agreement_exact": round(1.0 / period, 4),
            "phase_shift_events": int(np.sum(shifts > 0)),
            "shift_sizes_minutes": {int(k): int(c) for k, c in sorted(Counter(shifts[shifts > 0].tolist()).items())}}


def knot_stats(v, d2, period, tol, dominant):
    idx = np.flatnonzero(np.isfinite(d2) & (np.abs(d2) > tol))
    valid_minutes = int(np.isfinite(v).sum())
    expected = valid_minutes / period if period else 0
    out = {"n_detected_slope_changes": int(idx.size),
           "detected_per_expected_native_interval": round(idx.size / expected, 4) if expected else None}
    if idx.size:
        out["share_on_dominant_residue_exact"] = round(float(np.mean(idx % period == dominant)), 4)
        out["share_within_1_minute_of_dominant"] = round(float(np.mean(circ_dist(idx % period, dominant, period) <= 1)), 4)
    if idx.size > 1:
        nan_before = np.r_[0, np.cumsum(~np.isfinite(v))]
        sp = np.diff(idx)[(nan_before[idx[1:]] - nan_before[idx[:-1] + 1]) == 0]   # only fully observed stretches
        if sp.size:
            out["spacing"] = {"n": int(sp.size), "share_equal_to_period": round(float(np.mean(sp == period)), 4),
                              "share_other_multiple_of_period": round(float(np.mean((sp % period == 0) & (sp != period))), 4),
                              "share_not_a_multiple": round(float(np.mean(sp % period != 0)), 4),
                              "most_common_minutes": {int(k): int(c) for k, c in Counter(sp.tolist()).most_common(5)}}
    return out


def straight_runs(v, d2, tol, period):
    """Runs where d2 ~ 0 across more than two native intervals. Sloped ones are CANDIDATE
    interpolation-filled gaps (or very smooth glucose); flat ones are plateaus, counted separately."""
    zero = np.isfinite(d2) & (np.abs(d2) <= tol)
    pad = np.r_[False, zero, False]
    edges = np.flatnonzero(pad[1:] != pad[:-1])
    starts, ends = edges[::2], edges[1::2]                     # zero-d2 runs are [start, end)
    long_points = 2 * period + 1
    flat_runs, sloped_runs = [], []
    for s, e in zip(starts, ends):
        i0, i1 = s - 1, e                                      # run's end points (inclusive)
        n_points = i1 - i0 + 1
        if n_points <= long_points:
            continue
        (flat_runs if abs(v[i1] - v[i0]) <= tol else sloped_runs).append(n_points)
    valid = max(int(np.isfinite(v).sum()), 1)
    return {"long_run_threshold_points": long_points,
            "n_long_flat_runs": len(flat_runs), "n_long_sloped_runs": len(sloped_runs),
            "share_of_valid_minutes_in_long_sloped_runs": round(sum(sloped_runs) / valid, 5),
            "longest_sloped_run_points": max(sloped_runs) if sloped_runs else 0,
            "longest_flat_run_points": max(flat_runs) if flat_runs else 0}


def nan_gap_stats(v, period):
    fin = np.flatnonzero(np.isfinite(v))
    if fin.size == 0:
        return {"valid_minutes": 0}
    inside = ~np.isfinite(v[fin[0]:fin[-1] + 1])
    pad = np.r_[False, inside, False]
    edges = np.flatnonzero(pad[1:] != pad[:-1])
    lengths = edges[1::2] - edges[::2]
    buckets = {"1": int(np.sum(lengths == 1)), f"2-{period}": int(np.sum((lengths >= 2) & (lengths <= period))),
               f"{period + 1}-30": int(np.sum((lengths > period) & (lengths <= 30))), ">30": int(np.sum(lengths > 30))}
    return {"valid_minutes": int(fin.size), "share_missing_inside_span": round(float(inside.mean()), 5),
            "n_missing_gaps": int(lengths.size), "gap_length_buckets_minutes": buckets,
            "longest_gap_minutes": int(lengths.max()) if lengths.size else 0}


# ----------------------------------------------------------------------------- one channel

def classify_channel(info):
    """Conservative verdict from the measured statistics (observed pattern, not proof)."""
    if info.get("status") != "evaluated":
        return "insufficient_data"
    t, c1 = info["documented_period_test"], info["first_difference_test"]
    low_power = (info["knots"]["detected_per_expected_native_interval"] or 0) < MIN_DETECTABLE_KNOTS
    if c1["concentration"] is not None and c1["p_value"] <= ALPHA and c1["concentration"] >= MIN_CONCENTRATION:
        return "periodic_but_step_hold_like_not_linear"
    if t["concentration"] is None or t["p_value"] > ALPHA or t["concentration"] < MIN_CONCENTRATION:
        return "inconclusive_low_power" if low_power else "not_supported"
    stab = info["phase_stability"]
    if stab.get("n_blocks", 0) < 2 or stab.get("agreement_exact", 0) < MIN_PHASE_AGREEMENT:
        return "periodic_but_phase_unstable"
    return "consistent_with_linear_interpolation_on_fixed_grid"


def analyze_channel(v, period, n_perm, scan_perms, rng, block_minutes=BLOCK_MINUTES):
    n_valid = int(np.isfinite(v).sum())
    base = {"documented_period_minutes": period, "nan_gaps": nan_gap_stats(v, period)}
    d2 = second_differences(v)
    if n_valid < MIN_POINTS_PER_PERIOD * period or np.isfinite(d2).sum() < MIN_POINTS_PER_PERIOD * period:
        return {**base, "status": "insufficient_data", "verdict": "insufficient_data"}
    q = estimate_resolution(v)
    tol = zero_tolerance(q)
    absd2 = np.abs(d2)
    test = concentration_test(absd2, period, n_perm, rng)
    dominant = test["residue"] if test["residue"] is not None else 0
    scan = scan_periods(absd2, rng, scan_perms)
    d1_test = concentration_test(first_differences_abs(v), period, n_perm, rng)
    fin_d2 = d2[np.isfinite(d2)]
    info = {**base, "status": "evaluated", "value_resolution": q, "zero_tolerance": tol,
            "zero_d2_share": round(float(np.mean(np.abs(fin_d2) <= tol)), 4),
            "zero_d2_share_expected_if_exact_linear_at_least": round(1 - 1 / period, 4),
            "documented_period_test": test, "first_difference_test": d1_test,
            "dominant_residue_offset_from_file_start": dominant,
            "exploratory_period_scan": {"estimated_fundamental_period": estimate_fundamental_period(scan),
                                        "top_by_concentration": {int(P): round(s["concentration"], 4) for P, s in
                                                                 sorted(scan.items(), key=lambda kv: -(kv[1]["concentration"] or 0))[:5]}},
            "phase_stability": phase_stability(block_phases(absd2, period, block_minutes), dominant, period),
            "knots": knot_stats(v, d2, period, tol, dominant),
            "straight_runs": straight_runs(v, d2, tol, period)}
    info["verdict"] = classify_channel(info)
    return info


# ----------------------------------------------------------------------------- run / report

def find_candidate_files(root):
    found = []
    for dirpath, _d, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".csv"):
                p = Path(dirpath) / f
                try:
                    cols = {str(c).strip() for c in pd.read_csv(p, nrows=0).columns}
                except Exception:  # noqa: BLE001
                    continue
                if "Timestamp" in cols and cols & set(DOCUMENTED_PERIODS):
                    found.append(p)
    return sorted(found)


def analyze_file(path, periods, n_perm, scan_perms, rng, block_minutes):
    header = pd.read_csv(path, nrows=0).columns
    names = {str(c).strip(): c for c in header}
    channels = [c for c in periods if c in names]
    df = pd.read_csv(path, usecols=[names["Timestamp"]] + [names[c] for c in channels])
    df.columns = [str(c).strip() for c in df.columns]
    result = {}
    for c in channels:
        v, qc = to_minute_series(df["Timestamp"], df[c])
        entry = {"grid_qc": qc}
        if v is None:
            entry.update(status="grid_unusable", verdict="insufficient_data")
        else:
            entry.update(analyze_channel(v, periods[c], n_perm, scan_perms, rng, block_minutes))
        result[c] = entry
    return result


def summarize(per_participant, periods):
    agg = {}
    for c in periods:
        entries = [p[c] for p in per_participant.values() if c in p]
        verdicts = Counter(e["verdict"] for e in entries)
        ev = [e for e in entries if e.get("status") == "evaluated"]
        agg[c] = {"participants_with_channel": len(entries), "participants_evaluated": len(ev),
                  "verdict_counts": dict(verdicts),
                  "share_consistent_among_evaluated": round(verdicts.get("consistent_with_linear_interpolation_on_fixed_grid", 0) / len(ev), 3) if ev else None,
                  "median_concentration": _median(e["documented_period_test"]["concentration"] for e in ev),
                  "median_phase_agreement_exact": _median(e["phase_stability"].get("agreement_exact") for e in ev),
                  "median_detected_per_expected_interval": _median(e["knots"]["detected_per_expected_native_interval"] for e in ev),
                  "estimated_fundamental_periods": dict(Counter(str(e["exploratory_period_scan"]["estimated_fundamental_period"]) for e in ev))}
    return agg


def _median(it):
    x = [a for a in it if a is not None and np.isfinite(a)]
    return round(float(np.median(x)), 4) if x else None


def decide(agg, n_participants, n_total_files):
    """Explicit decision rule. A PILOT result can only ever be provisional."""
    evaluated = [a for a in agg.values() if a["participants_evaluated"]]
    all_consistent = bool(evaluated) and all((a["share_consistent_among_evaluated"] or 0) >= 0.9 for a in evaluated) \
        and all((a["median_detected_per_expected_interval"] or 0) >= MIN_DETECTABLE_KNOTS for a in evaluated)
    pilot = n_participants < n_total_files
    return {
        "rule": "consistent in >=90% of evaluated participants on EVERY available channel, with enough detectable slope changes",
        "rule_met": all_consistent, "evaluated_participants": n_participants, "files_available": n_total_files,
        "scope": "pilot_only_do_not_generalise: rerun with --n-participants <all> before adopting" if pilot else "all selected files",
        "recommendation": (
            "PROVISIONAL: the fixed-grid linear-interpolation fingerprint is present. It may be used to flag filled gaps and to "
            "choose per-participant phase for cross-checks, but keep the lag guard (features use only values at least one native "
            "interval old) as the default, and describe values as 'candidate native readings (inferred)'. Confirm on all files first."
            if all_consistent else
            "FALLBACK: do not rely on inferred sampling times. Use the lag guard (features use only values at least P minutes "
            "older than the prediction time: 5 for Dexcom, 15 for Libre), treat each meal/window as one sample (never minute rows), "
            "define the target as the window maximum with the last P minutes of the window excluded from the baseline-side "
            "features, and exclude windows with NaN gaps or long sloped straight runs."),
        "never_claimed": "recovery of native timestamps. This test shows consistency with a hypothesis, not independent proof.",
    }


def _py(o):
    if isinstance(o, dict):
        return {str(k): _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    ap.add_argument("--n-participants", type=int, default=5, help="Random participants to analyse (default 5).")
    ap.add_argument("--seed", type=int, default=0, help="Seed for participant selection and permutation tests.")
    ap.add_argument("--dexcom-period", type=int, default=DOCUMENTED_PERIODS["Dexcom GL"])
    ap.add_argument("--libre-period", type=int, default=DOCUMENTED_PERIODS["Libre GL"])
    ap.add_argument("--n-perm", type=int, default=500, help=f"Permutations for the documented-period tests (minimum {MIN_PERMUTATIONS} is enforced).")
    ap.add_argument("--scan-perms", type=int, default=100, help=f"Permutations per period in the exploratory scan (minimum {MIN_PERMUTATIONS} is enforced).")
    ap.add_argument("--block-minutes", type=int, default=BLOCK_MINUTES)
    ap.add_argument("--out", default=None, help="Local JSON (default data/interim/audit_local/cgm_interpolation_audit.json).")
    args = ap.parse_args(argv)
    if args.n_participants < 1:
        print("error: --n-participants must be >= 1", file=sys.stderr)
        return 2
    try:
        root = get_dataset_root(args.data_root)
    except DatasetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    files = find_candidate_files(root)
    if not files:
        print("error: no CSV with a 'Timestamp' column and a 'Dexcom GL' or 'Libre GL' column was found.", file=sys.stderr)
        return 2

    periods = {"Dexcom GL": args.dexcom_period, "Libre GL": args.libre_period}
    rng = np.random.default_rng(args.seed)
    chosen = rng.choice(len(files), size=min(args.n_participants, len(files)), replace=False)
    per_participant, errors = {}, Counter()
    for k, i in enumerate(chosen, start=1):
        try:
            per_participant[f"P{k}"] = analyze_file(files[i], periods, args.n_perm, args.scan_perms, rng, args.block_minutes)
        except Exception as exc:  # noqa: BLE001 - never echo paths or messages
            errors[type(exc).__name__] += 1
    agg = summarize(per_participant, periods)
    report = {
        "_privacy": "aggregate-only: anonymous labels, no identifiers, file names, timestamps or rows",
        "settings": {"documented_periods_minutes": periods, "n_selected": int(len(chosen)), "files_available": len(files),
                     "seed": args.seed, "alpha": ALPHA, "min_concentration": MIN_CONCENTRATION,
                     "min_phase_agreement": MIN_PHASE_AGREEMENT, "block_minutes": args.block_minutes},
        "read_errors_by_exception_type": dict(errors),
        "per_participant_qc": per_participant,
        "aggregate_by_channel": agg,
        "decision": decide(agg, len(per_participant), len(files)),
        "epistemic_status": {
            "observed": ["residue concentration of |second difference| and of |first difference|",
                         "phase agreement across day blocks", "spacing of detected slope changes",
                         "missing-minute gaps and long straight runs"],
            "inferred_not_verified": ["candidate native sampling phase (offset from file start)",
                                      "that long sloped straight runs are interpolation-filled gaps"],
            "not_established": ["actual native timestamps", "how the dataset authors resampled or aligned devices",
                                "whether the documented periods (5 / 15 min) hold for every participant"]},
    }
    text = json.dumps(_py(report), indent=2)
    out = Path(args.out) if args.out else REPO_ROOT / "data" / "interim" / "audit_local" / "cgm_interpolation_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print("\n(aggregate-only; saved to the git-ignored local file; no data was modified)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
