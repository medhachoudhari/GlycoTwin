"""Paired Model B versus Model C comparison on the sequential out-of-fold forecasts of the two pipelines.

The comparison REFUSES to run unless the two forecast tables describe exactly the same evaluation: same event identifiers, same
participants, same fold for every event, same observed outcome for every event (and optionally the expected event and participant counts).
Uncertainty: participant-clustered percentile bootstrap (participants resampled with replacement, events kept together, one common resample
for both models); the existing `paired_cluster_bootstrap` is used for Brier, log loss and rise MAE. Differences are C minus B; for the
loss-type metrics negative favours C. An interval containing 0 is inconclusive, not 'no difference'. No claim of superiority is made here.
Subgroup and stage tables are exploratory and descriptive.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from glycotwin.models.evaluation import expected_calibration_error
from glycotwin.models.experiment import paired_cluster_bootstrap, per_event_metric
from glycotwin.models.activity_strata import ACTIVE, EXCLUDED, SEDENTARY, within_participant_strata
from glycotwin.models.reliability_svg import reliability_bins
from glycotwin.twin.quality import COLD_START_MAX_OBSERVATIONS, EXPERIENCED_MIN_OBSERVATIONS

REQUIRED = ["event_id", "participant_id", "fold", "y", "p", "mean_rise", "rise", "interval90_low", "interval90_high",
            "p_frozen_prior", "mean_rise_frozen_prior", "n_personal_before"]
STAGE_BINS = [(0, 0), (1, 4), (5, 9), (10, 19), (20, 10 ** 9)]            # reporting bins of personal observations, not minimums


class ComparisonIntegrityError(ValueError):
    """The two forecast tables are not a matched evaluation; no comparison is made."""


FOLD_COMPARISON_LIMITATION = (
    "Fold integrity is checked INTERNALLY: each file must give every participant exactly one fold, every event of a participant the same fold, "
    "and Model B and Model C must agree on the fold of every event. It is NOT checked that these folds equal Model A's folds, that they were "
    "stratified by glycaemic group, or that they came from seed 0: the forecast files do not carry that information. Those properties rest on "
    "all three runs sharing `make_participant_folds`.")


def _canonical(series: pd.Series) -> pd.Series:
    from glycotwin.twin.adapter import canonical_ids
    return canonical_ids(series)


def _check_one_file(name: str, df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ComparisonIntegrityError(f"{name} forecasts are missing columns: {missing}")
    if len(df) == 0:
        raise ComparisonIntegrityError(f"{name} forecasts are empty")
    if df["event_id"].isna().any() or df["participant_id"].isna().any() or df["fold"].isna().any():
        raise ComparisonIntegrityError(f"{name} forecasts have missing event, participant or fold values")
    if df["event_id"].duplicated().any():
        raise ComparisonIntegrityError(f"{name} forecasts contain duplicated event identifiers")
    if not np.isfinite(df[["p", "mean_rise", "rise", "p_frozen_prior", "mean_rise_frozen_prior"]].to_numpy(dtype=float)).all():
        raise ComparisonIntegrityError(f"{name} forecasts contain non-finite values")
    if not df["y"].isin([0, 1]).all():
        raise ComparisonIntegrityError(f"{name} forecasts have labels that are not 0 or 1")
    probs = df[["p", "p_frozen_prior"]].to_numpy(dtype=float)
    if ((probs < 0) | (probs > 1)).any():
        raise ComparisonIntegrityError(f"{name} forecasts have probabilities outside [0, 1]")
    if (df["interval90_low"] > df["interval90_high"]).any():
        raise ComparisonIntegrityError(f"{name} forecasts have an interval with low > high")
    folds = pd.to_numeric(df["fold"], errors="coerce")
    if folds.isna().any() or (folds < 0).any() or (folds != np.floor(folds)).any():
        raise ComparisonIntegrityError(f"{name} forecasts have fold values that are not non-negative integers")
    per_person = df.assign(_pid=_canonical(df["participant_id"])).groupby("_pid")["fold"].nunique()
    if (per_person > 1).any():
        raise ComparisonIntegrityError(f"{name}: {int((per_person > 1).sum())} participants appear in more than one fold "
                                       f"(folds must be participant-level)")


def verify_matched(oof_b: pd.DataFrame, oof_c: pd.DataFrame, expected_events: Optional[int] = None,
                   expected_participants: Optional[int] = None) -> dict:
    for name, df in (("Model B", oof_b), ("Model C", oof_c)):
        _check_one_file(name, df)
    if set(oof_b["event_id"]) != set(oof_c["event_id"]):
        raise ComparisonIntegrityError(f"event sets differ (B {len(oof_b)} events, C {len(oof_c)} events, {len(set(oof_b['event_id']) ^ set(oof_c['event_id']))} not shared)")
    b, c = oof_b.set_index("event_id").sort_index(), oof_c.set_index("event_id").sort_index()
    pb, pc = _canonical(b["participant_id"]), _canonical(c["participant_id"])
    if (pb != pc).any():
        raise ComparisonIntegrityError(f"{int((pb != pc).sum())} events belong to different participants in B and C")
    if set(pb) != set(pc):
        raise ComparisonIntegrityError("participant sets differ")
    if (b["fold"].astype(int) != c["fold"].astype(int)).any():
        raise ComparisonIntegrityError(f"{int((b['fold'].astype(int) != c['fold'].astype(int)).sum())} events were validated in different folds")
    if (b["y"].astype(int) != c["y"].astype(int)).any():
        raise ComparisonIntegrityError(f"{int((b['y'].astype(int) != c['y'].astype(int)).sum())} events have different observed labels")
    if not np.allclose(b["rise"].to_numpy(float), c["rise"].to_numpy(float)):
        raise ComparisonIntegrityError("observed rises differ between B and C")
    n_events, n_part = int(len(b)), int(pb.nunique())
    if expected_events is not None and n_events != expected_events:
        raise ComparisonIntegrityError(f"expected {expected_events} events, found {n_events}")
    if expected_participants is not None and n_part != expected_participants:
        raise ComparisonIntegrityError(f"expected {expected_participants} participants, found {n_part}")
    per_fold = pd.DataFrame({"pid": pb, "fold": b["fold"].astype(int)}).drop_duplicates().groupby("fold").size()
    return {"n_events": n_events, "n_participants": n_part, "same_event_ids": True, "same_participants": True, "same_folds": True,
            "each_participant_in_exactly_one_fold": True, "same_labels": True, "same_observed_rises": True,
            "n_folds": int(len(per_fold)), "participants_per_fold": {int(k): int(v) for k, v in per_fold.items()},
            "expected_events_checked": expected_events, "expected_participants_checked": expected_participants,
            "fold_comparison_limitation": FOLD_COMPARISON_LIMITATION}


# ----------------------------------------------------------------------------- statistics

def _aligned(oof_b: pd.DataFrame, oof_c: pd.DataFrame):
    return oof_b.sort_values("event_id").reset_index(drop=True), oof_c.sort_values("event_id").reset_index(drop=True)


def _pooled_stats(y, p) -> dict:
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    two = 0 < y.sum() < len(y)
    return {"roc_auc": float(roc_auc_score(y, p)) if two else np.nan, "pr_auc": float(average_precision_score(y, p)) if two else np.nan,
            "brier": float(np.mean((p - y) ** 2)), "ece10": float(expected_calibration_error(y, p, 10)[0]), "ece5": float(expected_calibration_error(y, p, 5)[0])}


def _cluster_indices(participants: np.ndarray):
    ids, inv = np.unique(participants, return_inverse=True)
    return ids, [np.flatnonzero(inv == k) for k in range(len(ids))]


def _boot_pooled(b: pd.DataFrame, c: pd.DataFrame, n_boot: int, seed: int) -> dict:
    """Participant-clustered bootstrap of (C minus B) for the pooled statistics; one common resample for both models."""
    _, idx = _cluster_indices(b["participant_id"].to_numpy())
    rng = np.random.default_rng(seed)
    names = ["roc_auc", "pr_auc", "brier", "ece10", "ece5"]
    diffs = {n: [] for n in names}
    skipped = 0
    yb, pb, pc = b["y"].to_numpy(int), b["p"].to_numpy(float), c["p"].to_numpy(float)
    for _ in range(n_boot):
        take = np.concatenate([idx[k] for k in rng.integers(0, len(idx), size=len(idx))])
        if not (0 < yb[take].sum() < len(take)):
            skipped += 1
            continue
        sb, sc = _pooled_stats(yb[take], pb[take]), _pooled_stats(yb[take], pc[take])
        for n in names:
            diffs[n].append(sc[n] - sb[n])
    out = {"n_boot": n_boot, "seed": seed, "n_draws_skipped_single_class": skipped}
    for n in names:
        v = np.asarray(diffs[n])
        out[n] = (float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))) if len(v) else (None, None)
    return out


def _boot_event_mean(d: np.ndarray, participants: np.ndarray, n_boot: int, seed: int):
    _, idx = _cluster_indices(participants)
    sums, counts = np.array([d[i].sum() for i in idx]), np.array([len(i) for i in idx])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(idx), size=(n_boot, len(idx)))
    boot = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    return float(sums.sum() / counts.sum()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def _row(estimate, lo, hi, b_value, c_value) -> dict:
    return {"model_b": b_value, "model_c": c_value, "difference_c_minus_b": estimate, "ci95": [lo, hi], "ci_excludes_zero": bool(lo > 0 or hi < 0)}


# ----------------------------------------------------------------------------- blueprint section 21-22 splits

def _stratum_block(b: pd.DataFrame, c: pd.DataFrame, mask, n_boot: int, seed: int) -> dict:
    """B and C on the SAME events of one stratum. Differences are C minus B (negative favours C), participant-clustered 95% intervals."""
    m = np.asarray(mask, dtype=bool)
    sb, sc = b[m], c[m]
    row = {"n_events": int(m.sum()), "n_participants": int(sb["participant_id"].nunique())}
    if m.sum() == 0:
        return {**row, "note": "empty stratum"}
    for name, df in (("model_b", sb), ("model_c", sc)):
        st = _pooled_stats(df["y"], df["p"])
        row[name] = {"brier": st["brier"], "ece10_descriptive": st["ece10"], "roc_auc": st["roc_auc"],
                     "rise_mae_mg_dl": float(np.abs(df["mean_rise"] - df["rise"]).mean()),
                     "log_loss": float(per_event_metric(df.assign(model=name), "log_loss").mean())}
    parts = sb["participant_id"].to_numpy()
    for key, d in (("brier", ((sc["p"] - sc["y"]) ** 2).to_numpy(float) - ((sb["p"] - sb["y"]) ** 2).to_numpy(float)),
                   ("log_loss", per_event_metric(sc.assign(model="c"), "log_loss").to_numpy(float) - per_event_metric(sb.assign(model="b"), "log_loss").to_numpy(float)),
                   ("rise_mae_mg_dl", np.abs(sc["mean_rise"] - sc["rise"]).to_numpy(float) - np.abs(sb["mean_rise"] - sb["rise"]).to_numpy(float))):
        e, lo, hi = _boot_event_mean(d, parts, n_boot, seed)
        row[f"difference_c_minus_b_{key}"] = {"estimate": e, "ci95": [lo, hi], "ci_excludes_zero": bool(lo > 0 or hi < 0)}
    return row


def cold_start_vs_experienced(b: pd.DataFrame, c: pd.DataFrame, n_boot: int, seed: int) -> dict:
    """Blueprint section 21: cold-start (the person's first 3 meals) versus experienced twin (10 or more observed meals).
    `n_personal_before` is the number of the person's own meals already observed when the forecast was made, so the first meal has 0.
    cold-start = 0, 1 or 2 earlier meals (the first three meals); experienced = 10 or more earlier meals. Meals with 3-9 earlier meals
    belong to neither group and are counted, not analysed. Descriptive: the groups contain different meals of different people, and the
    interval for the difference is for that stratum only."""
    nb = b["n_personal_before"].to_numpy(int)
    agrees = bool((nb == c["n_personal_before"].to_numpy(int)).all())
    cold, exp = nb < COLD_START_MAX_OBSERVATIONS, nb >= EXPERIENCED_MIN_OBSERVATIONS
    return {"definition": f"cold-start: n_personal_before < {COLD_START_MAX_OBSERVATIONS} (first {COLD_START_MAX_OBSERVATIONS} meals); "
                          f"experienced: n_personal_before >= {EXPERIENCED_MIN_OBSERVATIONS} (blueprint section 21)",
            "n_personal_before_agrees_between_b_and_c": agrees,
            "n_events_in_neither_group": int((~cold & ~exp).sum()),
            "cold_start": _stratum_block(b, c, cold, n_boot, seed), "experienced": _stratum_block(b, c, exp, n_boot, seed),
            "interpretation_limits": "Exploratory and descriptive; strata hold different meals of different people; no multiplicity adjustment."}


def active_vs_sedentary_per_participant(b: pd.DataFrame, c: pd.DataFrame, n_boot: int, seed: int) -> Optional[dict]:
    """Blueprint sections 21-22: each patient's own active-day meals versus sedentary-day meals (the core comparison). The definition is in
    `glycotwin.models.activity_strata` and docs/activity_definition.md: relative to the person's own median pre-meal activity. Uses the
    activity value recorded by the Model C run; returns None if that column is absent."""
    if "activity" not in c.columns or c["activity"].isna().any():
        return None
    labels = within_participant_strata(c["participant_id"], c["activity"]).to_numpy()
    act = _stratum_block(b, c, labels == ACTIVE, n_boot, seed)
    sed = _stratum_block(b, c, labels == SEDENTARY, n_boot, seed)
    out = {"definition": "active = pre-meal activity strictly above the participant's own median over the compared events; sedentary = at or below; "
                         "participants lacking >= 2 events on each side are excluded. Analysis label only: it feeds no forecast.",
           "n_events_excluded": int((labels == EXCLUDED).sum()), "n_participants_excluded": int(c.loc[labels == EXCLUDED, "participant_id"].nunique()),
           "active": act, "sedentary": sed}
    if act.get("n_events") and sed.get("n_events"):
        da, ds = act["difference_c_minus_b_brier"], sed["difference_c_minus_b_brier"]
        out["blueprint_conditions_on_brier"] = {
            "c_better_on_active_meals_interval_excludes_zero": bool(da["ci95"][1] < 0),
            "c_at_least_as_good_on_sedentary_meals_point_estimate": bool(ds["estimate"] <= 0),
            "sedentary_interval": ds["ci95"],
            "note": ("These are the two conditions of blueprint section 22 applied to the Brier score only. No non-inferiority margin was "
                     "prespecified, so 'at least as good' is judged on the point estimate and the interval is shown. They are NOT the full "
                     "decision rules of docs/INNOVATION_ROADMAP.md (which also need the frozen-prior and permuted-activity controls), and "
                     "meeting them would not establish superiority.")}
    return out


# ----------------------------------------------------------------------------- Model A, glycaemic groups, per-participant metrics (blueprint 21-22)

A_REQUIRED = ["event_id", "participant_id", "fold", "y", "p"]


def verify_model_a_matches(oof_a: pd.DataFrame, oof_b: pd.DataFrame) -> dict:
    """Model A is trained on every core-eligible event, B/C on the activity-eligible subset, so A may hold MORE events. The shared events must
    agree exactly on participant, fold and label, and every participant must sit in one fold. This is the check that Model A, B and C used the
    same participant-level folds (the limitation noted for the two-model comparison)."""
    missing = [c for c in A_REQUIRED if c not in oof_a.columns]
    if missing:
        raise ComparisonIntegrityError(f"Model A forecasts are missing columns: {missing}")
    if len(oof_a) == 0 or oof_a["event_id"].duplicated().any() or oof_a[["event_id", "participant_id", "fold"]].isna().any().any():
        raise ComparisonIntegrityError("Model A forecasts are empty, have duplicated event identifiers, or have missing identifiers")
    if not np.isfinite(oof_a["p"].to_numpy(float)).all() or ((oof_a["p"] < 0) | (oof_a["p"] > 1)).any() or not oof_a["y"].isin([0, 1]).all():
        raise ComparisonIntegrityError("Model A forecasts have non-finite or out-of-range probabilities, or labels that are not 0 or 1")
    per_person = oof_a.assign(_pid=_canonical(oof_a["participant_id"])).groupby("_pid")["fold"].nunique()
    if (per_person > 1).any():
        raise ComparisonIntegrityError(f"Model A: {int((per_person > 1).sum())} participants appear in more than one fold")
    shared = set(oof_b["event_id"])
    if not shared <= set(oof_a["event_id"]):
        raise ComparisonIntegrityError(f"{len(shared - set(oof_a['event_id']))} Model B/C events are absent from the Model A forecasts")
    a = oof_a.set_index("event_id").loc[sorted(shared)]
    b = oof_b.set_index("event_id").loc[sorted(shared)]
    if (_canonical(a["participant_id"]) != _canonical(b["participant_id"])).any():
        raise ComparisonIntegrityError("shared events belong to different participants in Model A and Model B/C")
    if (a["fold"].astype(int) != b["fold"].astype(int)).any():
        raise ComparisonIntegrityError(f"{int((a['fold'].astype(int) != b['fold'].astype(int)).sum())} shared events were validated in different folds in Model A and Model B/C")
    if (a["y"].astype(int) != b["y"].astype(int)).any():
        raise ComparisonIntegrityError("shared events have different labels in Model A and Model B/C")
    return {"n_model_a_events": int(len(oof_a)), "n_shared_events": int(len(shared)), "n_model_a_only_events": int(len(oof_a) - len(shared)),
            "same_folds_as_model_a_on_shared_events": True, "same_labels_as_model_a": True}


def key_experiment_three_models(oof_a: pd.DataFrame, b: pd.DataFrame, c: pd.DataFrame, n_boot: int, seed: int) -> dict:
    """Blueprint section 22: Model A versus B versus C on the SAME events (those in the B/C comparison). Calibration is the primary target
    (Brier, ECE, reliability bins), AUROC/AUPRC secondary. Differences are second minus first; participant-clustered percentile intervals."""
    info = verify_model_a_matches(oof_a, b)
    a = oof_a.set_index("event_id").loc[b["event_id"]].reset_index()
    a = a.assign(participant_id=b["participant_id"].to_numpy())
    frames = {"model_a": a, "model_b": b, "model_c": c}
    stats = {k: _pooled_stats(f["y"], f["p"]) for k, f in frames.items()}
    out = {"integrity": info, "n_events": int(len(b)), "models": stats,
           "reliability_bins_10": {k: reliability_bins(f["y"], f["p"]) for k, f in frames.items()}, "differences": {}}
    for first, second in (("model_a", "model_b"), ("model_a", "model_c"), ("model_b", "model_c")):
        boots = _boot_pooled(frames[first].assign(y=b["y"].to_numpy()), frames[second], n_boot, seed)
        d = {}
        for key in ("roc_auc", "pr_auc", "brier", "ece10", "ece5"):
            lo, hi = boots[key]
            est = stats[second][key] - stats[first][key]
            d[key] = {"estimate": est, "ci95": [lo, hi], "ci_excludes_zero": bool(lo is not None and (lo > 0 or hi < 0))}
        out["differences"][f"{second}_minus_{first}"] = d
    out["note"] = ("Model A uses population features only; B and C use sequential personal updates. Differences are second minus first (negative favours "
                   "the second model for Brier and ECE). Exploratory, no multiplicity adjustment; an interval containing 0 is inconclusive.")
    return out


def glycaemic_group_breakdown(b: pd.DataFrame, c: pd.DataFrame, group_of: Dict[str, str], n_boot: int, seed: int, min_participants: int = 5) -> dict:
    """Blueprint section 21: results per glycaemic group. `group_of` maps participant id -> group (any spelling of the id; ids are canonicalised).
    Every participant in the comparison must have a group, otherwise the breakdown is refused rather than silently dropping people."""
    gmap = {_canonical_one(k): str(v) for k, v in group_of.items()}
    pids = _canonical(b["participant_id"])
    missing = sorted(set(pids) - set(gmap))
    if missing:
        raise ComparisonIntegrityError(f"{len(missing)} participants in the comparison have no glycaemic group")
    grp = pids.map(gmap).to_numpy()
    out = {"groups": {}, "min_participants_for_a_group_claim": min_participants,
           "note": "Per-group strata hold few participants; read them as descriptive. No multiplicity adjustment."}
    for g in sorted(set(grp)):
        blk = _stratum_block(b, c, grp == g, n_boot, seed)
        blk["too_few_participants_for_a_group_claim"] = bool(blk["n_participants"] < min_participants)
        out["groups"][g] = blk
    return out


def _canonical_one(value) -> str:
    from glycotwin.twin.adapter import canonical_participant_id
    return canonical_participant_id(value)


def per_participant_metric_distribution(b: pd.DataFrame, c: pd.DataFrame, min_events: int = 8) -> dict:
    """Blueprint section 21: per-patient Brier/AUROC "where enough meals exist". Aggregate only (no participant rows): how many participants
    qualify and how the per-participant C-minus-B differences are distributed."""
    brier_d, auc_d = [], []
    for pid, g in b.groupby("participant_id"):
        if len(g) < min_events:
            continue
        gc = c[c["participant_id"] == pid]
        brier_d.append(float(((gc["p"].to_numpy() - gc["y"].to_numpy()) ** 2).mean() - ((g["p"].to_numpy() - g["y"].to_numpy()) ** 2).mean()))
        if 0 < g["y"].sum() < len(g):
            auc_d.append(float(roc_auc_score(gc["y"], gc["p"]) - roc_auc_score(g["y"], g["p"])))

    def summ(v, better_if_negative):
        if not v:
            return {"n_participants": 0}
        a = np.asarray(v)
        return {"n_participants": len(v), "median_difference": float(np.median(a)), "q25": float(np.quantile(a, .25)), "q75": float(np.quantile(a, .75)),
                "n_c_better": int((a < 0).sum() if better_if_negative else (a > 0).sum()), "n_c_worse": int((a > 0).sum() if better_if_negative else (a < 0).sum()),
                "n_equal": int((a == 0).sum())}
    return {"min_events_per_participant": min_events, "brier_c_minus_b": summ(brier_d, True),
            "auroc_c_minus_b_participants_with_both_classes": summ(auc_d, False),
            "note": "Descriptive counts of participants; per-person estimates from a few meals are noisy."}


def paired_report(oof_b: pd.DataFrame, oof_c: pd.DataFrame, n_boot: int = 2000, seed: int = 0,
                  expected_events: Optional[int] = None, expected_participants: Optional[int] = None, mae_tolerance_mg_dl: float = 1.0,
                  oof_a: Optional[pd.DataFrame] = None, group_of: Optional[Dict[str, str]] = None) -> dict:
    integrity = verify_matched(oof_b, oof_c, expected_events, expected_participants)
    b, c = _aligned(oof_b, oof_c)
    part = b["participant_id"].to_numpy()
    pb, pc = _pooled_stats(b["y"], b["p"]), _pooled_stats(b["y"], c["p"])
    boots = _boot_pooled(b, c, n_boot, seed)
    metrics = {}
    for key in ("roc_auc", "pr_auc", "ece10", "ece5"):
        lo, hi = boots[key]
        metrics[key] = _row(pc[key] - pb[key], lo, hi, pb[key], pc[key])
    recs = pd.concat([c.assign(model="C"), b.assign(model="B")], ignore_index=True)
    for key, name in (("brier", "brier"), ("log_loss", "log_loss"), ("rise_mae_mg_dl", "mae_rise")):
        r = paired_cluster_bootstrap(recs, "C", "B", name, n_boot=n_boot, seed=seed)
        vb = float(per_event_metric(b.assign(model="B"), name).mean()); vc = float(per_event_metric(c.assign(model="C"), name).mean())
        metrics[key] = _row(r["estimate"], r["ci_low"], r["ci_high"], vb, vc)
    err_b, err_c = (b["mean_rise"] - b["rise"]).to_numpy(float), (c["mean_rise"] - c["rise"]).to_numpy(float)
    est, lo, hi = _boot_event_mean(err_c - err_b, part, n_boot, seed)
    metrics["mean_rise_error_mg_dl"] = {**_row(est, lo, hi, float(err_b.mean()), float(err_c.mean())),
                                        "note": "signed (predicted minus observed); negative = under-prediction; a bias measure, not an accuracy measure"}
    cov_b = ((b["rise"] >= b["interval90_low"]) & (b["rise"] <= b["interval90_high"])).to_numpy(float)
    cov_c = ((c["rise"] >= c["interval90_low"]) & (c["rise"] <= c["interval90_high"])).to_numpy(float)
    est, lo, hi = _boot_event_mean(cov_c - cov_b, part, n_boot, seed)
    metrics["coverage_90pct_interval"] = {**_row(est, lo, hi, float(cov_b.mean()), float(cov_c.mean())), "nominal": 0.90}
    # each model against its own never-updated prior (negative favours the updated model)
    frozen = {}
    for label, df in (("model_b", b), ("model_c", c)):
        fr = pd.concat([df.assign(model="updated"), df.assign(model="frozen", p=df["p_frozen_prior"], mean_rise=df["mean_rise_frozen_prior"])], ignore_index=True)
        frozen[label] = {name: {k: v for k, v in paired_cluster_bootstrap(fr, "updated", "frozen", name, n_boot=n_boot, seed=seed).items()
                                if k in ("estimate", "ci_low", "ci_high", "interval_excludes_zero", "n_events", "n_participants")}
                         for name in ("brier", "log_loss", "mae_rise")}
    # participant-level MAE
    mae_b = pd.Series(np.abs(b["mean_rise"] - b["rise"]).to_numpy(float)).groupby(part).mean()
    mae_c = pd.Series(np.abs(c["mean_rise"] - c["rise"]).to_numpy(float)).groupby(part).mean()
    delta = mae_c - mae_b
    participant_level = {"tolerance_mg_dl": mae_tolerance_mg_dl, "n_participants": int(len(delta)),
                         "c_improved_by_more_than_tolerance": int((delta < -mae_tolerance_mg_dl).sum()),
                         "c_worsened_by_more_than_tolerance": int((delta > mae_tolerance_mg_dl).sum()),
                         "within_tolerance": int((delta.abs() <= mae_tolerance_mg_dl).sum())}
    # exploratory: pooled activity tertiles of the compared events (Model C records the activity value)
    tert = None
    if "activity" in c.columns and c["activity"].notna().all():
        cuts = np.quantile(c["activity"].to_numpy(float), [1 / 3, 2 / 3])
        which = np.digitize(c["activity"].to_numpy(float), cuts)
        tert = {"definition": "pooled tertiles of the compared events' pre-meal activity (exploratory; cut points computed on these same events, so not a prespecified or training-fold definition)",
                "cut_points": [float(x) for x in cuts], "tertiles": {}}
        for k, name in enumerate(("low", "middle", "high")):
            m = which == k
            if m.sum() == 0:                                  # constant or heavily tied activity can leave a tertile empty
                tert["tertiles"][name] = {"n_events": 0, "n_participants": 0, "note": "empty: tied activity values"}
                continue
            sb_, sc_ = b[m], c[m]
            row = {"n_events": int(m.sum()), "n_participants": int(sb_["participant_id"].nunique())}
            for mod, df in (("model_b", sb_), ("model_c", sc_)):
                st = _pooled_stats(df["y"], df["p"])
                row[mod] = {"roc_auc": st["roc_auc"], "brier": st["brier"], "rise_mae_mg_dl": float(np.abs(df["mean_rise"] - df["rise"]).mean())}
            d_brier = ((sc_["p"] - sc_["y"]) ** 2).to_numpy(float) - ((sb_["p"] - sb_["y"]) ** 2).to_numpy(float)
            d_mae = np.abs(sc_["mean_rise"] - sc_["rise"]).to_numpy(float) - np.abs(sb_["mean_rise"] - sb_["rise"]).to_numpy(float)
            for nm, d in (("brier", d_brier), ("rise_mae_mg_dl", d_mae)):
                e, l, h = _boot_event_mean(d, sb_["participant_id"].to_numpy(), n_boot, seed)
                row[f"difference_c_minus_b_{nm}"] = {"estimate": e, "ci95": [l, h]}
            tert["tertiles"][name] = row
    # exploratory: number of personal observations available at forecast time (cold start versus warm)
    stages = {}
    for lo_n, hi_n in STAGE_BINS:
        m = ((b["n_personal_before"] >= lo_n) & (b["n_personal_before"] <= hi_n)).to_numpy()
        if m.sum() == 0:
            continue
        sb_, sc_ = b[m], c[m]
        label = f"{lo_n}" if lo_n == hi_n else (f"{lo_n}+" if hi_n >= 10 ** 9 else f"{lo_n}-{hi_n}")
        stages[label] = {"n_events": int(m.sum()), "brier_b": float(np.mean((sb_["p"] - sb_["y"]) ** 2)), "brier_c": float(np.mean((sc_["p"] - sc_["y"]) ** 2)),
                         "rise_mae_b": float(np.abs(sb_["mean_rise"] - sb_["rise"]).mean()), "rise_mae_c": float(np.abs(sc_["mean_rise"] - sc_["rise"]).mean())}
    return {
        "_status": "RESEARCH COMPARISON. Not clinically validated. Differences are C minus B; intervals are participant-clustered 95% percentile intervals.",
        "integrity": integrity, "bootstrap": {"n_boot": n_boot, "seed": seed}, "metrics": metrics,
        "n_intervals_excluding_zero": int(sum(v["ci_excludes_zero"] for v in metrics.values())), "n_intervals_reported": len(metrics),
        "frozen_prior_comparisons": {"_reading": "estimate = mean(metric_updated - metric_frozen_prior); negative favours the updated model", **frozen},
        "reliability_bins_10": {"_note": "aggregate equal-width bins of the pooled out-of-fold probabilities (counts, mean predicted, mean observed)",
                                "model_b": reliability_bins(b["y"], b["p"]), "model_c": reliability_bins(b["y"], c["p"])},
        "participant_level_rise_mae": participant_level, "activity_tertiles_exploratory": tert,
        "cold_start_vs_experienced": cold_start_vs_experienced(b, c, n_boot, seed),
        "active_vs_sedentary_per_participant": active_vs_sedentary_per_participant(b, c, n_boot, seed),
        "per_participant_metric_distribution": per_participant_metric_distribution(b, c),
        "key_experiment_model_a_b_c": None if oof_a is None else key_experiment_three_models(oof_a, b, c, n_boot, seed),
        "glycaemic_group_breakdown": None if group_of is None else glycaemic_group_breakdown(b, c, group_of, n_boot, seed), "personal_observation_stage_exploratory": {
            "_note": "reporting bins of the number of the person's own observations used at forecast time; descriptive, not minimums", **stages},
        "not_computed": ([] if oof_a is not None else ["Model A comparison (pass the Model A out-of-fold file)"]) + ([] if group_of is not None else ["glycaemic-group breakdown (needs a participant-to-group file)"]) + ["exclusion of participants with extreme estimated gamma (the researcher's rule is not in the repository)"],
        "interpretation_limits": "No multiplicity adjustment; one fold assignment; tertile, stage and participant-level tables are exploratory; no claim of superiority is made by this module.",
    }
