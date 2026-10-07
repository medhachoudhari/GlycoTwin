"""Model B sequential personalised Bayesian evaluation, on SYNTHETIC data only (software tests; no real-data claim)."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.models import model_a_cv as ma
from glycotwin.models import model_b_cv as mb
from glycotwin.models.bayesian import conjugate_update, fit_population_prior, forecast_exceeds_180

B = mb.MODEL_B_DESIGN

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"healthy": 15, "pre-diabetes": 16, "t2d": 14}


def cohort():
    g, k = {}, 1
    for name, n in SIZES.items():
        for _ in range(n):
            g[f"CGMacros-{k:03d}"] = name
            k += 1
    return g


def make_events(per=14, seed=2, gap_hours=6):
    rng = np.random.default_rng(seed)
    rows = []
    for pid, grp in cohort().items():
        sens = rng.normal(0.9, 0.3)
        b0 = {"healthy": 95, "pre-diabetes": 105, "t2d": 125}[grp]
        for j in range(per):
            c, b = rng.uniform(10, 90), rng.normal(b0, 10)
            rise = max(0.0, sens * c + rng.normal(0, 15))          # blueprint form: no intercept
            rows.append({"participant_id": pid, "event_id": f"{pid}-m{j:03d}",
                         "meal_time": pd.Timestamp("2000-01-01") + pd.Timedelta(hours=gap_hours * j),
                         "carbs_g": c, "baseline_glucose": b, "peak_glucose_rise": rise, "label_exceeds_180": int(b + rise >= 180),
                         "activity_level": rng.uniform(0.5, 3.0), "eligible_core": True})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def events():
    return make_events()


@pytest.fixture(scope="module")
def folds():
    return ma.make_participant_folds(cohort(), seed=0)


@pytest.fixture(scope="module")
def result(events, folds):
    return mb.cross_validated_sequential(events, folds)


def _p(oof, event_id, col="p"):
    return float(oof.set_index("event_id").loc[event_id, col])


def _one(events, pid="CGMacros-001"):
    return events[events["participant_id"] == pid].copy()


def _prior(events, exclude=("CGMacros-001",)):
    return fit_population_prior(events[~events["participant_id"].isin(exclude)], B)


# ------------------------------------------------------------------ 1 / 11 chronological order

def test_events_are_processed_in_time_order_not_row_or_id_order(events):
    ev, prior = _one(events), _prior(events)
    recs, _ = mb.sequential_participant(ev, prior)
    shuffled = ev.sample(frac=1.0, random_state=7)
    renamed = ev.assign(event_id=[f"z{99 - i:03d}" for i in range(len(ev))])        # ids sort opposite to time
    recs_s, _ = mb.sequential_participant(shuffled, prior)
    recs_r, _ = mb.sequential_participant(renamed, prior)
    assert [r["p"] for r in recs] == [r["p"] for r in recs_s] == [r["p"] for r in recs_r]
    times = [ev.set_index("event_id").loc[r["event_id"], "meal_time"] for r in recs]
    assert times == sorted(times) and [r["order"] for r in recs] == list(range(len(ev)))


# ------------------------------------------------------------------ 2 / 12 prediction before update

def test_an_events_own_outcome_never_changes_its_own_forecast(events):
    ev, prior = _one(events), _prior(events)
    base, _ = mb.sequential_participant(ev, prior)
    for i in (0, 5, len(ev) - 1):
        mod = ev.copy()
        tgt = ev.sort_values("meal_time").iloc[i]["event_id"]
        mod.loc[mod["event_id"] == tgt, "peak_glucose_rise"] += 500.0
        mod.loc[mod["event_id"] == tgt, "label_exceeds_180"] = 1 - mod.loc[mod["event_id"] == tgt, "label_exceeds_180"]
        recs, _ = mb.sequential_participant(mod, prior)
        assert recs[i]["p"] == base[i]["p"] and recs[i]["mean_rise"] == base[i]["mean_rise"]


def test_the_state_used_for_each_forecast_counts_only_earlier_events(events):
    ev, prior = _one(events), _prior(events)
    recs, traj = mb.sequential_participant(ev, prior)
    assert [r["n_personal_before"] for r in recs] == list(range(len(ev)))           # isolated meals: every earlier one
    assert [r["version_at_forecast"] for r in recs] == list(range(len(ev)))
    assert traj[-1]["n_observations"] == len(ev) and len(traj) == len(ev) + 1        # final state includes all, used for summaries only


def test_an_event_inside_an_earlier_events_open_window_cannot_use_that_outcome(events):
    ev, prior = _one(events).sort_values("meal_time").head(3).copy(), _prior(events)
    t0 = ev["meal_time"].iloc[0]
    ev["meal_time"] = [t0, t0 + pd.Timedelta(minutes=90), t0 + pd.Timedelta(minutes=120)]   # 90 min: window still open; 120: closed
    recs, _ = mb.sequential_participant(ev, prior)
    assert [r["n_personal_before"] for r in recs] == [0, 0, 1]
    mod = ev.copy(); mod.iloc[0, mod.columns.get_loc("peak_glucose_rise")] += 300
    recs_m, _ = mb.sequential_participant(mod, prior)
    assert recs_m[1]["p"] == recs[1]["p"] and recs_m[2]["p"] != recs[2]["p"]


# ------------------------------------------------------------------ 3 future observations / 6 earlier observations are used

def test_future_observations_cannot_change_an_earlier_forecast(events):
    ev, prior = _one(events), _prior(events)
    base, _ = mb.sequential_participant(ev, prior)
    order = ev.sort_values("meal_time")["event_id"].tolist()
    mod = ev.copy()
    mod.loc[mod["event_id"].isin(order[6:]), "peak_glucose_rise"] = 900.0              # outcomes of events 6.. (incl. event 6's own)
    mod.loc[mod["event_id"].isin(order[7:]), ["carbs_g", "baseline_glucose"]] = [1.0, 300.0]   # and every input of events 7..
    recs, _ = mb.sequential_participant(mod, prior)
    assert [r["p"] for r in recs[:7]] == [r["p"] for r in base[:7]]                 # forecasts 0..6 cannot see any of it
    assert recs[7]["p"] != base[7]["p"]


def test_later_validation_events_do_learn_from_earlier_ones(events):
    ev, prior = _one(events), _prior(events)
    base, _ = mb.sequential_participant(ev, prior)
    first = ev.sort_values("meal_time").iloc[0]["event_id"]
    mod = ev.copy(); mod.loc[mod["event_id"] == first, "peak_glucose_rise"] += 150.0
    recs, _ = mb.sequential_participant(mod, prior)
    assert recs[0]["p"] == base[0]["p"] and recs[1]["mean_rise"] > base[1]["mean_rise"]


# ------------------------------------------------------------------ 4 isolation / 5 prior only from training participants

def test_one_validation_participants_data_never_reaches_another(events, folds, result):
    oof = result[0]
    k = folds["CGMacros-001"]
    other = next(p for p, f in folds.items() if f == k and p != "CGMacros-001")
    mod = events.copy(); mod.loc[mod["participant_id"] == other, "peak_glucose_rise"] *= 3
    oof_m, _, _ = mb.cross_validated_sequential(mod, folds)
    mine = lambda o: o[o["participant_id"] == "CGMacros-001"].set_index("event_id")["p"].sort_index()
    pd.testing.assert_series_equal(mine(oof), mine(oof_m))


def test_each_validation_participant_starts_from_the_training_only_prior(events, folds, result):
    oof, trajs, priors = result
    for k in range(5):
        train = events[events["participant_id"].map(folds) != k]
        prior = fit_population_prior(train, B)
        assert priors[k]["sens_mean"] == pytest.approx(prior.coefficient("carbs_g")[0])
        for pid in [p for p, f in folds.items() if f == k][:3]:
            first = oof[oof["participant_id"] == pid].sort_values("order").iloc[0]
            row = events.set_index("event_id").loc[first["event_id"]]
            assert first["n_personal_before"] == 0 and first["version_at_forecast"] == 0
            assert first["p"] == pytest.approx(forecast_exceeds_180(prior, row, float(row["baseline_glucose"])).probability_exceeds_180)
            assert trajs[pid]["trajectory"][0]["sens_mean"] == pytest.approx(prior.coefficient("carbs_g")[0])


def test_the_fold_prior_does_not_depend_on_that_folds_participants(events, folds, result):
    priors = result[2]
    mod = events.copy()
    in0 = mod["participant_id"].map(folds) == 0
    mod.loc[in0, "peak_glucose_rise"] += 80
    _, _, priors_m = mb.cross_validated_sequential(mod, folds)
    assert priors_m[0] == priors[0] and priors_m[1] != priors[1]


# ------------------------------------------------------------------ 7 no activity term

def test_model_b_has_no_activity_term_and_ignores_activity_completely(events, folds, result):
    assert B == ["carbs_g"]
    mod = events.assign(activity_level=np.nan)
    oof_m, _, _ = mb.cross_validated_sequential(mod, folds)
    pd.testing.assert_series_equal(result[0].set_index("event_id")["p"].sort_index(), oof_m.set_index("event_id")["p"].sort_index())
    mod2 = events.assign(activity_level=events["activity_level"] * 100)
    oof_m2, _, _ = mb.cross_validated_sequential(mod2, folds)
    np.testing.assert_array_equal(result[0]["p"].to_numpy(), oof_m2["p"].to_numpy())
    with pytest.raises(ValueError, match="carbs_g"):
        mb.sequential_participant(_one(events), fit_population_prior(events, ["intercept", "carbs_g", "carbs_x_activity"]))


# ------------------------------------------------------------------ 8 uncertainty

def test_posterior_uncertainty_is_kept_and_only_shrinks_with_data(events):
    ev, prior = _one(events), _prior(events)
    recs, traj = mb.sequential_participant(ev, prior)
    sds = [t["sens_sd"] for t in traj]
    assert all(s > 0 for s in sds) and all(b <= a + 1e-12 for a, b in zip(sds, sds[1:]))
    noise_sd = float(np.sqrt(prior.noise_variance))
    assert all(r["pred_std"] > noise_sd for r in recs)                                # parameter uncertainty is added to noise
    assert all(r["interval90_low"] < r["mean_rise"] < r["interval90_high"] for r in recs)


def test_sequential_updates_equal_one_batch_update_of_the_same_earlier_events(events):
    ev, prior = _one(events).sort_values("meal_time"), _prior(events)
    recs, _ = mb.sequential_participant(ev, prior)
    batch = conjugate_update(prior, ev.iloc[:5])
    row = ev.iloc[5]
    assert recs[5]["p"] == pytest.approx(forecast_exceeds_180(batch, row, float(row["baseline_glucose"])).probability_exceeds_180)


# ------------------------------------------------------------------ 9 determinism / 10 no target leakage

def test_runs_are_deterministic(events, folds, result):
    again, _, _ = mb.cross_validated_sequential(events.sample(frac=1.0, random_state=1), folds)
    pd.testing.assert_frame_equal(result[0].sort_values("event_id").reset_index(drop=True), again.sort_values("event_id").reset_index(drop=True))


def test_the_binary_label_is_never_an_input(events, folds, result):
    mod = events.assign(label_exceeds_180=1 - events["label_exceeds_180"])
    oof_m, _, _ = mb.cross_validated_sequential(mod, folds)
    np.testing.assert_array_equal(result[0].sort_values("event_id")["p"].to_numpy(), oof_m.sort_values("event_id")["p"].to_numpy())
    assert (oof_m.sort_values("event_id")["y"].to_numpy() != result[0].sort_values("event_id")["y"].to_numpy()).all()


def test_baseline_enters_only_through_the_threshold_conversion(events):
    ev, prior = _one(events), _prior(events)
    recs, _ = mb.sequential_participant(ev, prior)
    mod = ev.assign(baseline_glucose=ev["baseline_glucose"] + 30)
    recs_m, _ = mb.sequential_participant(mod, prior)
    assert [r["mean_rise"] for r in recs] == [r["mean_rise"] for r in recs_m]       # rise forecast ignores baseline
    assert all(m["p"] >= r["p"] for r, m in zip(recs, recs_m))


def test_missing_required_values_are_refused_not_imputed(events, folds):
    bad = events.copy(); bad.loc[bad.index[0], "carbs_g"] = np.nan
    with pytest.raises(ValueError, match="finite"):
        mb.cross_validated_sequential(bad, folds)
    with pytest.raises(ValueError, match="missing columns"):
        mb.cross_validated_sequential(events.drop(columns=["peak_glucose_rise"]), folds)


# ------------------------------------------------------------------ 13 coverage

def test_every_event_gets_exactly_one_sequential_forecast_from_its_own_fold(events, folds, result):
    oof = result[0]
    assert len(oof) == len(events) and oof["event_id"].is_unique and set(oof["event_id"]) == set(events["event_id"])
    assert (oof["participant_id"].map(folds) == oof["fold"]).all() and oof["p"].between(0, 1).all()


# ------------------------------------------------------------------ 14 comparison, report, personalisation

def test_model_a_and_b_are_compared_on_identical_events_folds_and_conventions(events):
    rep, oof_b, oof_a, trajs, folds = mb.run_model_b(events, cohort(), seed=0, n_boot=40)
    assert set(oof_a["event_id"]) == set(oof_b["event_id"])
    assert rep["manifest"]["fold_assignment_sha256"] == ma.fold_assignment_hash(ma.make_participant_folds(cohort(), seed=0))
    a_direct = ma.metric_bundle(oof_a["y"], oof_a["p"], 0.5, oof_a["fold_train_prevalence"].to_numpy())
    assert rep["model_a_overall_same_folds"]["roc_auc"] == a_direct["roc_auc"]
    b_direct = ma.metric_bundle(oof_b["y"], oof_b["p"])
    assert rep["model_b_overall"]["brier_score"] == pytest.approx(b_direct["brier_score"])
    comps = {(c["model_a"], c["model_b"], c["metric"]): c for c in rep["paired_comparisons"]["comparisons"]}
    c = comps[("B", "A", "brier")]
    manual = float(((oof_b.set_index("event_id")["p"] - oof_b.set_index("event_id")["y"]) ** 2).mean()
                   - ((oof_a.set_index("event_id")["p"] - oof_a.set_index("event_id")["y"]) ** 2).mean())
    assert c["estimate"] == pytest.approx(manual) and c["n_events"] == len(events) and c["n_participants"] == 45
    assert ("B", "B_frozen_prior", "brier") in comps and ("B", "B_frozen_prior", "mae_rise") in comps


def test_paired_comparison_refuses_different_event_sets(events, folds):
    oof_b, _, _ = mb.cross_validated_sequential(events, folds)
    oof_a = ma.cross_validated_predictions(events, folds)
    with pytest.raises(ValueError, match="same events"):
        mb.compare_models(oof_a.iloc[1:], oof_b, n_boot=10)


def test_personalisation_summary_is_aggregate_and_shows_learning(events):
    rep, oof_b, *_ = mb.run_model_b(events, cohort(), seed=0, n_boot=20)
    p = rep["personalization"]
    assert p["observations_per_participant"]["n"] == 45 and p["participants_with_at_least_n_observations"]["10"] == 45
    assert p["final_over_prior_sensitivity_sd"]["max"] < 1.0                          # every posterior narrowed
    assert p["forecasts_made_from_prior_only"] == 45                                   # one first event per participant
    assert p["between_participant_sd_of_final_sensitivity_means"] > 0
    assert set(p["prior_by_fold"]) == {"0", "1", "2", "3", "4"}
    text = json.dumps(rep, default=str)
    for needle in ("CGMacros-", "2000-01-01"):
        assert needle not in text, needle
    assert "Not clinically validated" in rep["_status"]


def test_continuous_metrics_are_consistent(events, folds, result):
    oof = result[0]
    m = mb.continuous_metrics(oof)
    assert m["mae_rise_mg_dl"] == pytest.approx((oof["mean_rise"] - oof["rise"]).abs().mean())
    assert 0.0 <= m["coverage_of_90pct_predictive_interval"] <= 1.0


# ------------------------------------------------------------------ script

def _script():
    spec = importlib.util.spec_from_file_location("run_model_b", ROOT / "scripts" / "run_model_b.py")
    mod = importlib.util.module_from_spec(spec); sys.modules["run_model_b"] = mod; spec.loader.exec_module(mod)
    return mod


def test_script_end_to_end_aggregate_only_local_files_read_only(tmp_path, capsys):
    rmb = _script()
    root = tmp_path / "ds"; root.mkdir()
    g = cohort()
    a1c = {"healthy": 5.2, "pre-diabetes": 6.0, "t2d": 7.1}
    pd.DataFrame({"subject": [int(p[-3:]) for p in g], "A1c PDL (Lab)": [a1c[v] for v in g.values()]}).to_csv(root / "bio.csv", index=False)
    ev = make_events(per=8)
    ev.loc[ev.index[:5], "eligible_core"] = False
    table = tmp_path / "event_table_Libre_GL.csv"; ev.to_csv(table, index=False)
    before = hashlib.sha256(table.read_bytes()).hexdigest()
    out = tmp_path / "out"
    assert rmb.main(["--data-root", str(root), "--event-table", str(table), "--n-boot", "10", "--out-dir", str(out)]) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)
    assert rep["data"]["n_events"] == len(ev) - 5
    for needle in ("CGMacros-", "2000-01-01", str(root)):
        assert needle not in text, needle
    assert (out / "model_b_trajectories_Libre_GL.json").exists() and (out / "model_b_sequential_forecasts_Libre_GL.csv").exists()
    assert hashlib.sha256(table.read_bytes()).hexdigest() == before
    assert rmb.main(["--data-root", str(root), "--event-table", str(tmp_path / "events.csv")]) == 2


def test_event_definition_and_model_a_files_are_untouched_by_model_b():
    for f in ("scripts/build_event_table.py", "src/glycotwin/data/events.py", "src/glycotwin/models/model_a_cv.py"):
        assert "model_b" not in (ROOT / f).read_text(encoding="utf-8"), f


def test_the_frozen_prior_control_is_never_updated(events, folds, result):
    oof = result[0]
    for k in range(5):
        prior = fit_population_prior(events[events["participant_id"].map(folds) != k], B)
        sub = oof[oof["fold"] == k].head(25)
        for _, r in sub.iterrows():
            row = events.set_index("event_id").loc[r["event_id"]]
            assert r["p_frozen_prior"] == pytest.approx(forecast_exceeds_180(prior, row, float(row["baseline_glucose"])).probability_exceeds_180)
    later = oof[oof["n_personal_before"] > 0]
    assert (later["p"] != later["p_frozen_prior"]).any()


def test_prior_only_forecast_count_is_computed_from_the_forecasts(events, folds, result):
    oof, trajs, priors = result
    window_open = oof.copy()
    window_open.loc[window_open.index[:10], "n_personal_before"] = 0
    expected = int((window_open["n_personal_before"] == 0).sum())
    assert mb.personalization_summary(window_open, trajs, priors)["forecasts_made_from_prior_only"] == expected > 45


# ------------------------------------------------------------------ H12: blueprint form, no intercept

def test_model_b_design_has_no_intercept_anywhere(events, folds, result):
    oof, trajs, priors = result
    assert mb.MODEL_B_DESIGN == ["carbs_g"]
    prior = _prior(events)
    assert prior.feature_names == ["carbs_g"] and prior.mean.shape == (1,) and prior.covariance.shape == (1, 1)
    with pytest.raises(ValueError):
        prior.coefficient("intercept")
    with pytest.raises(ValueError, match="no intercept"):
        mb.sequential_participant(_one(events), fit_population_prior(events, ["intercept", "carbs_g"]))
    assert all("intercept_mean" not in t for tr in trajs.values() for t in tr["trajectory"])
    assert all("intercept_mean" not in v for v in priors.values())
    src = (ROOT / "src" / "glycotwin" / "models" / "model_b_cv.py").read_text(encoding="utf-8")
    assert "MODEL_B_FEATURES" not in src and 'coefficient("intercept")' not in src


def test_zero_carbohydrate_predicts_zero_rise_with_only_noise_uncertainty(events):
    prior = _prior(events)
    row = _one(events).iloc[0].copy()
    row["carbs_g"] = 0.0
    f = forecast_exceeds_180(prior, row, 150.0)
    sigma = float(np.sqrt(prior.noise_variance))
    assert f.mean_rise == 0.0 and f.predictive_std == pytest.approx(sigma)                 # nothing is added without carbohydrate
    from scipy.stats import norm
    assert f.probability_exceeds_180 == pytest.approx(norm.cdf((150.0 - 180.0) / sigma))


def test_scalar_closed_form_update_and_prediction(events):
    from scipy.stats import norm
    prior = _prior(events)
    m, tau2, s2 = float(prior.mean[0]), float(prior.covariance[0, 0]), prior.noise_variance
    ev = _one(events).sort_values("meal_time")
    c, rise = float(ev.iloc[0]["carbs_g"]), float(ev.iloc[0]["peak_glucose_rise"])
    post = conjugate_update(prior, ev.iloc[[0]])
    tau2_post = 1.0 / (1.0 / tau2 + c * c / s2)
    m_post = tau2_post * (m / tau2 + c * rise / s2)
    assert float(post.covariance[0, 0]) == pytest.approx(tau2_post) and float(post.mean[0]) == pytest.approx(m_post)
    nxt = ev.iloc[1]
    c2, base = float(nxt["carbs_g"]), float(nxt["baseline_glucose"])
    p_formula = norm.cdf((base + m_post * c2 - 180.0) / np.sqrt(s2 + c2 * c2 * tau2_post))
    recs, _ = mb.sequential_participant(ev, prior)
    assert recs[1]["p"] == pytest.approx(p_formula) and recs[1]["mean_rise"] == pytest.approx(m_post * c2)
    assert recs[1]["sens_mean_before"] == pytest.approx(m_post) and recs[1]["sens_sd_before"] == pytest.approx(np.sqrt(tau2_post))


# ------------------------------------------------------------------ fold-level prior: training participants only (review regression tests)

def _hand_prior(train):
    """Independent recomputation of the blueprint-form prior: m0 = pooled LS through the origin; sigma^2 = pooled
    within-participant residual variance of per-participant through-origin fits (dof n_i - 1); tau0^2 = variance of
    those slopes minus their mean sampling variance sigma^2 / sum(c^2), floored at 1e-3 * slope variance."""
    c, r = train["carbs_g"].to_numpy(float), train["peak_glucose_rise"].to_numpy(float)
    m0 = float(c @ r / (c @ c))
    slopes, ssr, dof, inv_cc = [], 0.0, 0, []
    for _, g in train.groupby("participant_id"):
        ci, ri = g["carbs_g"].to_numpy(float), g["peak_glucose_rise"].to_numpy(float)
        if len(g) <= 1:
            continue
        b = float(ci @ ri / (ci @ ci))
        slopes.append(b); ssr += float(((ri - b * ci) ** 2).sum()); dof += len(g) - 1; inv_cc.append(1.0 / float(ci @ ci))
    sigma2 = ssr / dof
    spread = float(np.var(slopes, ddof=1))
    tau02 = max(spread - sigma2 * float(np.mean(inv_cc)), max(1e-3 * spread, 1e-9))
    return m0, sigma2, tau02


def test_fold_prior_m0_sigma2_tau02_match_an_independent_computation_on_training_participants_only(events, folds, result):
    priors = result[2]
    for k in range(5):
        val_ids = {p for p, f in folds.items() if f == k}
        train = events[events["participant_id"].map(folds) != k]
        assert not set(train["participant_id"]) & val_ids
        m0, sigma2, tau02 = _hand_prior(train)
        p = priors[k]
        assert p["prior_source"] == "empirical_bayes_hierarchical"
        assert p["sens_mean"] == pytest.approx(m0, rel=1e-10)
        assert p["noise_sd"] ** 2 == pytest.approx(sigma2, rel=1e-10)
        assert p["sens_sd"] ** 2 == pytest.approx(tau02, rel=1e-10)
        assert p["n_training_participants"] == 45 - len(val_ids) and p["n_training_events"] == len(train)
        # the same computation on ALL participants differs, so the check above can tell training-only from leaky
        assert _hand_prior(events) != (m0, sigma2, tau02)


def test_fold_prior_is_unchanged_by_any_perturbation_of_its_validation_participants(events, folds, result):
    priors = result[2]
    for k in range(5):
        mod = events.copy()
        v = mod["participant_id"].map(folds) == k
        mod.loc[v, "peak_glucose_rise"] = mod.loc[v, "peak_glucose_rise"] * 7 + 300           # rises
        mod.loc[v, "carbs_g"] = mod.loc[v, "carbs_g"] * 0.1 + 1                               # carbs
        mod.loc[v, "baseline_glucose"] = mod.loc[v, "baseline_glucose"] + 60                  # baselines
        mod["label_exceeds_180"] = (mod["baseline_glucose"] + mod["peak_glucose_rise"] >= 180).astype(int)
        extra = mod[v].copy()                                                                  # extra validation events
        extra["event_id"] = extra["event_id"] + "x"
        extra["meal_time"] = extra["meal_time"] + pd.Timedelta(days=30)
        mod = pd.concat([mod, extra], ignore_index=True)
        oof_m, _, priors_m = mb.cross_validated_sequential(mod, folds)
        assert priors_m[k] == priors[k], k                                                     # m0, sigma, tau0, source, counts
        m0, sigma2, tau02 = _hand_prior(mod[mod["participant_id"].map(folds) != k])
        assert (priors_m[k]["sens_mean"], priors_m[k]["noise_sd"] ** 2, priors_m[k]["sens_sd"] ** 2) == pytest.approx((m0, sigma2, tau02), rel=1e-10)
        for j in range(5):                                                                     # those participants ARE training data elsewhere
            if j != k:
                assert priors_m[j] != priors[j], (k, j)
        assert len(oof_m) == len(mod)                                                          # the extra events are forecast, not dropped
