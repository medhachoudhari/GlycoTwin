"""Mathematical-property tests for the closed-form Bayesian layer (synthetic data only)."""
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from synthetic import make_hierarchical_meals, make_meals, personalization_experiment
from glycotwin.models.bayesian import (
    MODEL_B_FEATURES, MODEL_C_FEATURES, PRIOR_SOURCE_DIFFUSE, PRIOR_SOURCE_HIERARCHICAL,
    BayesianLinearState, build_design_matrix, conjugate_update, fit_population_prior,
    forecast_exceeds_180)
from glycotwin.models.evaluation import evaluate_predictions


# ---------- the update itself ----------

def test_conjugate_update_matches_manual_formula():
    prior = BayesianLinearState(["intercept", "carbs_g"], [0.0, 1.0], np.eye(2) * 4.0, 2.0)
    df = pd.DataFrame({"carbs_g": [10.0, 20.0], "peak_glucose_rise": [15.0, 30.0]})
    X = np.array([[1, 10.0], [1, 20.0]]); y = df["peak_glucose_rise"].to_numpy()
    P0 = np.linalg.inv(prior.covariance)
    cov = np.linalg.inv(P0 + X.T @ X / 2.0)
    np.testing.assert_allclose(conjugate_update(prior, df).mean, cov @ (P0 @ prior.mean + X.T @ y / 2.0))
    np.testing.assert_allclose(conjugate_update(prior, df).covariance, cov)


