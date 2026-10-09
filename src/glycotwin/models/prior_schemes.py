"""Prior-scheme option for the Model B and Model C research runners (S2/S3 sensitivity analyses).

  empirical_bayes (DEFAULT, the primary protocol): one unstratified empirical-Bayes prior per training fold, exactly as in the reported runs.
  blueprint (opt-in): the blueprint's section 10 prior, built PER HELD-OUT PARTICIPANT from that participant's training fold:
      * beta prior mean/variance come from the training participants who share the held-out participant's glycaemic group (the stratum);
      * gamma (Model C only) has prior mean 0 and a prespecified width (GAMMA_WIDTHS, relative sd 0.25 / 0.5 / 1 / 2);
      * noise variance is the pooled within-participant variance of the training fold.
    Details and decisions: models/blueprint_prior.py and docs/blueprint_prior.md.

Leakage rules enforced here (each has a regression test):
  * only training-fold rows are ever passed to the prior; the held-out participant must not appear in them (checked, error otherwise);
  * the held-out participant contributes ONLY their glycaemic group label (a baseline characteristic derived from bio.csv, not an outcome) to pick
    the stratum; every number in the prior comes from eligible training participants;
  * a stratum with too few training participants falls back to the pooled training fold, and every fallback is counted in the manifest.
The model equations, likelihood, sequential update and event protocol are untouched; only the prior's mean and covariance differ.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from glycotwin.models.blueprint_prior import MIN_GROUP_PARTICIPANTS, fit_blueprint_prior

PRIOR_SCHEMES = ("empirical_bayes", "blueprint")
DEFAULT_SCHEME = "empirical_bayes"
GAMMA_WIDTHS = (0.25, 0.5, 1.0, 2.0)            # prespecified relative sd of the gamma prior (blueprint prior, Model C only)
DEFAULT_GAMMA_WIDTH = 0.5


def validate_prior_options(model: str, scheme: str, gamma_relative_sd: Optional[float]) -> Tuple[str, Optional[float]]:
    """Return (scheme, gamma width or None). Refuses anything outside the prespecified options rather than silently ignoring it."""
    if model not in ("B", "C"):
        raise ValueError("model must be 'B' or 'C'")
    if scheme not in PRIOR_SCHEMES:
        raise ValueError(f"prior_scheme must be one of {PRIOR_SCHEMES}; got {scheme!r}")
    if model == "B":
        if gamma_relative_sd is not None:
            raise ValueError("Model B has no gamma; gamma_relative_sd applies to Model C only")
        return scheme, None
    if scheme == "empirical_bayes":
        if gamma_relative_sd is not None:
            raise ValueError("gamma_relative_sd applies only to the blueprint prior; the empirical-Bayes prior has no such option")
        return scheme, None
    width = DEFAULT_GAMMA_WIDTH if gamma_relative_sd is None else float(gamma_relative_sd)
    if width not in GAMMA_WIDTHS:
        raise ValueError(f"gamma_relative_sd must be one of the prespecified widths {GAMMA_WIDTHS}; got {gamma_relative_sd!r}")
    return scheme, width


def with_group(train: pd.DataFrame, group_of: Dict[str, str]) -> pd.DataFrame:
    """Training rows plus a `glycaemic_group` column; refuses if any training participant has no group (no silent drop)."""
    missing = sorted(set(train["participant_id"]) - set(group_of))
    if missing:
        raise ValueError(f"{len(missing)} training participants have no glycaemic group")
    return train.assign(glycaemic_group=train["participant_id"].map(group_of).astype(str))


def blueprint_prior_for_participant(train_with_group: pd.DataFrame, held_out_participant: str, held_out_group: str,
                                    model: str, gamma_relative_sd: Optional[float]):
    """(prior state, summary dict) for ONE held-out participant, from training rows only. `held_out_group` is used only to select the stratum."""
    if held_out_participant in set(train_with_group["participant_id"]):
        raise AssertionError("the held-out participant is present in the training rows used for the prior")
    kwargs = {} if gamma_relative_sd is None else {"gamma_relative_sd": gamma_relative_sd}
    prior_b, prior_c, d = fit_blueprint_prior(train_with_group, glycaemic_group=held_out_group, **kwargs)
    state = prior_b if model == "B" else prior_c
    return state, d


def fold_summary_B(summaries) -> dict:
    """Fold-level aggregate of per-participant blueprint priors, in the key layout of Model B's `prior_by_fold` (empirical-Bayes keys kept)."""
    return {"prior_source": "blueprint (per held-out participant, stratified)", "sens_mean": float(np.mean([s["beta_prior_mean"] for s in summaries])),
            "sens_sd": float(np.mean([s["beta_prior_sd"] for s in summaries])), "noise_sd": float(np.mean([s["noise_sd_model_b"] for s in summaries])),
            "n_training_events": int(np.mean([s["n_stratum_events"] for s in summaries])),
            "n_training_participants": int(np.mean([s["n_stratum_participants"] for s in summaries])),
            "n_participants_priors_averaged": len(summaries), "n_pooled_fallbacks": int(sum(s["group_used"] is None for s in summaries)),
            "note": "mean over this fold's held-out participants of their own stratum priors"}


