"""Prior-versus-prior comparison for the Model B and Model C research runs (sensitivity analysis S2/S3).

Four out-of-fold forecast files, one per arm, produced by the SAME runners on the SAME event table, folds and seed:
    b_eb  Model B, empirical-Bayes prior (primary)      c_eb  Model C, empirical-Bayes prior (primary)
    b_bp  Model B, blueprint prior                       c_bp  Model C, blueprint prior (gamma relative sd recorded)
plus each run's report manifest. The comparison REFUSES (PriorComparisonError) unless all four describe exactly the same evaluation: the same event
identifiers, participants, folds, labels, observed rises and personal-observation counts, the same event table file and settings, seed, channel and
fold hash, and prior metadata that matches each arm. Nothing is aligned or dropped silently.

Reported (all lower-is-better metrics: Brier, log loss, ECE with 10 and 5 bins, rise MAE), each with a participant-clustered percentile bootstrap
(one common resample of participants for all four arms, events of a participant kept together):
    blueprint minus empirical Bayes, for Model B and for Model C;
    Model C minus Model B under each prior;
    the change in the C-minus-B contrast between priors  [(C_bp - B_bp) - (C_eb - B_eb)].
Negative favours the second-named arm (blueprint; C). An interval containing 0 is inconclusive, not 'no difference'.

Where the priors were learned: the runners fit every prior on training folds only (tested in tests/test_prior_scheme_runners.py). This module cannot re-derive that
from forecasts; it checks the manifests' declarations (scheme, 'training folds only', one prior per held-out participant, fold hash) and refuses if they disagree.

The adoption screen at the end is a PRESPECIFIED decision rule that triggers human review. It is not proof of equivalence or superiority.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from glycotwin.models.evaluation import expected_calibration_error
from glycotwin.models.model_bc_compare import ComparisonIntegrityError, _canonical, _check_one_file
from glycotwin.models.prior_schemes import GAMMA_WIDTHS

ARMS = ("b_eb", "b_bp", "c_eb", "c_bp")
ARM_MODEL = {"b_eb": "B", "b_bp": "B", "c_eb": "C", "c_bp": "C"}
ARM_SCHEME = {"b_eb": "empirical_bayes", "b_bp": "blueprint", "c_eb": "empirical_bayes", "c_bp": "blueprint"}
METRICS = ("brier", "log_loss", "ece10", "ece5", "rise_mae_mg_dl")
CONTRASTS = {
    "model_b_blueprint_minus_empirical_bayes": lambda m: {k: m["b_bp"][k] - m["b_eb"][k] for k in METRICS},
    "model_c_blueprint_minus_empirical_bayes": lambda m: {k: m["c_bp"][k] - m["c_eb"][k] for k in METRICS},
    "c_minus_b_under_empirical_bayes": lambda m: {k: m["c_eb"][k] - m["b_eb"][k] for k in METRICS},
    "c_minus_b_under_blueprint": lambda m: {k: m["c_bp"][k] - m["b_bp"][k] for k in METRICS},
    "change_in_c_minus_b_contrast_blueprint_minus_empirical_bayes":
        lambda m: {k: (m["c_bp"][k] - m["b_bp"][k]) - (m["c_eb"][k] - m["b_eb"][k]) for k in METRICS},
}

DECISION_RULE_TEXT = (
    "PRESPECIFIED SCREEN (fixed before any real run; changing it afterwards is a protocol change). The blueprint prior becomes a CANDIDATE default, "
    "for human review only, if for BOTH Model B and Model C: (1) the Brier difference (blueprint minus empirical Bayes) has a 95% interval entirely below 0, "
    "(2) the log-loss difference has a 95% interval entirely below 0, and (3) the 10-bin ECE difference does NOT have an interval entirely above 0. "
    "Each gamma width is screened separately; the best-looking width is never selected. Meeting the screen does not establish superiority; failing it does "
    "not establish equivalence; neither says anything about clinical use. The empirical-Bayes prior stays the default until the researcher decides.")


class PriorComparisonError(ComparisonIntegrityError):
    """The four arms are not a matched evaluation; no comparison is made."""


# ----------------------------------------------------------------------------- validation

def _manifest(x) -> dict:
    if isinstance(x, dict) and "manifest" in x:
        return x["manifest"]
    if isinstance(x, dict):
        return x
    raise PriorComparisonError("a manifest/report must be a JSON object")


def validate_prior_arms(frames: Dict[str, pd.DataFrame], reports: Dict[str, dict], expected_events: Optional[int] = None,
                        expected_participants: Optional[int] = None, expected_gamma: Optional[float] = None) -> dict:
    if set(frames) != set(ARMS) or set(reports) != set(ARMS):
        raise PriorComparisonError(f"exactly the four arms {ARMS} are required (frames and manifests)")
    for arm in ARMS:
        try:
            _check_one_file(f"arm {arm}", frames[arm])
        except ComparisonIntegrityError as exc:
            raise PriorComparisonError(str(exc)) from None
        if "n_personal_before" not in frames[arm].columns:
            raise PriorComparisonError(f"arm {arm} has no n_personal_before column")
    ref = frames["c_eb"].set_index("event_id").sort_index()
    ref_pid = _canonical(ref["participant_id"])
    n_part = int(ref_pid.nunique())
    for arm in ARMS:
        cur = frames[arm].set_index("event_id").sort_index()
        if set(cur.index) != set(ref.index):
            raise PriorComparisonError(f"arm {arm} does not hold the same events as c_eb ({len(cur)} vs {len(ref)} events, "
                                       f"{len(set(cur.index) ^ set(ref.index))} not shared)")
        if (_canonical(cur["participant_id"]) != ref_pid).any():
            raise PriorComparisonError(f"arm {arm}: events belong to different participants than in c_eb")
        if (cur["fold"].astype(int) != ref["fold"].astype(int)).any():
            raise PriorComparisonError(f"arm {arm}: events were validated in different folds than in c_eb")
        if (cur["y"].astype(int) != ref["y"].astype(int)).any():
            raise PriorComparisonError(f"arm {arm}: observed labels differ from c_eb")
        if not np.allclose(cur["rise"].to_numpy(float), ref["rise"].to_numpy(float)):
            raise PriorComparisonError(f"arm {arm}: observed rises differ from c_eb")
        if (cur["n_personal_before"].astype(int) != ref["n_personal_before"].astype(int)).any():
            raise PriorComparisonError(f"arm {arm}: personal-observation counts differ from c_eb (the evaluations are not the same sequence)")
    n_events = int(len(ref))
    if expected_events is not None and n_events != expected_events:
        raise PriorComparisonError(f"expected {expected_events} events, found {n_events}")
    if expected_participants is not None and n_part != expected_participants:
        raise PriorComparisonError(f"expected {expected_participants} participants, found {n_part}")

    m = {a: _manifest(reports[a]) for a in ARMS}
    for a in ARMS:
        if not str(m[a].get("model", "")).startswith(ARM_MODEL[a] + ":"):
            raise PriorComparisonError(f"arm {a}: the manifest is not a Model {ARM_MODEL[a]} run")
        pr = m[a].get("prior")
        if not isinstance(pr, dict) or "scheme" not in pr:
            raise PriorComparisonError(f"arm {a}: the manifest has no prior metadata (re-run with the current runners)")
        if pr["scheme"] != ARM_SCHEME[a]:
            raise PriorComparisonError(f"arm {a}: prior scheme is {pr['scheme']!r}, expected {ARM_SCHEME[a]!r}")
        if "training folds only" not in str(pr.get("fitted_on", "")):
            raise PriorComparisonError(f"arm {a}: the manifest does not declare that the prior was fitted on training folds only")
        want_gamma = a == "c_bp"
        g = pr.get("gamma_relative_sd")
        if want_gamma:
            if g not in GAMMA_WIDTHS:
                raise PriorComparisonError(f"arm c_bp: gamma_relative_sd must be one of {GAMMA_WIDTHS}; manifest says {g!r}")
            if expected_gamma is not None and g != expected_gamma:
                raise PriorComparisonError(f"arm c_bp: gamma_relative_sd is {g}, expected {expected_gamma}")
        elif g is not None:
            raise PriorComparisonError(f"arm {a}: a gamma width is recorded but this arm has none")
        if ARM_SCHEME[a] == "blueprint" and pr.get("n_participant_priors") != n_part:
            raise PriorComparisonError(f"arm {a}: the manifest records {pr.get('n_participant_priors')} participant priors for {n_part} participants")
    if "activity-eligible" not in str(m["b_eb"].get("population", "")) or "activity-eligible" not in str(m["b_bp"].get("population", "")):
        raise PriorComparisonError("Model B arms must be run with --population activity-eligible (Model C's events)")
    for key, what in (("seed_for_folds", "fold seed"), ("fold_assignment_sha256", "fold hash"), ("cgm_channel", "CGM channel"),
                      ("event_table_file_sha256", "event table file hash"), ("event_table_settings", "event table settings")):
        vals = [m[a].get(key) for a in ARMS]
        if any(v is None for v in vals):
            raise PriorComparisonError(f"a manifest has no {what} ({key}); re-run with the current runners")
        if any(v != vals[0] for v in vals):
            raise PriorComparisonError(f"the four arms disagree on the {what}")
    for a in ARMS:
        rep = reports[a]
        if isinstance(rep, dict) and "data" in rep and rep["data"].get("n_events") not in (None, n_events):
            raise PriorComparisonError(f"arm {a}: the report counts {rep['data']['n_events']} events but the forecast file has {n_events}")
    settings = m["c_eb"]["event_table_settings"]
    revisions = {m[a].get("git_commit") for a in ARMS}
    return {"n_events": n_events, "n_participants": n_part, "same_event_ids": True, "same_participants": True, "same_folds": True,
            "same_labels": True, "same_observed_rises": True, "same_personal_observation_counts": True,
            "same_event_table_file": True, "same_seed": True, "same_channel": m["c_eb"]["cgm_channel"], "fold_assignment_sha256": m["c_eb"]["fold_assignment_sha256"],
            "seed_for_folds": m["c_eb"]["seed_for_folds"], "event_table_settings": settings,
            "event_table_settings_known": not str(settings.get("status", "")).startswith("UNKNOWN") if isinstance(settings, dict) else False,
            "gamma_relative_sd_of_blueprint_model_c": m["c_bp"]["prior"]["gamma_relative_sd"],
            "blueprint_pooled_fallbacks": {"b_bp": m["b_bp"]["prior"].get("n_pooled_fallbacks"), "c_bp": m["c_bp"]["prior"].get("n_pooled_fallbacks")},
            "code_revisions_identical": len(revisions) == 1, "git_commits": sorted(str(r) for r in revisions),
            "working_tree_dirty": {a: m[a].get("working_tree_dirty") for a in ARMS},
            "expected_events_checked": expected_events, "expected_participants_checked": expected_participants}


# ----------------------------------------------------------------------------- statistics

def _arm_arrays(frames: Dict[str, pd.DataFrame]):
    ref = frames["c_eb"].sort_values("event_id").reset_index(drop=True)
    out = {}
    for a in ARMS:
        f = frames[a].sort_values("event_id").reset_index(drop=True)
        out[a] = (f["p"].to_numpy(float), f["mean_rise"].to_numpy(float))
    return ref["y"].to_numpy(int), ref["rise"].to_numpy(float), _canonical(ref["participant_id"]).to_numpy(), out


def _metrics(y, rise, p, mean_rise) -> dict:
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    return {"brier": float(np.mean((p - y) ** 2)), "log_loss": float(np.mean(-(y * np.log(pc) + (1 - y) * np.log(1 - pc)))),
            "ece10": float(expected_calibration_error(y, p, 10)[0]), "ece5": float(expected_calibration_error(y, p, 5)[0]),
            "rise_mae_mg_dl": float(np.mean(np.abs(mean_rise - rise)))}


def prior_comparison_report(frames: Dict[str, pd.DataFrame], reports: Dict[str, dict], n_boot: int = 2000, seed: int = 0,
                            expected_events: Optional[int] = None, expected_participants: Optional[int] = None,
                            expected_gamma: Optional[float] = None) -> dict:
    integrity = validate_prior_arms(frames, reports, expected_events, expected_participants, expected_gamma)
    y, rise, pid, arrays = _arm_arrays(frames)
    ids, inv = np.unique(pid, return_inverse=True)
    idx = [np.flatnonzero(inv == k) for k in range(len(ids))]
    point = {a: _metrics(y, rise, *arrays[a]) for a in ARMS}
    est = {name: fn(point) for name, fn in CONTRASTS.items()}
    rng = np.random.default_rng(seed)
    draws = {name: {k: [] for k in METRICS} for name in CONTRASTS}
    for _ in range(n_boot):
        take = np.concatenate([idx[k] for k in rng.integers(0, len(idx), size=len(idx))])
        m = {a: _metrics(y[take], rise[take], arrays[a][0][take], arrays[a][1][take]) for a in ARMS}
        for name, fn in CONTRASTS.items():
            for k, v in fn(m).items():
                draws[name][k].append(v)
    contrasts = {}
    for name in CONTRASTS:
        contrasts[name] = {}
        for k in METRICS:
            v = np.asarray(draws[name][k])
            lo, hi = float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))
            contrasts[name][k] = {"estimate": est[name][k], "ci95": [lo, hi], "ci_excludes_zero": bool(lo > 0 or hi < 0)}
    return {
        "_status": "RESEARCH SENSITIVITY ANALYSIS. Not clinically validated. Differences are second-named minus first-named (blueprint minus empirical Bayes; C minus B); "
                   "negative favours the second-named arm for every metric. Participant-clustered 95% percentile intervals, one common resample for all arms.",
        "integrity": integrity, "bootstrap": {"n_boot": n_boot, "seed": seed, "n_participants_resampled": int(len(ids))},
        "arms": {a: {"model": ARM_MODEL[a], "prior_scheme": ARM_SCHEME[a], **point[a]} for a in ARMS},
        "contrasts": contrasts,
        "c_minus_b_conclusion_depends_on_prior": {
            "brier_interval_status_under_empirical_bayes": contrasts["c_minus_b_under_empirical_bayes"]["brier"]["ci_excludes_zero"],
            "brier_interval_status_under_blueprint": contrasts["c_minus_b_under_blueprint"]["brier"]["ci_excludes_zero"],
            "brier_sign_differs": bool(np.sign(est["c_minus_b_under_empirical_bayes"]["brier"]) != np.sign(est["c_minus_b_under_blueprint"]["brier"])),
            "interval_status_differs": bool(contrasts["c_minus_b_under_empirical_bayes"]["brier"]["ci_excludes_zero"]
                                            != contrasts["c_minus_b_under_blueprint"]["brier"]["ci_excludes_zero"]),
            "note": "descriptive; the formal quantity is the 'change in C-minus-B contrast' row, whose interval, if it contains 0, is inconclusive"},
        "adoption_screen": adoption_screen(contrasts),
        "interpretation_limits": "One fold assignment; a single gamma width per run; no multiplicity adjustment across metrics and contrasts; an interval containing 0 is "
                                 "inconclusive; nothing here says Model C is better than Model B or that either prior is clinically meaningful.",
    }


def adoption_screen(contrasts: dict) -> dict:
    out = {"rule": DECISION_RULE_TEXT}
    ok = True
    for model, name in (("B", "model_b_blueprint_minus_empirical_bayes"), ("C", "model_c_blueprint_minus_empirical_bayes")):
        c = contrasts[name]
        crit = {"brier_interval_entirely_below_zero": bool(c["brier"]["ci95"][1] < 0), "log_loss_interval_entirely_below_zero": bool(c["log_loss"]["ci95"][1] < 0),
                "ece10_interval_not_entirely_above_zero": not bool(c["ece10"]["ci95"][0] > 0)}
        crit["all_met"] = all(crit.values())
        out[f"model_{model.lower()}"] = crit
        ok &= crit["all_met"]
    out["candidate_default_for_human_review"] = bool(ok)
    out["meaning"] = ("Screen met: the researcher may review the blueprint prior as a default candidate; nothing is changed automatically." if ok else
                      "Screen not met: the empirical-Bayes prior stays the default. This does not show the priors are equivalent.")
    return out
