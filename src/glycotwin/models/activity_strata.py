"""Per-participant active-day versus sedentary-day definition (blueprint sections 21-22: "each patient's own active-day meals versus
sedentary-day meals").

DEFINITION (documented in docs/activity_definition.md). The stratifying variable is the same pre-meal activity covariate the models use
(`activity_level`, the 4 h pre-meal mean METs). "Active" and "sedentary" are RELATIVE TO THE PERSON'S OWN usual activity:
  * retrospective analysis stratum (for the evaluation of Models B and C): for each participant, the median `activity_level` over that
    participant's evaluated events; a meal is ACTIVE if its activity is strictly above the median and SEDENTARY otherwise (at or below).
    A participant contributes only if both strata hold at least `min_per_side` events; the rest are `excluded`.
    This stratifier uses the person's whole evaluated period, so it is an ANALYSIS label only: it feeds no forecast and no model.
  * prospective label (for display in the twin state): active if the current activity is strictly above the median of the person's
    PREVIOUS meals' activity, sedentary otherwise, `unknown` until `min_prior` earlier meals exist. Uses past information only.
No absolute METs threshold is used: the blueprint does not give one, and a population threshold would label some people always
active and others never, leaving them out of a within-person comparison.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

ACTIVE, SEDENTARY, EXCLUDED, UNKNOWN = "active", "sedentary", "excluded", "unknown"
DEFAULT_MIN_PER_SIDE = 2
DEFAULT_MIN_PRIOR = 4


def within_participant_strata(participant_ids, activity, min_per_side: int = DEFAULT_MIN_PER_SIDE) -> pd.Series:
    """Retrospective stratum of every event: 'active', 'sedentary' or 'excluded' (index = positional, same order as the input)."""
    df = pd.DataFrame({"pid": pd.Series(participant_ids).astype(str).to_numpy(), "a": np.asarray(activity, dtype=float)})
    if not np.isfinite(df["a"]).all():
        raise ValueError("activity must be finite for every event")
    med = df.groupby("pid")["a"].transform("median")
    label = np.where(df["a"] > med, ACTIVE, SEDENTARY)
    df["label"] = label
    counts = df.groupby(["pid", "label"]).size().unstack(fill_value=0)
    for col in (ACTIVE, SEDENTARY):
        if col not in counts:
            counts[col] = 0
    ok = counts.index[(counts[ACTIVE] >= min_per_side) & (counts[SEDENTARY] >= min_per_side)]
    df.loc[~df["pid"].isin(ok), "label"] = EXCLUDED
    return pd.Series(df["label"].to_numpy(), name="activity_stratum")


def prospective_activity_label(prior_activity: Sequence[float], current: float, min_prior: int = DEFAULT_MIN_PRIOR) -> str:
    """Active / sedentary relative to the median of the person's EARLIER meals' activity; 'unknown' without enough history."""
    prior = np.asarray([x for x in prior_activity if x is not None and np.isfinite(x)], dtype=float)
    if len(prior) < min_prior or current is None or not np.isfinite(current):
        return UNKNOWN
    return ACTIVE if float(current) > float(np.median(prior)) else SEDENTARY
