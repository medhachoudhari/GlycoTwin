"""Model C (blueprint form, rise = (beta_i + gamma_i * activity) * carbs), SYNTHETIC data only: software tests, no real-data claim."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from glycotwin.data.events import build_event_table
from glycotwin.models import model_a_cv as ma
from glycotwin.models import model_b_cv as mb
from glycotwin.models import model_c_cv as mc
from glycotwin.models.bayesian import BayesianLinearState, conjugate_update, forecast_exceeds_180

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"healthy": 15, "pre-diabetes": 16, "t2d": 14}


def cohort():
    g, k = {}, 1
    for name, n in SIZES.items():
        for _ in range(n):
            g[f"CGMacros-{k:03d}"] = name
            k += 1
    return g


def make_events(per=16, seed=4, gamma_sd=0.12, gamma_mean=-0.15, noise=15.0, act_range=(1.0, 3.0), clip=True, beta_mean=0.9):
    """rise = (beta_i + gamma_i * activity) * carbs + noise: the blueprint form with known per-participant truth."""
    rng = np.random.default_rng(seed)
    rows, truth = [], {}
    for pid in cohort():
        beta, gamma = rng.normal(beta_mean, 0.2), rng.normal(gamma_mean, gamma_sd)
        truth[pid] = (beta, gamma)
        for j in range(per):
            c, a, b = rng.uniform(10, 90), rng.uniform(*act_range), rng.normal(105, 12)
            rise = (beta + gamma * a) * c + rng.normal(0, noise)
            rise = max(0.0, rise) if clip else rise                      # clip=False: exactly the Gaussian blueprint model
            rows.append({"participant_id": pid, "event_id": f"{pid}-m{j:03d}",
                         "meal_time": pd.Timestamp("2000-01-01") + pd.Timedelta(hours=6 * j), "carbs_g": c, "baseline_glucose": b,
                         "peak_glucose_rise": rise, "activity_level": a, "label_exceeds_180": int(b + rise >= 180),
                         "eligible_core": True, "eligible_activity": True})
    ev = pd.DataFrame(rows)
    ev.attrs["truth"] = truth
    return ev


@pytest.fixture(scope="module")
def events():
    return make_events()


@pytest.fixture(scope="module")
def folds():
    return ma.make_participant_folds(cohort(), seed=0)


@pytest.fixture(scope="module")
def result(events, folds):
    return mc.cross_validated_sequential(events, folds)


def _train(events, folds, k):
    return events[events["participant_id"].map(folds) != k]


def _one(events, pid="CGMacros-001"):
    return events[events["participant_id"] == pid].copy()


def _prior(events, exclude=("CGMacros-001",)):
    return mc.fit_scale_aware_prior(events[~events["participant_id"].isin(exclude)])[0]


# ------------------------------------------------------------------ independent recomputation of the prior (no repo helpers)

def hand_prior(train, ratio=1e-3):
    """m0 (pooled LS), sigma^2 (pooled within-participant residual variance, dof n_i - 2), Sigma_between with the scale-aware
    effect-space eigenvalue floor, all from training rows only."""
    X = np.column_stack([train["carbs_g"], train["carbs_g"] * train["activity_level"]])
    y = train["peak_glucose_rise"].to_numpy()
    mu = np.linalg.lstsq(X, y, rcond=None)[0]
    rms = np.sqrt((X ** 2).mean(axis=0))
    betas, ssr, dof, samp = [], 0.0, 0, []
    for _, g in train.groupby("participant_id"):
        Xi = np.column_stack([g["carbs_g"], g["carbs_g"] * g["activity_level"]])
        yi = g["peak_glucose_rise"].to_numpy()
        if len(g) <= 2 or np.linalg.matrix_rank(Xi) < 2:
            continue
        b = np.linalg.lstsq(Xi, yi, rcond=None)[0]
        r = yi - Xi @ b
        betas.append(b); ssr += float(r @ r); dof += len(g) - 2; samp.append(np.linalg.inv(Xi.T @ Xi))
    s2 = ssr / dof
    spread = np.cov(np.array(betas), rowvar=False)
    raw = np.mean([s2 * m for m in samp], axis=0)
    raw = spread - raw
    raw = (raw + raw.T) / 2
    D = np.diag(rms)
    vals, vecs = np.linalg.eigh(D @ raw @ D)
    floor = max(ratio * np.trace(D @ spread @ D) / 2, 1e-12)
    eff = (vecs * np.clip(vals, floor, None)) @ vecs.T
    return mu, s2, np.linalg.inv(D) @ eff @ np.linalg.inv(D), raw, spread


# ------------------------------------------------------------------ 1. no intercept, blueprint design

def test_model_c_design_is_blueprint_form_with_no_intercept(events, folds, result):
    assert mc.MODEL_C_DESIGN == ["carbs_g", "carbs_x_activity"]
    prior = _prior(events)
    assert prior.feature_names == mc.MODEL_C_DESIGN and prior.mean.shape == (2,) and prior.covariance.shape == (2, 2)
    assert prior.activity_center == 0.0                                                    # un-centred (B1)
    with pytest.raises(ValueError):
        prior.coefficient("intercept")
    with pytest.raises(ValueError, match="no intercept"):
        mc.sequential_participant(_one(events), BayesianLinearState(["intercept", "carbs_g", "carbs_x_activity"], np.zeros(3), np.eye(3), 100.0))
    centred = BayesianLinearState(mc.MODEL_C_DESIGN, np.zeros(2), np.eye(2), 100.0, activity_center=2.0)
    with pytest.raises(ValueError, match="un-centred"):
        mc.sequential_participant(_one(events), centred)
    with pytest.raises(ValueError, match="design must be"):
        mc.fit_scale_aware_prior(events, ["intercept", "carbs_g", "carbs_x_activity"])
    X = np.column_stack([events["carbs_g"], events["carbs_g"] * events["activity_level"]])
    from glycotwin.models.bayesian import build_design_matrix
    np.testing.assert_allclose(build_design_matrix(events, mc.MODEL_C_DESIGN, 0.0), X)    # columns are exactly [c, c*a]
    traj = next(iter(result[1].values()))["trajectory"]
    assert all("intercept" in "" or "intercept_mean" not in t for t in traj)
    src = (ROOT / "src" / "glycotwin" / "models" / "model_c_cv.py").read_text(encoding="utf-8")
    assert "MODEL_B_FEATURES" not in src and 'coefficient("intercept")' not in src and "MODEL_C_FEATURES" not in src


def test_zero_carbohydrate_gives_zero_predicted_rise_and_only_noise_uncertainty(events):
    prior = _prior(events)
    row = _one(events).iloc[0].copy()
    row["carbs_g"] = 0.0
    f = forecast_exceeds_180(prior, row, 150.0)
    sigma = float(np.sqrt(prior.noise_variance))
    assert f.mean_rise == 0.0 and f.predictive_std == pytest.approx(sigma)
    assert f.probability_exceeds_180 == pytest.approx(norm.cdf((150.0 - 180.0) / sigma))
    row["activity_level"] = 9.0
    assert forecast_exceeds_180(prior, row, 150.0).mean_rise == 0.0                          # no activity main effect either


# ------------------------------------------------------------------ 2. exact two-parameter closed form

def test_two_parameter_closed_form_update_and_prediction(events):
    prior = _prior(events)
    mu, S, s2 = prior.mean.copy(), prior.covariance.copy(), prior.noise_variance
    ev = _one(events).sort_values("meal_time")
    r0 = ev.iloc[0]
    x = np.array([r0["carbs_g"], r0["carbs_g"] * r0["activity_level"]])
    S_post = np.linalg.inv(np.linalg.inv(S) + np.outer(x, x) / s2)
    m_post = S_post @ (np.linalg.inv(S) @ mu + x * r0["peak_glucose_rise"] / s2)
    post = conjugate_update(prior, ev.iloc[[0]])
    np.testing.assert_allclose(post.covariance, S_post, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(post.mean, m_post, rtol=1e-9, atol=1e-12)
    r1 = ev.iloc[1]
    x1 = np.array([r1["carbs_g"], r1["carbs_g"] * r1["activity_level"]])
    p_formula = norm.cdf((r1["baseline_glucose"] + x1 @ m_post - 180.0) / np.sqrt(s2 + x1 @ S_post @ x1))
    recs, _ = mc.sequential_participant(ev, prior)
    assert recs[1]["p"] == pytest.approx(p_formula) and recs[1]["mean_rise"] == pytest.approx(x1 @ m_post)
    assert recs[1]["mean_rise"] == pytest.approx((m_post[0] + m_post[1] * r1["activity_level"]) * r1["carbs_g"])      # (beta + gamma*a)*c
    assert recs[1]["pred_std"] == pytest.approx(np.sqrt(s2 + x1 @ S_post @ x1))


# ------------------------------------------------------------------ 3. beta/gamma posterior update

def test_beta_and_gamma_posteriors_move_in_the_direction_the_data_demand():
    prior = BayesianLinearState(mc.MODEL_C_DESIGN, np.array([0.9, 0.0]), np.diag([0.04, 0.01]), 100.0, activity_center=0.0)
    row = pd.DataFrame({"carbs_g": [60.0], "activity_level": [3.0], "peak_glucose_rise": [60.0 * (0.9 + 0.0 * 3) + 40.0]})   # +40 above prediction at high activity
    post = conjugate_update(prior, row)
    assert post.mean[1] > 0 and post.mean[0] > 0.9                                         # both coefficients absorb the surprise
    assert post.covariance[0, 0] < 0.04 and post.covariance[1, 1] < 0.01
    assert post.covariance[0, 1] < 0                                                        # one observation couples them: more beta means less gamma
    low = row.assign(activity_level=0.0)
    post0 = conjugate_update(prior, low)
    assert post0.mean[1] == pytest.approx(0.0) and post0.covariance[1, 1] == pytest.approx(0.01)   # zero activity: gamma unidentified, untouched
    assert post0.mean[0] > 0.9


# ------------------------------------------------------------------ 4. fold prior: independent recomputation (training participants only)

def test_fold_prior_matches_an_independent_computation_on_training_participants_only(events, folds, result):
    priors = result[2]
    for k in range(5):
        train = _train(events, folds, k)
        assert not set(train["participant_id"]) & {p for p, f in folds.items() if f == k}
        mu, s2, cov, raw, spread = hand_prior(train)
        state, diag = mc.fit_scale_aware_prior(train)
        np.testing.assert_allclose(state.mean, mu, rtol=1e-10)
        np.testing.assert_allclose(state.covariance, cov, rtol=1e-8, atol=1e-14)
        assert state.noise_variance == pytest.approx(s2, rel=1e-10) and state.activity_center == 0.0
        assert diag == priors[k]
        assert diag["beta_population_mean"] == pytest.approx(mu[0]) and diag["gamma_population_mean"] == pytest.approx(mu[1])
        assert diag["beta_between_participant_sd"] ** 2 == pytest.approx(cov[0, 0], rel=1e-8)
        assert diag["gamma_between_participant_sd"] ** 2 == pytest.approx(cov[1, 1], rel=1e-8)
        assert diag["noise_sd"] ** 2 == pytest.approx(s2, rel=1e-10)
        assert diag["raw_between_participant_variance_before_regularization"]["carbs_x_activity"] == pytest.approx(raw[1, 1], rel=1e-8)
        assert diag["n_training_participants"] == 45 - sum(1 for f in folds.values() if f == k)
        assert diag["prior_source"] == mc.PRIOR_SOURCE_SCALE_AWARE
        assert not np.allclose(hand_prior(events)[0], mu)                                   # all-participant fit differs: the check can see leakage


# ------------------------------------------------------------------ 5. validation perturbation invariance

def test_validation_participants_cannot_affect_the_fold_prior_in_any_way(events, folds, result):
    priors = result[2]
    for k in range(5):
        mod = events.copy()
        v = mod["participant_id"].map(folds) == k
        mod.loc[v, "peak_glucose_rise"] = mod.loc[v, "peak_glucose_rise"] * 7 + 300           # rises
        mod.loc[v, "carbs_g"] = mod.loc[v, "carbs_g"] * 0.1 + 1                               # carbs
        mod.loc[v, "activity_level"] = mod.loc[v, "activity_level"] * 40 + 5                  # activity (the prior's activity-related quantities)
        mod.loc[v, "baseline_glucose"] = mod.loc[v, "baseline_glucose"] + 60                  # baselines
        mod["label_exceeds_180"] = (mod["baseline_glucose"] + mod["peak_glucose_rise"] >= 180).astype(int)
        extra = mod[v].copy()
        extra["event_id"] = extra["event_id"] + "x"
        extra["meal_time"] = extra["meal_time"] + pd.Timedelta(days=30)
        mod = pd.concat([mod, extra], ignore_index=True)
        s0, d0 = mc.fit_scale_aware_prior(_train(events, folds, k))
        s1, d1 = mc.fit_scale_aware_prior(_train(mod, folds, k))
        np.testing.assert_array_equal(s0.mean, s1.mean)                                       # m0
        np.testing.assert_array_equal(s0.covariance, s1.covariance)                           # Sigma
        assert s0.noise_variance == s1.noise_variance                                         # sigma^2
        assert d0 == d1                                                                       # incl. effect scales and spread diagnostics
        _, _, pk = mc.cross_validated_sequential(mod, folds)
        assert pk[k] == priors[k], k
        for j in range(5):
            if j != k:
                assert pk[j] != priors[j], (k, j)                                             # those participants ARE training data elsewhere


# ------------------------------------------------------------------ 6. activity-unit equivariance of the scale-aware regularisation

@pytest.mark.parametrize("scale", [0.1, 10.0, 1000.0])
@pytest.mark.parametrize("gamma_sd", [0.12, 0.0])          # 0.0: gamma has no real spread, so the regularisation floor is what sets its prior
def test_rescaling_activity_units_leaves_every_forecast_unchanged(scale, gamma_sd):
    ev = make_events(per=14, seed=9, gamma_sd=gamma_sd)
    folds = ma.make_participant_folds(cohort(), seed=0)
    base, tr0, pr0 = mc.cross_validated_sequential(ev, folds)
    scaled = ev.assign(activity_level=ev["activity_level"] * scale)
    oof, tr1, pr1 = mc.cross_validated_sequential(scaled, folds)
    np.testing.assert_allclose(oof["p"].to_numpy(), base["p"].to_numpy(), rtol=1e-6, atol=1e-10)
    np.testing.assert_allclose(oof["mean_rise"].to_numpy(), base["mean_rise"].to_numpy(), rtol=1e-6, atol=1e-8)
    np.testing.assert_allclose(oof["pred_std"].to_numpy(), base["pred_std"].to_numpy(), rtol=1e-6)
    for k in range(5):
        assert pr1[k]["gamma_population_mean"] == pytest.approx(pr0[k]["gamma_population_mean"] / scale, rel=1e-6)    # gamma carries the units
        assert pr1[k]["gamma_between_participant_sd"] == pytest.approx(pr0[k]["gamma_between_participant_sd"] / scale, rel=1e-5)
        assert pr1[k]["beta_between_participant_sd"] == pytest.approx(pr0[k]["beta_between_participant_sd"], rel=1e-6)
        assert pr1[k]["n_eigenvalues_raised_to_the_floor"] == pr0[k]["n_eigenvalues_raised_to_the_floor"]
    if gamma_sd == 0.0:
        assert any(p["n_eigenvalues_raised_to_the_floor"] >= 1 for p in pr0.values())   # the regularisation was actually active in this case


def test_regularisation_floor_is_defined_in_effect_space(events, folds):
    train = _train(events, folds, 0)
    state, diag = mc.fit_scale_aware_prior(train)
    mu, s2, cov, raw, spread = hand_prior(train)
    rms = np.sqrt(np.mean(np.column_stack([train["carbs_g"], train["carbs_g"] * train["activity_level"]]) ** 2, axis=0))
    D = np.diag(rms)
    assert diag["effect_space_eigenvalue_floor"] == pytest.approx(1e-3 * np.trace(D @ spread @ D) / 2)
    eff_eigs = np.linalg.eigvalsh(D @ state.covariance @ D)
    assert eff_eigs.min() >= diag["effect_space_eigenvalue_floor"] * (1 - 1e-9)             # nothing below the floor in effect space
    assert diag["effect_scale_rms"]["carbs_g"] == pytest.approx(rms[0]) and diag["effect_scale_rms"]["carbs_x_activity"] == pytest.approx(rms[1])


def test_fallback_prior_is_also_scale_aware_and_says_so():
    ev = make_events(per=12, seed=2)
    few = ev[ev["participant_id"].isin(sorted(ev["participant_id"].unique())[:3])]
    s, d = mc.fit_scale_aware_prior(few)
    assert s.prior_source == "diffuse_fallback" and d["n_eigenvalues_raised_to_the_floor"] is None
    s2_, _ = mc.fit_scale_aware_prior(few.assign(activity_level=few["activity_level"] * 50))
    assert s2_.covariance[1, 1] == pytest.approx(s.covariance[1, 1] / 2500, rel=1e-6)       # variance in effect space is constant
    assert s2_.covariance[0, 0] == pytest.approx(s.covariance[0, 0], rel=1e-6)


# ------------------------------------------------------------------ 7. personalisation of gamma

def test_gamma_is_personalised_towards_each_participants_own_value():
    ev = make_events(per=30, seed=11, gamma_sd=0.3, noise=8.0, act_range=(0.5, 4.0), clip=False)
    folds = ma.make_participant_folds(cohort(), seed=0)
    oof, trajs, priors = mc.cross_validated_sequential(ev, folds)
    truth = ev.attrs["truth"]
    ids = sorted(trajs)
    final_g = np.array([trajs[p]["trajectory"][-1]["gamma_mean"] for p in ids])
    true_g = np.array([truth[p][1] for p in ids])
    prior_g = np.array([priors[trajs[p]["fold"]]["gamma_population_mean"] for p in ids])
    assert np.corrcoef(final_g, true_g)[0, 1] > 0.8                                         # individual gammas recovered
    assert (np.abs(final_g - true_g) < np.abs(prior_g - true_g)).mean() > 0.8              # closer than the population mean for most
    assert np.std(final_g, ddof=1) > 0.5 * np.std(true_g, ddof=1)                           # the spread across people is learned
    hi, lo = ids[int(np.argmax(true_g))], ids[int(np.argmin(true_g))]
    assert trajs[hi]["trajectory"][-1]["gamma_mean"] > trajs[lo]["trajectory"][-1]["gamma_mean"] + 0.3
    beta_final = np.array([trajs[p]["trajectory"][-1]["beta_mean"] for p in ids])
    assert np.corrcoef(beta_final, [truth[p][0] for p in ids])[0, 1] > 0.8                 # and beta too


def test_gamma_posterior_uncertainty_only_shrinks_and_never_collapses(events):
    ev, prior = _one(events), _prior(events)
    recs, traj = mc.sequential_participant(ev, prior)
    for key in ("gamma_sd", "beta_sd"):
        sds = [t[key] for t in traj]
        assert all(s > 0 for s in sds) and all(b <= a + 1e-12 for a, b in zip(sds, sds[1:])) and sds[-1] < sds[0]
    assert [t["n_observations"] for t in traj] == list(range(len(ev) + 1))
    noise = float(np.sqrt(prior.noise_variance))
    assert all(r["pred_std"] > noise for r in recs) and all(r["interval90_low"] < r["mean_rise"] < r["interval90_high"] for r in recs)


# ------------------------------------------------------------------ 8. causal ordering

def test_an_events_own_outcome_never_changes_its_own_forecast(events):
    ev, prior = _one(events), _prior(events)
    base, _ = mc.sequential_participant(ev, prior)
    order = ev.sort_values("meal_time")["event_id"].tolist()
    for i in (0, 5, len(ev) - 1):
        mod = ev.copy()
        mod.loc[mod["event_id"] == order[i], "peak_glucose_rise"] += 500.0
        mod.loc[mod["event_id"] == order[i], "label_exceeds_180"] = 1 - mod.loc[mod["event_id"] == order[i], "label_exceeds_180"]
        recs, _ = mc.sequential_participant(mod, prior)
        assert recs[i]["p"] == base[i]["p"] and recs[i]["mean_rise"] == base[i]["mean_rise"]


def test_future_observations_and_inputs_cannot_change_an_earlier_forecast(events):
    ev, prior = _one(events), _prior(events)
    base, _ = mc.sequential_participant(ev, prior)
    order = ev.sort_values("meal_time")["event_id"].tolist()
    mod = ev.copy()
    mod.loc[mod["event_id"].isin(order[6:]), "peak_glucose_rise"] = 900.0
    mod.loc[mod["event_id"].isin(order[7:]), ["carbs_g", "baseline_glucose", "activity_level"]] = [1.0, 300.0, 40.0]
    recs, _ = mc.sequential_participant(mod, prior)
    assert [r["p"] for r in recs[:7]] == [r["p"] for r in base[:7]]
    assert recs[7]["p"] != base[7]["p"]


def test_events_are_processed_in_time_order_and_forecast_before_update(events):
    ev, prior = _one(events), _prior(events)
    recs, traj = mc.sequential_participant(ev, prior)
    shuffled, _ = mc.sequential_participant(ev.sample(frac=1.0, random_state=5), prior)
    renamed, _ = mc.sequential_participant(ev.assign(event_id=[f"z{99 - i:03d}" for i in range(len(ev))]), prior)
    assert [r["p"] for r in recs] == [r["p"] for r in shuffled] == [r["p"] for r in renamed]
    assert [r["n_personal_before"] for r in recs] == list(range(len(ev))) and [r["version_at_forecast"] for r in recs] == list(range(len(ev)))
    assert traj[-1]["n_observations"] == len(ev)


def test_an_event_inside_an_earlier_events_open_window_cannot_use_that_outcome(events):
    ev, prior = _one(events).sort_values("meal_time").head(3).copy(), _prior(events)
    t0 = ev["meal_time"].iloc[0]
    ev["meal_time"] = [t0, t0 + pd.Timedelta(minutes=90), t0 + pd.Timedelta(minutes=120)]
    recs, _ = mc.sequential_participant(ev, prior)
    assert [r["n_personal_before"] for r in recs] == [0, 0, 1]
    mod = ev.copy(); mod.iloc[0, mod.columns.get_loc("peak_glucose_rise")] += 300
    recs_m, _ = mc.sequential_participant(mod, prior)
    assert recs_m[1]["p"] == recs[1]["p"] and recs_m[2]["p"] != recs[2]["p"]


def test_participants_are_isolated_and_start_from_the_training_only_prior(events, folds, result):
    oof, trajs, priors = result
    k = folds["CGMacros-001"]
    other = next(p for p, f in folds.items() if f == k and p != "CGMacros-001")
    mod = events.copy(); mod.loc[mod["participant_id"] == other, "peak_glucose_rise"] *= 3
    oof_m, _, _ = mc.cross_validated_sequential(mod, folds)
    mine = lambda o: o[o["participant_id"] == "CGMacros-001"].set_index("event_id")["p"].sort_index()
    pd.testing.assert_series_equal(mine(oof), mine(oof_m))
    for kk in range(5):
        prior, _ = mc.fit_scale_aware_prior(_train(events, folds, kk))
        for pid in [p for p, f in folds.items() if f == kk][:3]:
            first = oof[oof["participant_id"] == pid].sort_values("order").iloc[0]
            row = events.set_index("event_id").loc[first["event_id"]]
            assert first["n_personal_before"] == 0
            assert first["p"] == pytest.approx(forecast_exceeds_180(prior, row, float(row["baseline_glucose"])).probability_exceeds_180)
            assert trajs[pid]["trajectory"][0]["gamma_mean"] == pytest.approx(prior.mean[1])


def test_labels_are_never_inputs_and_baseline_only_converts_to_a_probability(events, folds, result):
    flipped = events.assign(label_exceeds_180=1 - events["label_exceeds_180"])
    oof_f, _, _ = mc.cross_validated_sequential(flipped, folds)
    np.testing.assert_array_equal(result[0].sort_values("event_id")["p"].to_numpy(), oof_f.sort_values("event_id")["p"].to_numpy())
    ev, prior = _one(events), _prior(events)
    recs, _ = mc.sequential_participant(ev, prior)
    shifted, _ = mc.sequential_participant(ev.assign(baseline_glucose=ev["baseline_glucose"] + 30), prior)
    assert [r["mean_rise"] for r in recs] == [r["mean_rise"] for r in shifted] and all(s["p"] >= r["p"] for r, s in zip(recs, shifted))


# ------------------------------------------------------------------ 9. missing / low-coverage activity

def test_missing_activity_is_refused_not_imputed_and_the_input_is_untouched(events, folds):
    bad = events.copy(); bad.loc[bad.index[3], "activity_level"] = np.nan
    snapshot = bad.copy()
    with pytest.raises(ValueError, match="activity"):
        mc.cross_validated_sequential(bad, folds)
    pd.testing.assert_frame_equal(bad, snapshot)
    with pytest.raises(ValueError, match="missing columns"):
        mc.cross_validated_sequential(events.drop(columns=["activity_level"]), folds)


def test_low_coverage_activity_events_are_excluded_from_model_c_by_the_event_table_rule():
    n = 1500
    t = pd.date_range("2000-01-01", periods=n, freq="1min")
    mets = np.full(n, 1.5)
    mets[:330] = np.nan                                                    # rows 160-399 are the 4 h before the first meal: only 70 of 240 minutes have METs (< 50%)
    mt = [np.nan] * n; cb = [np.nan] * n
    for i in (400, 1000):
        mt[i], cb[i] = "Lunch", 40.0
    df = pd.DataFrame({"Timestamp": t, "Dexcom GL": 100.0, "Libre GL": 100.0, "HR": 70.0, "METs": mets, "Meal Type": mt, "Carbs": cb,
                       "Protein": np.nan, "Fat": np.nan, "Fiber": np.nan, "Calories": np.nan})
    df.loc[500:600, "Libre GL"] = 130.0
    table = build_event_table(df, "CGMacros-001", cgm_col="Libre GL").table
    assert table["eligible_core"].tolist() == [True, True] and table["eligible_activity"].tolist() == [False, True]
    kept = mc.select_activity_eligible(table)
    assert len(kept) == 1 and kept["eligible_activity"].all() and kept["activity_coverage"].iloc[0] >= 0.5
    with pytest.raises(ValueError, match="eligible_activity"):
        mc.select_activity_eligible(table.drop(columns=["eligible_activity"]))


# ------------------------------------------------------------------ 10. nesting: C reduces to B when gamma is pinned to zero

def test_model_c_reduces_to_model_b_when_the_gamma_prior_variance_goes_to_zero(events):
    ev = _one(events)
    m, tau2, s2 = 0.9, 0.05, 150.0
    b_prior = BayesianLinearState(["carbs_g"], np.array([m]), np.array([[tau2]]), s2)
    rb, tb = mb.sequential_participant(ev, b_prior)
    for gvar, tol in ((1e-14, 1e-9), (1e-10, 1e-6)):
        c_prior = BayesianLinearState(mc.MODEL_C_DESIGN, np.array([m, 0.0]), np.diag([tau2, gvar]), s2)
        rc, tc = mc.sequential_participant(ev, c_prior)
        np.testing.assert_allclose([r["p"] for r in rc], [r["p"] for r in rb], atol=tol)
        np.testing.assert_allclose([r["mean_rise"] for r in rc], [r["mean_rise"] for r in rb], atol=tol * 100)
        np.testing.assert_allclose([t["beta_mean"] for t in tc], [t["sens_mean"] for t in tb], atol=tol * 100)
        assert max(abs(t["gamma_mean"]) for t in tc) < 1e-3
    wide = BayesianLinearState(mc.MODEL_C_DESIGN, np.array([m, 0.0]), np.diag([tau2, 0.05]), s2)      # a free gamma is NOT B
    assert [r["p"] for r in mc.sequential_participant(ev, wide)[0]] != [r["p"] for r in rb]


# ------------------------------------------------------------------ 11. folds, coverage, determinism

def test_folds_are_identical_to_models_a_and_b_even_if_a_participant_has_no_activity_eligible_events(events):
    reference = ma.fold_assignment_hash(ma.make_participant_folds(cohort(), seed=0))
    rep, *_ = mc.run_model_c(events, cohort(), seed=0, n_boot=10, n_core_events=len(events))
    assert rep["manifest"]["fold_assignment_sha256"] == reference
    fewer = events[events["participant_id"] != "CGMacros-007"]
    rep2, oof2, *_ = mc.run_model_c(fewer, cohort(), seed=0, n_boot=10, n_core_events=len(events))
    assert rep2["manifest"]["fold_assignment_sha256"] == reference and rep2["data"]["n_participants"] == 44
    assert rep2["data"]["n_events_dropped_for_missing_or_low_coverage_activity"] == len(events) - len(fewer)
    assert "CGMacros-007" not in set(oof2["participant_id"])


def test_every_event_gets_exactly_one_forecast_from_its_own_fold_and_runs_are_deterministic(events, folds, result):
    oof = result[0]
    assert len(oof) == len(events) and oof["event_id"].is_unique and set(oof["event_id"]) == set(events["event_id"])
    assert (oof["participant_id"].map(folds) == oof["fold"]).all() and oof["p"].between(0, 1).all()
    again, _, _ = mc.cross_validated_sequential(events.sample(frac=1.0, random_state=1), folds)
    pd.testing.assert_frame_equal(oof.sort_values("event_id").reset_index(drop=True), again.sort_values("event_id").reset_index(drop=True))


# ------------------------------------------------------------------ 12. report and paired comparison

def test_report_contains_every_requested_quantity_and_no_identifiers(events):
    rep, oof, trajs, folds = mc.run_model_c(events, cohort(), seed=0, n_boot=20, n_core_events=len(events))
    P = rep["personalization"]
    across = P["prior_across_folds"]
    assert set(across) == {"beta_population_mean", "beta_between_participant_sd", "gamma_population_mean", "gamma_between_participant_sd",
                           "beta_gamma_prior_correlation", "noise_sd"}
    for key in ("final_minus_prior_beta", "final_minus_prior_gamma", "final_over_prior_sd_beta", "final_over_prior_sd_gamma",
                "posterior_beta_sd_at_forecast_time", "posterior_gamma_sd_at_forecast_time", "personal_observations_used_at_forecast_time",
                "observations_per_participant", "final_posterior_beta_mean", "final_posterior_gamma_mean"):
        assert P[key]["n"] > 0, key
    assert P["participants_with_both_coefficients_identifiable_from_own_events"] == 45 and P["participants_total"] == 45
    assert "no additional minimum" in P["identifiable_rule"] and P["forecasts_made_from_prior_only"] == 45
    f0 = P["prior_by_fold"]["0"]
    for key in ("raw_between_participant_variance_before_regularization", "gamma_share_of_observed_spread_that_is_sampling_noise",
                "n_participants_usable_for_spread", "n_eigenvalues_raised_to_the_floor", "effect_scale_rms"):
        assert key in f0, key
    assert rep["manifest"]["intercept"] == "none" and rep["manifest"]["design_features"] == ["carbs_g", "carbs_x_activity"]
    assert rep["paired_c_vs_b"].startswith("NOT COMPUTED") and "Not clinically validated" in rep["_status"]
    assert rep["model_c_overall"]["n_events"] == len(events)
    text = json.dumps(rep, default=str)
    for needle in ("CGMacros-", "2000-01-01"):
        assert needle not in text, needle


def test_paired_c_vs_b_needs_identical_events_and_computes_the_difference(events, folds):
    oof_c, _, _ = mc.cross_validated_sequential(events, folds)
    oof_b, _, _ = mb.cross_validated_sequential(events, folds)
    out = mc.compare_c_to_b(oof_c, oof_b, n_boot=40)
    brier = next(c for c in out["comparisons"] if c["metric"] == "brier")
    manual = float(((oof_c.set_index("event_id")["p"] - oof_c.set_index("event_id")["y"]) ** 2).mean()
                   - ((oof_b.set_index("event_id")["p"] - oof_b.set_index("event_id")["y"]) ** 2).mean())
    assert brier["estimate"] == pytest.approx(manual) and brier["n_events"] == len(events) and brier["n_participants"] == 45
    with pytest.raises(ValueError, match="same events"):
        mc.compare_c_to_b(oof_c.iloc[1:], oof_b)
    fz = mc.compare_c_to_frozen_prior(oof_c, n_boot=30)
    assert [c["metric"] for c in fz["comparisons"]] == ["brier", "log_loss", "mae_rise"]


def test_c_beats_b_when_the_activity_interaction_exists_and_not_by_much_when_it_does_not():
    folds = ma.make_participant_folds(cohort(), seed=0)
    out, prevalence = {}, {}
    for name, beta_mean, gm, gsd in (("present", 2.4, -0.5, 0.1), ("absent", 1.4, 0.0, 0.0)):
        ev = make_events(per=24, seed=21, gamma_sd=gsd, gamma_mean=gm, beta_mean=beta_mean, noise=10.0, clip=False)
        prevalence[name] = ev["label_exceeds_180"].mean()
        c, _, _ = mc.cross_validated_sequential(ev, folds)
        b, _, _ = mb.cross_validated_sequential(ev, folds)
        out[name] = mc.compare_c_to_b(c, b, n_boot=200)["comparisons"][0]
    assert all(0.15 < v < 0.85 for v in prevalence.values()), prevalence                    # both scenarios have real positives and negatives
    assert out["present"]["estimate"] < 0 and out["present"]["ci_high"] < 0                 # simulated effect is detected
    assert out["absent"]["estimate"] < 0.01                                                 # no meaningful harm when gamma is null


# ------------------------------------------------------------------ 13. script and legacy-alignment flags

def _script():
    spec = importlib.util.spec_from_file_location("run_model_c", ROOT / "scripts" / "run_model_c.py")
    mod = importlib.util.module_from_spec(spec); sys.modules["run_model_c"] = mod; spec.loader.exec_module(mod)
    return mod


def test_script_end_to_end_activity_eligible_population_aggregate_only_read_only(tmp_path, capsys):
    rmc = _script()
    root = tmp_path / "ds"; root.mkdir()
    g = cohort()
    a1c = {"healthy": 5.2, "pre-diabetes": 6.0, "t2d": 7.1}
    pd.DataFrame({"subject": [int(p[-3:]) for p in g], "A1c PDL (Lab)": [a1c[v] for v in g.values()]}).to_csv(root / "bio.csv", index=False)
    ev = make_events(per=10)
    ev.loc[ev.index[:7], "eligible_activity"] = False                           # core-eligible but without usable activity
    ev.loc[ev.index[7:9], "eligible_core"] = False                              # not core-eligible at all
    ev.loc[ev.index[3], "activity_level"] = np.nan                               # (already inside the activity-ineligible rows)
    table = tmp_path / "event_table_Libre_GL.csv"; ev.to_csv(table, index=False)
    before = hashlib.sha256(table.read_bytes()).hexdigest(), hashlib.sha256((root / "bio.csv").read_bytes()).hexdigest()
    out = tmp_path / "out"
    assert rmc.main(["--data-root", str(root), "--event-table", str(table), "--n-boot", "10", "--out-dir", str(out)]) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)
    expected = int((ev["eligible_core"] & ev["eligible_activity"]).sum())
    assert rep["data"]["n_events"] == expected and rep["data"]["n_core_events_before_activity_eligibility"] == int(ev["eligible_core"].sum())
    assert rep["data"]["n_events_dropped_for_missing_or_low_coverage_activity"] == int(ev["eligible_core"].sum()) - expected
    for needle in ("CGMacros-", "2000-01-01", str(root)):
        assert needle not in text, needle
    assert (out / "model_c_trajectories_Libre_GL.json").exists() and (out / "model_c_sequential_forecasts_Libre_GL.csv").exists()
    assert before == (hashlib.sha256(table.read_bytes()).hexdigest(), hashlib.sha256((root / "bio.csv").read_bytes()).hexdigest())
    assert rmc.main(["--data-root", str(root), "--event-table", str(tmp_path / "events.csv")]) == 2


def test_model_b_and_the_legacy_harness_and_twin_store_are_not_modified_or_coupled_to_model_c():
    for f in ("src/glycotwin/models/model_b_cv.py", "scripts/run_model_b.py", "src/glycotwin/models/experiment.py", "src/glycotwin/twin/state.py",
              "src/glycotwin/data/events.py", "scripts/build_event_table.py", "src/glycotwin/models/model_a_cv.py"):
        text = (ROOT / f).read_text(encoding="utf-8")
        assert "model_c_cv" not in text and "scale_aware" not in text and "run_model_c" not in text, f     # (the legacy `model_c` field name is allowed)
    bay = (ROOT / "src" / "glycotwin" / "models" / "bayesian.py").read_text(encoding="utf-8")
    assert "scale_aware" not in bay and 'MODEL_B_BLUEPRINT_FEATURES = ["carbs_g"]' in bay and 'MODEL_B_FEATURES = ["intercept", "carbs_g"]' in bay


# ------------------------------------------------------------------ controls and identifiability rule (added after mutation checks)

def test_the_frozen_prior_control_is_never_updated(events, folds, result):
    oof = result[0]
    for k in range(5):
        prior, _ = mc.fit_scale_aware_prior(_train(events, folds, k))
        for _, r in oof[oof["fold"] == k].head(25).iterrows():
            row = events.set_index("event_id").loc[r["event_id"]]
            f = forecast_exceeds_180(prior, row, float(row["baseline_glucose"]))
            assert r["p_frozen_prior"] == pytest.approx(f.probability_exceeds_180) and r["mean_rise_frozen_prior"] == pytest.approx(f.mean_rise)
    later = oof[oof["n_personal_before"] > 0]
    assert (later["p"] != later["p_frozen_prior"]).any()


def test_identifiability_needs_more_events_than_coefficients_and_a_rank_two_design():
    def part(pid, c, a):
        return pd.DataFrame({"participant_id": pid, "carbs_g": c, "activity_level": a})
    ev = pd.concat([
        part("two_events", [20, 50], [1.0, 2.0]),                       # 2 events, 2 coefficients: not more events than coefficients
        part("constant_activity", [20, 40, 60, 80], [2.0] * 4),         # c*a is proportional to c: rank 1, gamma not separable from beta
        part("identifiable", [20, 40, 60], [1.0, 3.0, 2.0]),            # 3 events, rank 2
        part("zero_carbs", [0, 0, 0, 0], [1.0, 2.0, 3.0, 2.5]),         # no carbohydrate at all: rank 0
    ], ignore_index=True)
    assert mc._identifiable(ev) == {"two_events": False, "constant_activity": False, "identifiable": True, "zero_carbs": False}
