"""Blueprint-form prior (stratified beta, gamma centred at 0). SYNTHETIC data only: these tests check the construction and its
documented decisions, not that the prior is good on real data (it has not been evaluated there)."""
import numpy as np
import pandas as pd
import pytest

from glycotwin.models.bayesian import conjugate_update
from glycotwin.models.blueprint_prior import (BLUEPRINT_PRIOR_SOURCE, GAMMA_RELATIVE_SD, POOLED_SOURCE, fit_blueprint_prior)
from glycotwin.twin import demo as demo_mod
from glycotwin.twin.adapter import initialize_twin_from_population
from glycotwin.twin.replay import replay_lifecycle
from glycotwin.twin.state import TwinStore


def grouped_population(seed=0, n_per_group=8):
    """Three glycaemic groups whose true sensitivities differ clearly (0.6, 1.0, 1.5 mg/dL per g); no activity effect."""
    rng = np.random.default_rng(seed)
    rows = []
    for gi, (g, beta) in enumerate((("healthy", 0.6), ("pre-diabetes", 1.0), ("t2d", 1.5))):
        for k in range(n_per_group):
            pid = f"{g[:2]}{k:02d}"
            b_i = beta + rng.normal(0, 0.1)
            for j in range(20):
                c, a = float(rng.uniform(15, 100)), float(rng.uniform(0.2, 1.0))
                rows.append({"participant_id": pid, "glycaemic_group": g, "carbs_g": c, "activity_level": a,
                             "peak_glucose_rise": b_i * c + float(rng.normal(0, 8))})
    return pd.DataFrame(rows)


def test_beta_mean_is_the_through_origin_regression_within_the_participants_group():
    pop = grouped_population()
    for g, true in (("healthy", 0.6), ("t2d", 1.5)):
        pb, pc, diag = fit_blueprint_prior(pop, glycaemic_group=g)
        d = pop[pop["glycaemic_group"] == g]
        expect = float(d["carbs_g"] @ d["peak_glucose_rise"] / (d["carbs_g"] @ d["carbs_g"]))
        assert pb.mean[0] == pytest.approx(expect) and pc.mean[0] == pytest.approx(expect) and abs(expect - true) < 0.1
        assert diag["group_used"] == g and diag["fallback_reason"] is None and pc.prior_source == BLUEPRINT_PRIOR_SOURCE
        assert diag["n_stratum_participants"] == 8
    healthy, t2d = fit_blueprint_prior(pop, "healthy")[1].mean[0], fit_blueprint_prior(pop, "t2d")[1].mean[0]
    assert t2d > 2 * healthy                                                         # the strata really differ


def test_gamma_prior_is_centred_at_zero_with_the_documented_spread_and_is_independent_of_beta():
    pop = grouped_population()
    _, pc, diag = fit_blueprint_prior(pop, "pre-diabetes")
    assert pc.feature_names == ["carbs_g", "carbs_x_activity"] and pc.mean[1] == 0.0 and pc.activity_center == 0.0
    a_rms = float(np.sqrt(np.mean(pop["activity_level"] ** 2)))
    assert np.sqrt(pc.covariance[1, 1]) == pytest.approx(GAMMA_RELATIVE_SD * abs(pc.mean[0]) / a_rms) == pytest.approx(diag["gamma_prior_sd"])
    assert pc.covariance[0, 1] == 0.0 and pc.covariance[1, 0] == 0.0
    assert diag["gamma_prior_mean"] == 0.0 and diag["activity_rms"] == pytest.approx(a_rms)
    wide = fit_blueprint_prior(pop, "pre-diabetes", gamma_relative_sd=2.0)[1]
    assert np.sqrt(wide.covariance[1, 1]) == pytest.approx(4 * np.sqrt(pc.covariance[1, 1]))


