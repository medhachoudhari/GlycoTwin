"""Prequential harness: timing, leakage, controls, bootstrap and manifest (synthetic data only).

The "effect" and "no effect" datasets are SIMULATIONS with a known generating process. They show that
the machinery can detect an effect when one exists and stays inconclusive when none does. They are
not results about CGMacros.
"""
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import brier_score_loss, log_loss

from synthetic import make_hierarchical_meals
from glycotwin.models.experiment import (
    MODELS, build_manifest, paired_cluster_bootstrap, per_event_metric, prequential_participant,
    run_prequential_experiment)

STRONG = dict(n_participants=20, n_meals=24, seed=0, sens_sd=0.35, interaction_mean=-0.35, interaction_sd=0.1, noise_sd=8.0)
NULL = dict(n_participants=20, n_meals=24, seed=0, sens_sd=0.0, interaction_mean=0.0, interaction_sd=0.0, noise_sd=12.0)


def _split(df, pid="p000"):
    return df[df.participant_id == pid].copy(), df[df.participant_id != pid].copy()


# ---------------------------------------------------------------- timing and leakage

def test_updates_wait_until_the_outcome_window_has_closed():
    df = make_hierarchical_meals(10, 10, seed=1)
    ev, train = _split(df)
    base = pd.Timestamp("2000-01-01 08:00")
    ev = ev.iloc[:3].copy()
    ev["meal_time"] = [base, base + pd.Timedelta(minutes=30), base + pd.Timedelta(minutes=200)]   # overlapping, then clear
    rec = prequential_participant(ev, train)
    n = rec[rec.model == "B"].sort_values("order")["n_personal_before"].tolist()
    assert n == [0, 0, 2]            # meal 2 starts while meal 1's window is open; both are closed by meal 3


def test_prior_never_sees_the_held_out_participant():
    df = make_hierarchical_meals(10, 10, seed=2)
    ev, train = _split(df)
    with pytest.raises(ValueError, match="held-out"):
        prequential_participant(ev, df)
    ev2 = ev.copy(); ev2["peak_glucose_rise"] += 500; ev2["label_exceeds_180"] = 1
    a, b = prequential_participant(ev, train), prequential_participant(ev2, train)
    first = lambda r, m: r[(r.model == m) & (r.order == 0)][["p", "mean_rise", "pred_std"]].to_numpy()   # noqa: E731
    for m in MODELS:
        np.testing.assert_array_equal(first(a, m), first(b, m))          # event 0 forecast cannot depend on any outcome


def test_forecast_for_a_meal_depends_only_on_earlier_outcomes_for_every_model():
    df = make_hierarchical_meals(10, 12, seed=3)
    ev, train = _split(df)
    ev2 = ev.sort_values("meal_time").copy()
    k = 6
    ev2.iloc[k:, ev2.columns.get_loc("peak_glucose_rise")] += 300.0
    ev2.iloc[k:, ev2.columns.get_loc("label_exceeds_180")] = 1
    a, b = prequential_participant(ev, train, seed=5), prequential_participant(ev2, train, seed=5)
    for m in MODELS:
        pa = a[(a.model == m) & (a.order <= k)].sort_values("order")[["p", "mean_rise"]].to_numpy()
        pb = b[(b.model == m) & (b.order <= k)].sort_values("order")[["p", "mean_rise"]].to_numpy()
        np.testing.assert_array_equal(pa, pb)                            # up to and including meal k
    later = lambda r: r[(r.model == "B") & (r.order > k)]["p"].to_numpy()   # noqa: E731
    assert not np.array_equal(later(a), later(b))                        # and the change IS visible afterwards


