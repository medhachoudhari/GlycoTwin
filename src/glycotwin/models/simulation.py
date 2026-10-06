"""Simulated MealEvent tables with a KNOWN generating process.

Used by the tests and by scripts/simulate_power.py. These are SIMULATIONS under stated assumptions:
they say what the code can detect if the world looked like this, and nothing about CGMacros or any
real person. Never present their output as research data.
"""
import numpy as np
import pandas as pd


def make_hierarchical_meals(n_participants=40, n_meals=40, seed=0, sens_mean=0.7, sens_sd=0.2,
                            interaction_mean=-0.35, interaction_sd=0.1, intercept=5.0,
                            noise_sd=12.0, activity_center=0.5, spacing_hours=6):
    """Participants draw (sensitivity, interaction) from a population, then meals follow
    rise = intercept + (s_i + g_i*(activity - center))*carbs + N(0, noise_sd^2).
    This is exactly Model C's generative form, with balanced-ish 180 mg/dL labels."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_participants):
        s = rng.normal(sens_mean, sens_sd)
        g = rng.normal(interaction_mean, interaction_sd)
        t0 = pd.Timestamp("2000-01-01 08:00")
        for j in range(n_meals):
            carbs = rng.uniform(10, 120)
            act = rng.uniform(0, 1)
            base = rng.uniform(95, 125)
            rise = intercept + (s + g * (act - activity_center)) * carbs + rng.normal(0, noise_sd)
            rows.append(dict(
                participant_id=f"p{i:03d}", meal_time=t0 + pd.Timedelta(hours=spacing_hours * j),
                carbs_g=carbs, baseline_glucose=base, activity_level=act,
                peak_glucose_rise=rise, label_exceeds_180=int(base + rise >= 180),
                data_quality_flag="ok"))
    return pd.DataFrame(rows)