def test_gamma_sd_is_invariant_to_the_units_of_activity():
    pop = grouped_population()
    scaled = pop.assign(activity_level=pop["activity_level"] * 10.0)
    a, b = fit_blueprint_prior(pop, "t2d")[1], fit_blueprint_prior(scaled, "t2d")[1]
    # one prior sd of the activity term at a typical activity is the same number of mg/dL per gram in both units
    rms = lambda d: float(np.sqrt(np.mean(d["activity_level"] ** 2)))
    assert np.sqrt(a.covariance[1, 1]) * rms(pop) == pytest.approx(np.sqrt(b.covariance[1, 1]) * rms(scaled)) == pytest.approx(GAMMA_RELATIVE_SD * a.mean[0])


def test_pooled_fallbacks_are_explicit():
    pop = grouped_population()
    _, pc, diag = fit_blueprint_prior(pop)
    assert pc.prior_source == POOLED_SOURCE and "no glycaemic group" in diag["fallback_reason"] and diag["group_used"] is None
    _, _, d2 = fit_blueprint_prior(pop.drop(columns=["glycaemic_group"]), "t2d")
    assert "no 'glycaemic_group' column" in d2["fallback_reason"]
    small = pop[~((pop["glycaemic_group"] == "t2d") & (pop["participant_id"] > "t203"))]
    _, pc3, d3 = fit_blueprint_prior(small, "t2d")
    assert "only" in d3["fallback_reason"] and pc3.prior_source == POOLED_SOURCE
    unknown = fit_blueprint_prior(pop, "no-such-group")[2]
    assert unknown["group_used"] is None and unknown["fallback_reason"]
    assert fit_blueprint_prior(pop, "t2d")[1].mean[0] != pc.mean[0]                 # stratified differs from pooled


def test_noise_variance_is_the_pooled_within_participant_variance():
    pop = grouped_population(seed=3)
    pb, pc, diag = fit_blueprint_prior(pop, "healthy")
    assert pb.noise_variance == pytest.approx(64.0, rel=0.35) and pc.noise_variance == pytest.approx(64.0, rel=0.35)     # generating sd = 8


def test_input_validation():
    pop = grouped_population()
    with pytest.raises(ValueError, match="missing column"):
        fit_blueprint_prior(pop.drop(columns=["activity_level"]))
    bad = pop.copy(); bad.loc[bad.index[0], "carbs_g"] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        fit_blueprint_prior(bad)
    with pytest.raises(ValueError, match="at least two"):
        fit_blueprint_prior(pop[pop["participant_id"] == "he00"])
    with pytest.raises(ValueError, match="positive"):
        fit_blueprint_prior(pop, gamma_relative_sd=0)
    with pytest.raises(ValueError, match="zero"):
        fit_blueprint_prior(pop.assign(activity_level=0.0))


def test_blueprint_toy_example_behaviour_sedentary_meal_leaves_gamma_untouched_active_meal_moves_it_negative():
    pop = grouped_population()
    _, prior, _ = fit_blueprint_prior(pop, "pre-diabetes")
    sed = pd.DataFrame({"carbs_g": [60.0], "activity_level": [0.0], "peak_glucose_rise": [130.0]})
    post = conjugate_update(prior, sed)
    assert post.mean[1] == pytest.approx(0.0, abs=1e-12) and post.covariance[1, 1] == pytest.approx(prior.covariance[1, 1])    # a = 0 says nothing about gamma
    assert post.mean[0] != prior.mean[0]
    act = pd.DataFrame({"carbs_g": [60.0], "activity_level": [1.0], "peak_glucose_rise": [0.6 * 60.0]})                        # smaller rise when active
    post2 = conjugate_update(post, act)
    assert post2.mean[1] < -0.05 and post2.covariance[1, 1] < post.covariance[1, 1]
    assert post2.covariance[0, 1] != 0.0                                                                                          # beta and gamma become correlated
    assert np.all(np.linalg.eigvalsh(post2.covariance) > 0)