def test_update_equals_ridge_posterior_mode():
    """With a Normal prior the posterior mean is the ridge/MAP solution - an independent
    derivation of the same quantity (penalised least squares)."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"carbs_g": rng.uniform(10, 100, 15)})
    df["peak_glucose_rise"] = 3 + 0.5 * df.carbs_g + rng.normal(0, 4, 15)
    prior = BayesianLinearState(["intercept", "carbs_g"], [1.0, 0.2], np.diag([9.0, 0.25]), 16.0)
    X = build_design_matrix(df, prior.feature_names); y = df.peak_glucose_rise.to_numpy()
    P0 = np.linalg.inv(prior.covariance)
    ridge = np.linalg.solve(X.T @ X + 16.0 * P0, X.T @ y + 16.0 * P0 @ prior.mean)
    np.testing.assert_allclose(conjugate_update(prior, df).mean, ridge)


def test_sequential_updates_equal_batch_update_and_are_order_independent():
    df = make_hierarchical_meals(8, 12, seed=1)
    own = df[df.participant_id == "p000"]
    prior = fit_population_prior(df, MODEL_C_FEATURES, exclude_participants=("p000",))
    batch = conjugate_update(prior, own)
    seq = prior
    for i in range(len(own)):
        seq = conjugate_update(seq, own.iloc[[i]])
    shuffled = prior
    for i in np.random.default_rng(0).permutation(len(own)):
        shuffled = conjugate_update(shuffled, own.iloc[[i]])
    for other in (seq, shuffled):
        np.testing.assert_allclose(other.mean, batch.mean, rtol=1e-7, atol=1e-9)
        np.testing.assert_allclose(other.covariance, batch.covariance, rtol=1e-7, atol=1e-9)
    assert seq.version == len(own) and seq.n_observations_used == len(own)


def test_posterior_covariance_is_symmetric_psd_and_shrinks():
    df = make_hierarchical_meals(10, 30, seed=2)
    prior = fit_population_prior(df, MODEL_C_FEATURES, exclude_participants=("p000",))
    post = conjugate_update(prior, df[df.participant_id == "p000"])
    np.testing.assert_allclose(post.covariance, post.covariance.T)
    assert np.linalg.eigvalsh(post.covariance).min() > 0
    assert np.linalg.eigvalsh(prior.covariance - post.covariance).min() > -1e-9  # Loewner shrink


def test_update_rejects_bad_input():
    prior = BayesianLinearState(["intercept"], [0.0], np.eye(1), 1.0)
    with pytest.raises(ValueError):
        BayesianLinearState(["intercept"], [0.0], np.eye(1), 0.0)
    with pytest.raises(ValueError):
        conjugate_update(prior, pd.DataFrame())
    with pytest.raises(ValueError):
        conjugate_update(prior, pd.DataFrame({"carbs_g": [1.0], "peak_glucose_rise": [np.nan]}))
    with pytest.raises(ValueError):
        build_design_matrix(pd.DataFrame({"carbs_g": [1.0]}), ["bogus"])


# ---------- the prior ----------

def test_prior_is_informative_at_version_zero_and_counts_zero_personal_meals():
    df = make_hierarchical_meals(30, 30, seed=3)
    prior = fit_population_prior(df, MODEL_C_FEATURES)
    assert prior.prior_source == PRIOR_SOURCE_HIERARCHICAL
    assert prior.n_observations_used == 0 and prior.version == 0
    lo = forecast_exceeds_180(prior, pd.Series({"carbs_g": 10.0, "activity_level": .5}), 110.0)
    hi = forecast_exceeds_180(prior, pd.Series({"carbs_g": 150.0, "activity_level": .5}), 110.0)
    assert hi.predictive_std < 100          # the diffuse prior gave thousands of mg/dL
    assert hi.probability_exceeds_180 > lo.probability_exceeds_180 + 0.4


def test_prior_falls_back_to_diffuse_and_says_so_with_few_participants():
    df = make_hierarchical_meals(3, 30, seed=3)
    assert fit_population_prior(df, MODEL_B_FEATURES).prior_source == PRIOR_SOURCE_DIFFUSE


def test_prior_recovers_within_participant_noise_better_than_pooled_residual():
    df = make_hierarchical_meals(40, 40, seed=0, noise_sd=12.0)
    prior = fit_population_prior(df, MODEL_C_FEATURES)
    assert prior.noise_variance == pytest.approx(144.0, rel=0.15)
    pooled = fit_population_prior(df, MODEL_B_FEATURES)  # B ignores the interaction -> more resid
    assert pooled.noise_variance > prior.noise_variance


def test_prior_excluding_a_participant_equals_prior_fit_without_them():
    df = make_hierarchical_meals(12, 20, seed=4)
    a = fit_population_prior(df, MODEL_C_FEATURES, exclude_participants=("p003",))
    b = fit_population_prior(df[df.participant_id != "p003"], MODEL_C_FEATURES)
    np.testing.assert_allclose(a.mean, b.mean); np.testing.assert_allclose(a.covariance, b.covariance)
    assert a.noise_variance == b.noise_variance


# ---------- Model C's interaction ----------

def test_activity_centering_is_a_reparametrisation_not_a_different_fit():
    df = make_hierarchical_meals(10, 30, seed=5)
    centered = fit_population_prior(df, MODEL_C_FEATURES)
    c = centered.activity_center
    assert c == pytest.approx(df.activity_level.mean())
    X0 = build_design_matrix(df, MODEL_C_FEATURES, 0.0)
    b0, *_ = np.linalg.lstsq(X0, df.peak_glucose_rise.to_numpy(), rcond=None)
    X1 = build_design_matrix(df, MODEL_C_FEATURES, c)
    np.testing.assert_allclose(X0 @ b0, X1 @ centered.mean, atol=1e-6)      # same fitted values
    # sensitivity at reference activity = sensitivity at 0 + interaction * centre (exact algebra)
    assert centered.mean[1] == pytest.approx(b0[1] + b0[2] * c)
    assert centered.mean[2] == pytest.approx(b0[2])


def test_model_c_estimates_the_activity_interaction_when_present_and_not_when_absent():
    with_g = make_hierarchical_meals(40, 40, seed=6, interaction_mean=-0.35, interaction_sd=0.05)
    without = make_hierarchical_meals(40, 40, seed=6, interaction_mean=0.0, interaction_sd=0.0)
    m1 = fit_population_prior(with_g, MODEL_C_FEATURES).coefficient("carbs_x_activity")[0]
    m0 = fit_population_prior(without, MODEL_C_FEATURES).coefficient("carbs_x_activity")[0]
    assert m1 == pytest.approx(-0.35, abs=0.05)
    assert abs(m0) < 0.05


def test_personalisation_moves_posterior_toward_the_participants_own_slope():
    df = make_hierarchical_meals(30, 40, seed=7, sens_sd=0.3)
    pid = "p001"
    own = df[df.participant_id == pid]
    prior = fit_population_prior(df, MODEL_B_FEATURES, exclude_participants=(pid,))
    post = conjugate_update(prior, own)
    own_ols = np.linalg.lstsq(build_design_matrix(own, MODEL_B_FEATURES), own.peak_glucose_rise, rcond=None)[0]
    pop = prior.coefficient("carbs_g")[0]
    mine = post.coefficient("carbs_g")[0]
    assert abs(mine - own_ols[1]) < abs(pop - own_ols[1])          # moved toward own data...
    assert min(own_ols[1], pop) - 1e-9 <= mine <= max(own_ols[1], pop) + 1e-9  # ...shrunk, not extrapolated


# ---------- forecast probability ----------

def _posterior():
    df = make_hierarchical_meals(20, 25, seed=8)
    return conjugate_update(fit_population_prior(df, MODEL_C_FEATURES, exclude_participants=("p000",)),
                            df[df.participant_id == "p000"].iloc[:6])


def test_forecast_probability_matches_monte_carlo_of_the_stated_target():
    """P(baseline + rise > 180) must equal the simulated frequency under beta~N(mean,cov),
    eps~N(0,noise_var): the closed form really is the stated event's probability."""
    st = _posterior(); rng = np.random.default_rng(0)
    row = pd.Series({"carbs_g": 80.0, "activity_level": 0.3}); baseline = 112.0
    f = forecast_exceeds_180(st, row, baseline)
    x = build_design_matrix(row.to_frame().T, st.feature_names, st.activity_center)[0]
    n = 400_000
    betas = rng.multivariate_normal(st.mean, st.covariance, n)
    rise = betas @ x + rng.normal(0, np.sqrt(st.noise_variance), n)
    assert f.probability_exceeds_180 == pytest.approx(np.mean(baseline + rise > 180), abs=0.005)
    lo, hi = f.interval_90
    assert np.mean((rise >= lo) & (rise <= hi)) == pytest.approx(0.90, abs=0.005)


