"""Synthetic MealEvent generators for SOFTWARE TESTS ONLY.

Nothing here is real or realistic clinical data and must never be presented as a
research result. Values come from a made-up generative rule so tests can check that the
code recovers known parameters and is calibrated *when the model is correctly specified*.
"""
import numpy as np
import pandas as pd

from glycotwin.models.bayesian import (
    MODEL_B_FEATURES, MODEL_C_FEATURES, conjugate_update, fit_population_prior,
    forecast_exceeds_180)


def make_meals(n_per_participant=30, participants=("p1", "p2"), seed=0,
               sens=None, interaction=0.0, noise_sd=5.0, spacing_hours=6):
    """Simple fixed-slope generator (no between-participant distribution)."""
    rng = np.random.default_rng(seed)
    sens = sens or {p: 3.0 + i for i, p in enumerate(participants)}
    rows = []
    for p in participants:
        t0 = pd.Timestamp("2000-01-01 08:00")
        for i in range(n_per_participant):
            carbs = rng.uniform(10, 100)
            act = rng.uniform(0, 1)
            base = rng.uniform(90, 130)
            rise = 5 + sens[p] * carbs / 10 + interaction * carbs * act + rng.normal(0, noise_sd)
            rows.append(dict(
                participant_id=p, meal_time=t0 + pd.Timedelta(hours=spacing_hours * i),
                carbs_g=carbs, baseline_glucose=base, activity_level=act,
                peak_glucose_rise=rise, label_exceeds_180=int(base + rise > 180),
                data_quality_flag="ok"))
    return pd.DataFrame(rows)


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
                peak_glucose_rise=rise, label_exceeds_180=int(base + rise > 180),
                data_quality_flag="ok"))
    return pd.DataFrame(rows)


def personalization_experiment(df, n_train=15, n_test_participants=12):
    """Leave-one-participant-out prior, update on each test participant's first n_train
    meals, forecast their remaining meals. Returns one row per (model, held-out meal)."""
    rows = []
    for pid in df["participant_id"].unique()[:n_test_participants]:
        g = df[df.participant_id == pid].sort_values("meal_time")
        train, test = g.iloc[:n_train], g.iloc[n_train:]
        for name, feats in (("B", MODEL_B_FEATURES), ("C", MODEL_C_FEATURES)):
            prior = fit_population_prior(df, feats, exclude_participants=(pid,))
            post = conjugate_update(prior, train)
            for _, r in test.iterrows():
                f = forecast_exceeds_180(post, r, r.baseline_glucose)
                rows.append(dict(
                    model=name, participant_id=pid, y=int(r.label_exceeds_180),
                    p=f.probability_exceeds_180, rise=r.peak_glucose_rise,
                    covered=f.interval_90[0] <= r.peak_glucose_rise <= f.interval_90[1],
                    sq_err=(f.mean_rise - r.peak_glucose_rise) ** 2,
                    activity=r.activity_level))
    return pd.DataFrame(rows)