def test_blueprint_prior_in_the_twin_adapter_is_opt_in_and_leaves_the_default_unchanged():
    pop = grouped_population()
    default = initialize_twin_from_population(TwinStore(), "he00", pop)
    assert default.profile["prior_scheme"] == "empirical_bayes" and default.model_c.prior_source != BLUEPRINT_PRIOR_SOURCE
    tw = initialize_twin_from_population(TwinStore(), "he00", pop, prior_scheme="blueprint", glycaemic_group="healthy")
    assert tw.profile["prior_scheme"] == "blueprint" and tw.profile["glycaemic_group"] == "healthy"
    assert tw.profile["blueprint_prior"]["group_used"] == "healthy" and tw.model_c.mean[1] == 0.0 and tw.model_b.feature_names == ["carbs_g"]
    with pytest.raises(ValueError, match="prior_scheme"):
        initialize_twin_from_population(TwinStore(), "he00", pop, prior_scheme="made-up")


def test_blueprint_prior_excludes_the_participants_own_outcomes():
    pop = grouped_population()
    other = pop.copy()
    m = other["participant_id"] == "he00"
    other.loc[m, "peak_glucose_rise"] = other.loc[m, "peak_glucose_rise"] * 9 + 700
    a = initialize_twin_from_population(TwinStore(), "he00", pop, prior_scheme="blueprint", glycaemic_group="healthy")
    b = initialize_twin_from_population(TwinStore(), "he00", other, prior_scheme="blueprint", glycaemic_group="healthy")
    assert np.array_equal(a.model_c.mean, b.model_c.mean) and np.array_equal(a.model_c.covariance, b.model_c.covariance)
    assert a.model_b.noise_variance == b.model_b.noise_variance


def test_blueprint_prior_twin_runs_the_full_lifecycle_and_the_posterior_narrows():
    pop = demo_mod.demo_population(0).assign(glycaemic_group="prediabetes")
    store = TwinStore()
    initialize_twin_from_population(store, "p000", pop, prior_scheme="blueprint", glycaemic_group="prediabetes", allow_unseen_participant=False)
    ev = pop[pop["participant_id"] == "p000"].head(8).assign(label_exceeds_180=lambda d: ((d["baseline_glucose"] + d["peak_glucose_rise"]) >= 180).astype(int))
    log = replay_lifecycle(store, "p000", ev)
    assert sum(s["action"].startswith("reconcile") for s in log) == 8
    first, last = store.twin_history("p000")[0], store.current_twin("p000")
    assert last.model_c.covariance[0, 0] < first.model_c.covariance[0, 0] and last.model_c.covariance[1, 1] <= first.model_c.covariance[1, 1]


def test_blueprint_part10_toy_example_numbers():
    """Blueprint section 10 numerical example: prior beta = 2.0, gamma = 0 (wide); the text gives approximate results.
    Illustrative prior sds (beta 0.5, gamma 1.0) and noise sd 10 are chosen by us; the blueprint states none."""
    from glycotwin.models.bayesian import BayesianLinearState
    st = BayesianLinearState(["carbs_g", "carbs_x_activity"], np.array([2.0, 0.0]), np.diag([0.25, 1.0]), 100.0)

    def step(s, c, a, y):
        return conjugate_update(s, pd.DataFrame({"carbs_g": [c], "activity_level": [a], "peak_glucose_rise": [y]}))
    s1 = step(st, 60, 0, 130)
    assert s1.mean[0] == pytest.approx(2.15, abs=0.005)                    # "moves from 2.0 toward about 2.15 (130/60 ~ 2.17, pulled partway to the prior)"
    assert s1.mean[1] == 0.0                                               # "gamma barely moves since a = 0"
    s2 = step(s1, 60, 1, 90)
    assert abs(s2.mean[0] - 2.15) < 0.05                                   # "beta stays near 2.15"
    assert -0.75 < s2.mean[1] < -0.5                                       # "gamma moves negative ... about 0.65 lower than beta alone predicts"
    s3 = step(s2, 40, 0, 92)
    assert 2.1 < s3.mean[0] < 2.3                                          # "beta refines further toward about 2.2"
    sds = [np.sqrt(s.covariance[0, 0]) for s in (st, s1, s2, s3)]
    assert sds[0] > sds[1] > sds[3] and sds[3] < sds[1]                    # uncertainty on beta visibly narrower than after meal 1
    assert s3.mean[1] < -0.5                                               # "gamma has started to show a real negative trend"