def test_forecast_is_one_half_when_expected_peak_sits_on_the_threshold():
    st = _posterior(); row = pd.Series({"carbs_g": 60.0, "activity_level": 0.5})
    mean_rise = forecast_exceeds_180(st, row, 100.0).mean_rise
    assert forecast_exceeds_180(st, row, 180.0 - mean_rise).probability_exceeds_180 == pytest.approx(0.5)


def test_forecast_is_monotone_in_baseline_and_bounded():
    st = _posterior(); row = pd.Series({"carbs_g": 60.0, "activity_level": 0.5})
    ps = [forecast_exceeds_180(st, row, b).probability_exceeds_180 for b in range(60, 200, 10)]
    assert all(0 <= p <= 1 for p in ps) and ps == sorted(ps)


# ---------- end-to-end calibration (only valid under correct specification) ----------

def test_leave_one_participant_out_forecasts_are_calibrated_when_model_is_correctly_specified():
    df = make_hierarchical_meals(40, 40, seed=0)
    res = personalization_experiment(df, n_train=15, n_test_participants=12)
    for model, g in res.groupby("model"):
        assert g.covered.mean() == pytest.approx(0.90, abs=0.05), model
        assert evaluate_predictions(g.y, g.p).expected_calibration_error < 0.08, model


def test_activity_term_helps_when_interaction_exists_and_does_not_hurt_much_when_absent():
    """The experiment machinery can detect the effect it is built to detect, and does not
    invent one: this is a statement about the code on synthetic data, not about CGMacros."""
    def brier(df, m):
        g = personalization_experiment(df, 15, 12).query("model == @m")
        return evaluate_predictions(g.y, g.p).brier_score
    present = make_hierarchical_meals(40, 40, seed=0, interaction_mean=-0.35)
    absent = make_hierarchical_meals(40, 40, seed=0, interaction_mean=0.0, interaction_sd=0.0)
    assert brier(present, "C") < brier(present, "B") - 0.005
    assert brier(absent, "C") - brier(absent, "B") < 0.01