def fold_summary_C(summaries, width) -> dict:
    return {"prior_source": "blueprint (per held-out participant, stratified)",
            "beta_population_mean": float(np.mean([s["beta_prior_mean"] for s in summaries])),
            "beta_between_participant_sd": float(np.mean([s["beta_prior_sd"] for s in summaries])),
            "gamma_population_mean": 0.0, "gamma_between_participant_sd": float(np.mean([s["gamma_prior_sd"] for s in summaries])),
            "beta_gamma_prior_correlation": 0.0, "noise_sd": float(np.mean([s["noise_sd_model_c"] for s in summaries])),
            "gamma_relative_sd": width, "n_participants_priors_averaged": len(summaries),
            "n_pooled_fallbacks": int(sum(s["group_used"] is None for s in summaries)),
            "note": "mean over this fold's held-out participants; gamma_between_participant_sd here is the prior sd of gamma"}


def participant_prior_record(model: str, d: dict) -> dict:
    """The per-participant prior in the key layout the personalisation summaries read (so they work unchanged)."""
    if model == "B":
        return {"sens_mean": d["beta_prior_mean"], "sens_sd": d["beta_prior_sd"]}
    return {"beta_population_mean": d["beta_prior_mean"], "beta_between_participant_sd": d["beta_prior_sd"],
            "gamma_population_mean": 0.0, "gamma_between_participant_sd": d["gamma_prior_sd"]}


def prior_manifest(model: str, scheme: str, gamma_relative_sd: Optional[float], summaries=None) -> dict:
    out = {"scheme": scheme, "model": model, "gamma_relative_sd": gamma_relative_sd,
           "fitted_on": "training folds only; the held-out participant's outcomes never enter the prior"}
    if scheme == "empirical_bayes":
        out["description"] = "unstratified empirical-Bayes prior per training fold (primary protocol)"
        return out
    out["description"] = ("blueprint section 10 prior per held-out participant: beta from the training participants of the held-out participant's "
                          "glycaemic group (label used only to choose the stratum)" + ("; gamma prior mean 0, prior sd = relative_sd x |beta| / rms(activity)" if model == "C" else ""))
    out["min_group_participants_before_pooled_fallback"] = MIN_GROUP_PARTICIPANTS
    if summaries is not None:
        out["n_participant_priors"] = len(summaries)
        out["n_pooled_fallbacks"] = int(sum(s["group_used"] is None for s in summaries))
        out["fallback_reasons"] = sorted({s["fallback_reason"] for s in summaries if s["fallback_reason"]})
    return out


# ----------------------------------------------------------------------------- manifest helpers (event definition, table fingerprint)

def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_state() -> dict:
    """Code revision and working-tree status, as recorded by the model manifests (same helper)."""
    from glycotwin.models.model_a_cv import _git_state
    return _git_state()


def settings_sidecar_path(table_path) -> Path:
    p = Path(table_path)
    return p.with_name(p.stem + ".settings.json")


def event_table_info(table_path) -> dict:
    """What the manifest records about the event table: file hash and the settings written beside it by build_event_table.py.
    A table built before the sidecar existed has no recorded settings; that is said, not guessed."""
    import json
    side = settings_sidecar_path(table_path)
    info = {"event_table_file_sha256": file_sha256(table_path)}
    if side.exists():
        info["event_table_settings"] = json.loads(side.read_text(encoding="utf-8"))
    else:
        info["event_table_settings"] = {"status": "UNKNOWN: no settings sidecar next to this event table (built before the sidecar existed); "
                                                  "rebuild it with scripts/build_event_table.py to record channel, gap limit and event definition"}
    return info
