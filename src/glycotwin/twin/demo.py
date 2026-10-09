"""Reproducible, clearly labelled SYNTHETIC demonstration of the twin lifecycle (forecast -> observe -> reconcile -> update).

Everything here is simulated: a simulated population supplies the priors and one simulated participant supplies the meals.
It is NOT CGMacros data, contains no real person's measurements, and its numbers are not research results; it only shows
what the machinery does with valid inputs. The generating truth of the simulated participant is stated because it is simulated.
Blueprint form throughout: rise = (beta + gamma * activity) * carbs, no intercept, un-centred activity.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from glycotwin.models.bayesian import MODEL_B_BLUEPRINT_FEATURES, fit_population_prior
from glycotwin.models.model_c_cv import fit_scale_aware_prior
from glycotwin.models.simulation import make_hierarchical_meals
from glycotwin.twin.insight import (explain_forecast, hit_rate_trend, parameter_history, posterior_convergence, reconciliation_report, twin_insight, what_if)
from glycotwin.twin.state_view import twin_state_view
from glycotwin.twin.replay import replay_lifecycle
from glycotwin.twin.state import TwinStore

DEMO_PARTICIPANT_ID = "DEMO-SYNTHETIC-001"
DEMO_BANNER = "SYNTHETIC DEMONSTRATION: simulated population and simulated participant; NOT CGMacros data; not a research result."
DEMO_TRUTH = {"beta": 1.1, "gamma": -0.35, "noise_sd": 12.0}        # generating values of the simulated participant (known only because simulated)
DEMO_REFERENCE_ACTIVITY = 0.5


def demo_population(seed: int = 0) -> pd.DataFrame:
    """Simulated population in the blueprint form (no intercept, un-centred activity in [0, 1])."""
    return make_hierarchical_meals(n_participants=30, n_meals=24, seed=seed, sens_mean=0.9, sens_sd=0.2, interaction_mean=-0.3,
                                   interaction_sd=0.1, intercept=0.0, noise_sd=DEMO_TRUTH["noise_sd"], activity_center=0.0)


def demo_events(seed: int = 0, n_events: int = 8) -> pd.DataFrame:
    """Valid example events for the simulated participant, spaced 6 h apart (outcome windows never overlap)."""
    rng = np.random.default_rng(seed + 1000)
    rows = []
    for j in range(n_events):
        carbs, act, base = float(rng.uniform(20, 110)), float(rng.uniform(0.0, 1.0)), float(rng.uniform(95, 125))
        rise = (DEMO_TRUTH["beta"] + DEMO_TRUTH["gamma"] * act) * carbs + float(rng.normal(0, DEMO_TRUTH["noise_sd"]))
        if abs(base + rise - 180.0) < 1e-3:                      # keep clear of the label's float tolerance
            rise += 0.01
        rows.append({"event_id": f"{DEMO_PARTICIPANT_ID}-m{j:03d}", "meal_time": pd.Timestamp("2000-01-01 08:00") + pd.Timedelta(hours=6 * j),
                     "carbs_g": carbs, "activity_level": act, "baseline_glucose": base, "peak_glucose_rise": rise,
                     "label_exceeds_180": int(base + rise >= 180.0)})
    return pd.DataFrame(rows)


def build_demo_store(seed: int = 0) -> TwinStore:
    pop = demo_population(seed)
    store = TwinStore()
    prior_b = fit_population_prior(pop, MODEL_B_BLUEPRINT_FEATURES)
    prior_c, _ = fit_scale_aware_prior(pop)
    store.initialize_twin(DEMO_PARTICIPANT_ID, prior_b, prior_c)
    return store


def run_demo(seed: int = 0, n_events: int = 8, reference_activity: float = DEMO_REFERENCE_ACTIVITY, what_if_scenarios: Optional[list] = None) -> dict:
    """The whole demonstration: initial insight, replayed lifecycle, final insight, parameter history and a what-if."""
    store = build_demo_store(seed)
    events = demo_events(seed, n_events)
    insight_before = twin_insight(store, DEMO_PARTICIPANT_ID, reference_activity)
    log = replay_lifecycle(store, DEMO_PARTICIPANT_ID, events)
    insight_after = twin_insight(store, DEMO_PARTICIPANT_ID, reference_activity)
    scenarios = what_if_scenarios or [
        {"label": "reference meal: 60 g carbohydrate, low activity", "carbs_g": 60.0, "activity_level": 0.1},
        {"label": "same meal after higher activity", "carbs_g": 60.0, "activity_level": 0.9},
        {"label": "larger meal: 90 g carbohydrate, low activity", "carbs_g": 90.0, "activity_level": 0.1}]
    ranges = {"carbs_g": (float(events["carbs_g"].min()), float(events["carbs_g"].max())),
              "activity_level": (float(events["activity_level"].min()), float(events["activity_level"].max()))}
    wi = what_if(store.current_twin(DEMO_PARTICIPANT_ID), scenarios, baseline_glucose=110.0, reference_ranges=ranges)
    explanation = explain_forecast(store.current_twin(DEMO_PARTICIPANT_ID), {"carbs_g": 60.0, "activity_level": 0.3, "baseline_glucose": 110.0})
    return {"banner": DEMO_BANNER, "participant_label": DEMO_PARTICIPANT_ID, "seed": seed, "generating_truth_of_simulated_participant": DEMO_TRUTH,
            "events_are": "SIMULATED", "lifecycle_log": log, "twin_insight_before": insight_before, "twin_insight_after": insight_after,
            "parameter_history": parameter_history(store, DEMO_PARTICIPANT_ID, reference_activity), "what_if": wi,
            "reconciliation": reconciliation_report(store, DEMO_PARTICIPANT_ID), "explanation": explanation,
            "state_view": twin_state_view(store, DEMO_PARTICIPANT_ID, reference_activity),
            "convergence": posterior_convergence(store, DEMO_PARTICIPANT_ID, reference_activity),
            "hit_rate_trend": hit_rate_trend(store, DEMO_PARTICIPANT_ID)}
