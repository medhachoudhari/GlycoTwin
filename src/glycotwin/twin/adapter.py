"""Bridge from the event table to the in-memory twin: leakage-safe population-informed initialisation and a validated event feed.

  * `initialize_twin_from_population`: the twin's prior is fitted on a population that EXCLUDES the participant (their own events are
    removed automatically and counted), using exactly the Model B (`carbs_g`) and scale-aware Model C priors of the research pipeline.
  * `prepare_participant_events`: one participant's activity-eligible, time-ordered, validated events ready for `replay_lifecycle`.
Deployment-style initialisation (leave-this-participant-out), not the 5-fold evaluation protocol of the model comparison.
No database, no web framework.
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from glycotwin.models.bayesian import MODEL_B_BLUEPRINT_FEATURES, fit_population_prior
from glycotwin.models.model_c_cv import fit_scale_aware_prior
from glycotwin.twin.replay import validate_replay_events
from glycotwin.twin.state import TwinState, TwinStore

POPULATION_REQUIRED = ["participant_id", "carbs_g", "activity_level", "peak_glucose_rise"]


_FLOATY_INT = re.compile(r"^[1-9][0-9]*\.0+$|^0\.0+$")


def canonical_participant_id(value) -> str:
    """One spelling for a participant identifier, so that 3, 3.0 (an integer column that picked up a NaN) and "3" compare equal.
    Only surrounding whitespace is removed; case is NOT folded (P1 and p1 stay different people)."""
    if isinstance(value, (float, np.floating)) and np.isfinite(value) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    return str(int(float(text))) if _FLOATY_INT.match(text) else text          # "3.0" -> "3"; zero-padded ids such as "03" are left alone


def canonical_ids(series: pd.Series) -> pd.Series:
    """Canonical identifiers for a column; raises if one canonical id would merge DIFFERENT raw spellings (3.0 and "3", "P1" and "P1 "),
    because then it is unclear who is who and a silent merge or a silent miss could leak or drop a person."""
    canon = series.map(canonical_participant_id)
    spellings = pd.DataFrame({"canon": canon, "raw": series.map(str)}).drop_duplicates()
    clash = spellings.groupby("canon")["raw"].nunique()
    if (clash > 1).any():
        raise ValueError(f"{int((clash > 1).sum())} participant identifiers have more than one spelling in the data "
                         f"(for example 3 and 3.0, or trailing whitespace); fix the identifiers before building a prior")
    return canon


def initialize_twin_from_population(store: TwinStore, participant_id: str, population_events: pd.DataFrame,
                                    profile: Optional[dict] = None, allow_unseen_participant: bool = False,
                                    prior_scheme: str = "empirical_bayes", glycaemic_group: Optional[str] = None) -> TwinState:
    """Create the version-0 twin for `participant_id` from a population prior fitted WITHOUT that participant.

    Identifiers are compared in canonical form (3, 3.0 and "3" are the same person), so an integer-versus-string mismatch cannot let
    the participant's own outcomes into their prior. If NONE of the population rows belongs to the participant the call is refused
    (a mismatch is far more likely than a brand-new person); pass `allow_unseen_participant=True` for a genuinely new participant,
    which is recorded in the profile. After exclusion a post-condition re-checks that no remaining row is the participant's.

    prior_scheme: "empirical_bayes" (default; the priors used in the Model B/C research runs) or "blueprint" (the blueprint's section 10 prior:
    stratified population regression for beta, gamma centred at 0 with a wide variance; see models/blueprint_prior.py). `glycaemic_group`
    is only used by the blueprint scheme; the population events then need a `glycaemic_group` column to stratify on."""
    if prior_scheme not in ("empirical_bayes", "blueprint"):
        raise ValueError("prior_scheme must be 'empirical_bayes' or 'blueprint'")
    missing = [c for c in POPULATION_REQUIRED if c not in population_events.columns]
    if missing:
        raise ValueError(f"population events are missing columns: {missing}")
    ids = canonical_ids(population_events["participant_id"])
    target = canonical_participant_id(participant_id)
    own = ids == target
    if int(own.sum()) == 0 and not allow_unseen_participant:
        raise ValueError("the participant has no rows in the population events (identifier mismatch?); nothing was built. "
                         "Pass allow_unseen_participant=True only for a participant who really is new")
    train = population_events[~own.to_numpy()]
    if (ids[~own.to_numpy()] == target).any():
        raise ValueError("internal check failed: the participant's own rows remain in the training population")
    if train["participant_id"].nunique() < 2:
        raise ValueError("need at least two other participants to build a population prior")
    finite = train[["carbs_g", "activity_level", "peak_glucose_rise"]].apply(pd.to_numeric, errors="coerce")
    if not finite.notna().all().all():
        raise ValueError("population events contain missing or non-numeric carbs_g, activity_level or peak_glucose_rise (pass activity-eligible events)")
    meta = dict(profile or {})
    if prior_scheme == "blueprint":
        from glycotwin.models.blueprint_prior import fit_blueprint_prior
        prior_b, prior_c, bdiag = fit_blueprint_prior(train, glycaemic_group=glycaemic_group)
        diag = {"prior_source": prior_c.prior_source}
        meta["prior_scheme"] = "blueprint"
        meta["blueprint_prior"] = {k: bdiag[k] for k in ("group_requested", "group_used", "fallback_reason", "gamma_relative_sd", "beta_prior_mean",
                                                         "beta_prior_sd", "gamma_prior_sd")}
        if glycaemic_group is not None:
            meta.setdefault("glycaemic_group", glycaemic_group)
    else:
        prior_b = fit_population_prior(train, MODEL_B_BLUEPRINT_FEATURES)
        prior_c, diag = fit_scale_aware_prior(train)
        meta["prior_scheme"] = "empirical_bayes"
    meta["population_prior"] = {"n_training_participants": int(train["participant_id"].nunique()), "n_training_events": int(len(train)),
                                "own_events_excluded_from_prior": int(own.sum()), "participant_seen_in_population": bool(own.sum() > 0),
                                "model_c_prior_source": diag["prior_source"]}
    return store.initialize_twin(participant_id, prior_b, prior_c, profile=meta)


def prepare_participant_events(event_table: pd.DataFrame, participant_id: str) -> pd.DataFrame:
    """One participant's core-eligible AND activity-eligible events, validated and time-ordered (same population rule as Model C)."""
    for c in ("participant_id", "eligible_core", "eligible_activity"):
        if c not in event_table.columns:
            raise ValueError(f"event table has no {c} column")
    same = (canonical_ids(event_table["participant_id"]) == canonical_participant_id(participant_id)).to_numpy()
    rows = event_table[same & event_table["eligible_core"].astype(bool).to_numpy() & event_table["eligible_activity"].astype(bool).to_numpy()]
    if rows.empty:
        raise ValueError("no core-eligible, activity-eligible events for this participant")
    return validate_replay_events(rows)