def test_frozen_models_depend_only_on_the_meal_features():
    df = make_hierarchical_meals(10, 12, seed=4)
    ev, train = _split(df)
    ev = ev.sort_values("meal_time").copy()
    ev.iloc[5, ev.columns.get_loc("carbs_g")] = ev.iloc[1]["carbs_g"]
    ev.iloc[5, ev.columns.get_loc("activity_level")] = ev.iloc[1]["activity_level"]
    ev.iloc[5, ev.columns.get_loc("baseline_glucose")] = ev.iloc[1]["baseline_glucose"]
    r = prequential_participant(ev, train)
    for m in ("frozen_B", "frozen_C"):
        p = r[r.model == m].sort_values("order")["p"].to_numpy()
        assert p[1] == p[5]
    pb = r[r.model == "B"].sort_values("order")["p"].to_numpy()
    assert pb[1] != pb[5]                                               # the updating model has learned in between


def test_active_cut_comes_from_training_participants_only():
    df = make_hierarchical_meals(10, 12, seed=8)
    ev, train = _split(df)
    r = prequential_participant(ev, train)
    cut = train["activity_level"].median()
    assert (r["is_active"] == (r["activity"] >= cut)).all()
    shifted = ev.copy(); shifted["activity_level"] = shifted["activity_level"] * 0.1       # held-out distribution moves
    r2 = prequential_participant(shifted, train)
    assert (r2["is_active"] == (r2["activity"] >= cut)).all()                              # cut did not move with it


def test_personal_rate_baseline_is_carbs_times_the_running_mean_of_past_rise_per_gram():
    df = make_hierarchical_meals(10, 12, seed=9)
    ev, train = _split(df)
    ev = ev.sort_values("meal_time").iloc[:4].copy()                          # 6 h apart: windows always closed
    r = prequential_participant(ev, train).query("model == 'personal_rate'").sort_values("order")
    ratios = (ev["peak_glucose_rise"] / ev["carbs_g"].clip(lower=1.0)).to_numpy()
    carbs = ev["carbs_g"].to_numpy()
    for k in (1, 2, 3):
        assert r["mean_rise"].iloc[k] == pytest.approx(carbs[k] * ratios[:k].mean())
    from glycotwin.models.bayesian import MODEL_B_FEATURES, fit_population_prior
    pop_rate = fit_population_prior(train, MODEL_B_FEATURES).coefficient("carbs_g")[0]
    assert r["mean_rise"].iloc[0] == pytest.approx(carbs[0] * pop_rate)         # no history yet: population rate


def test_nonfinite_or_missing_inputs_are_rejected():
    df = make_hierarchical_meals(6, 8, seed=5)
    ev, train = _split(df)
    bad = ev.copy(); bad.iloc[0, bad.columns.get_loc("carbs_g")] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        prequential_participant(bad, train)
    with pytest.raises(ValueError, match="missing required"):
        prequential_participant(ev.drop(columns=["activity_level"]), train)


def test_run_is_deterministic_and_skips_participants_with_too_few_events():
    df = make_hierarchical_meals(8, 10, seed=6)
    df = pd.concat([df, df[df.participant_id == "p000"].iloc[:1].assign(participant_id="tiny")])
    a, b = run_prequential_experiment(df, seed=3), run_prequential_experiment(df, seed=3)
    pd.testing.assert_frame_equal(a, b)
    assert "tiny" not in set(a.participant_id) and set(a.model) == set(MODELS)


# ---------------------------------------------------------------- what the harness can and cannot detect

@pytest.fixture(scope="module")
def strong():
    return run_prequential_experiment(make_hierarchical_meals(**STRONG), seed=1)


@pytest.fixture(scope="module")
def null():
    return run_prequential_experiment(make_hierarchical_meals(**NULL), seed=1)


def test_detects_personalisation_and_the_shuffled_history_control_removes_it(strong):
    upd = paired_cluster_bootstrap(strong, "B", "frozen_B", "brier", n_boot=1000)
    assert upd["interval_excludes_zero"] and upd["estimate"] < 0
    ctl = paired_cluster_bootstrap(strong, "B", "B_shuffled", "brier", n_boot=1000)
    assert ctl["interval_excludes_zero"] and ctl["estimate"] < 0          # learning from other people's meals is worse
    assert paired_cluster_bootstrap(strong, "B", "personal_rate", "brier", n_boot=1000)["estimate"] < 0


def test_detects_the_activity_term_on_active_meals_and_the_permuted_control_removes_it(strong):
    r = paired_cluster_bootstrap(strong, "C", "B", "brier", subset=strong["is_active"], n_boot=1000)
    assert r["interval_excludes_zero"] and r["estimate"] < 0
    perm = paired_cluster_bootstrap(strong, "C", "C_perm_activity", "brier", n_boot=1000)
    assert perm["interval_excludes_zero"] and perm["estimate"] < 0


def test_stays_inconclusive_when_there_is_nothing_to_learn(null):
    for a, b in (("B", "frozen_B"), ("C", "B"), ("C", "C_perm_activity")):
        r = paired_cluster_bootstrap(null, a, b, "brier", n_boot=1000)
        assert not r["interval_excludes_zero"], (a, b, r)


# ---------------------------------------------------------------- bootstrap and metrics

def test_bootstrap_is_reproducible_clustered_and_zero_for_identical_models(strong):
    a = paired_cluster_bootstrap(strong, "B", "frozen_B", n_boot=500, seed=7)
    assert a == paired_cluster_bootstrap(strong, "B", "frozen_B", n_boot=500, seed=7)
    assert a["n_participants"] == strong.participant_id.nunique() == 20
    same = paired_cluster_bootstrap(strong, "B", "B", "brier", n_boot=300)
    assert same["estimate"] == 0 and same["ci_low"] == 0 == same["ci_high"]
    assert paired_cluster_bootstrap(strong, "B", "frozen_B", subset=pd.Series(False, index=strong.index))["n_events"] == 0


def test_bootstrap_resamples_participants_not_events():
    """Two participants with opposite, perfectly consistent differences: a cluster bootstrap must produce
    a wide interval (resampling can land on one participant only); an event-level one would not."""
    rows = []
    for pid, sign in (("a", -1.0), ("b", +1.0)):
        for i in range(50):
            for m, p in (("m1", 0.5 + 0.2 * sign), ("m2", 0.5)):
                rows.append({"participant_id": pid, "event_id": f"{pid}{i}", "model": m, "p": p, "y": 1, "mean_rise": 0.0, "rise": 0.0})
    r = paired_cluster_bootstrap(pd.DataFrame(rows), "m1", "m2", "brier", n_boot=2000, seed=1)
    assert r["ci_low"] < -0.05 and r["ci_high"] > 0.05 and not r["interval_excludes_zero"]


def test_metrics_match_reference_implementations():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 300); p = np.clip(rng.uniform(size=300), 0.01, 0.99)
    rec = pd.DataFrame({"y": y, "p": p, "mean_rise": rng.normal(size=300), "rise": rng.normal(size=300)})
    assert per_event_metric(rec, "brier").mean() == pytest.approx(brier_score_loss(y, p))
    assert per_event_metric(rec, "log_loss").mean() == pytest.approx(log_loss(y, p))
    assert per_event_metric(rec, "mae_rise").mean() == pytest.approx((rec.mean_rise - rec.rise).abs().mean())
    with pytest.raises(ValueError):
        per_event_metric(rec, "accuracy")


def test_manifest_is_deterministic_has_no_participant_values_and_detects_data_change():
    df = make_hierarchical_meals(6, 8, seed=7)
    m = build_manifest({"x": 1}, df, seed=3)
    assert m == build_manifest({"x": 1}, df, seed=3)
    assert m["n_events"] == 48 and m["n_participants"] == 6 and set(m["versions"]) >= {"numpy", "pandas", "scipy", "xgboost"}
    assert "p000" not in str(m)
    changed = df.copy(); changed.loc[changed.index[0], "carbs_g"] += 1
    assert build_manifest({"x": 1}, changed, seed=3)["event_table_sha256"] != m["event_table_sha256"]
