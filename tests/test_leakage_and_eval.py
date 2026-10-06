import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from synthetic import make_meals
from glycotwin.features import (OUTCOME_WINDOW, SplitResult, assert_no_temporal_leakage,
                                chronological_participant_split, validate_meal_events)
from glycotwin.models.baseline import PopulationBaselineModel
from glycotwin.models.evaluation import (compare_models_on_activity_strata, evaluate_predictions,
                                         expected_calibration_error)


# ---------- schema validation ----------

def test_valid_events_pass_and_missing_columns_fail():
    df = make_meals(3, ("a",))
    assert validate_meal_events(df) == []
    assert validate_meal_events(df.drop(columns=["carbs_g"]))


@pytest.mark.parametrize("mutate,fragment", [
    (lambda d: d.assign(label_exceeds_180=7), "other than 0/1"),
    (lambda d: d.assign(label_exceeds_180=1 - d.label_exceeds_180), "disagrees"),
    (lambda d: d.assign(carbs_g=-5.0), "negative"),
    (lambda d: d.assign(peak_glucose_rise=np.nan), "peak_glucose_rise"),
    (lambda d: d.assign(meal_time=d.meal_time.astype(str)), "datetime"),
    (lambda d: d.assign(participant_id=None), "participant_id"),
])
def test_validation_catches_bad_data(mutate, fragment):
    problems = validate_meal_events(mutate(make_meals(10, ("a",), noise_sd=20)))
    assert any(fragment in p for p in problems), problems


def test_validation_messages_do_not_leak_row_values():
    df = make_meals(10, ("a",), noise_sd=20).assign(carbs_g=-123.456)
    assert "123.456" not in " ".join(validate_meal_events(df))


# ---------- chronological split and leakage ----------

def test_chronological_split_is_disjoint_complete_and_leak_free():
    df = make_meals(20, ("a", "b", "c"))
    s = chronological_participant_split(df, 0.25)
    assert_no_temporal_leakage(df, s)
    assert set(s.train_index).isdisjoint(s.test_index)
    assert len(s.train_index) + len(s.test_index) + len(s.purged_index) == len(df)
    for pid, g in df.groupby("participant_id"):
        assert df.loc[s.test_index].query("participant_id == @pid").meal_time.min() > \
               df.loc[s.train_index].query("participant_id == @pid").meal_time.max()


def test_split_purges_training_meals_whose_outcome_window_reaches_the_test_period():
    df = make_meals(20, ("a",), spacing_hours=1)       # meals 1 h apart, outcome window 2 h
    s = chronological_participant_split(df, 0.25)
    first_test = df.loc[s.test_index].meal_time.min()
    # first test meal is at hour 15: the 14 h meal's window ends at 16 h (unobserved -> purged);
    # the 13 h meal's window ends at exactly 15 h (observed by then -> kept).
    assert list(s.purged_index) == [14] and 13 in s.train_index
    assert (df.loc[s.train_index].meal_time + OUTCOME_WINDOW <= first_test).all()
    assert_no_temporal_leakage(df, s)
    naive = SplitResult(df.index[:15], df.index[15:], "naive no-purge")
    with pytest.raises(AssertionError, match="leakage"):
        assert_no_temporal_leakage(df, naive)


def test_leakage_detector_flags_reversed_and_overlapping_splits():
    df = make_meals(20, ("a",))
    with pytest.raises(AssertionError):
        assert_no_temporal_leakage(df, SplitResult(df.index[10:], df.index[:10], "reversed"))
    with pytest.raises(AssertionError, match="share rows"):
        assert_no_temporal_leakage(df, SplitResult(df.index[:12], df.index[10:], "overlap"))


def test_single_meal_participant_goes_to_train_and_bad_fraction_rejected():
    df = make_meals(1, ("solo",))
    s = chronological_participant_split(df, 0.25)
    assert len(s.train_index) == 1 and len(s.test_index) == 0
    with pytest.raises(ValueError):
        chronological_participant_split(df, 1.0)


# ---------- metrics against hand-computed values ----------

def test_ece_hand_computed():
    y = np.array([0, 0, 1, 1]); p = np.array([0.15, 0.15, 0.85, 0.85])
    assert expected_calibration_error(y, p)[0] == pytest.approx(0.15)       # |.15-0| and |.85-1|
    assert expected_calibration_error(np.array([0] * 50 + [1] * 50), np.full(100, 0.5))[0] == pytest.approx(0.0)
    assert expected_calibration_error(np.array([0] * 50 + [1] * 50), np.full(100, 0.95))[0] == pytest.approx(0.45)


def test_metrics_match_reference_values():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 200); p = np.clip(0.3 * y + rng.uniform(0, 0.7, 200), 0, 1)
    r = evaluate_predictions(y, p)
    assert r.auroc == pytest.approx(roc_auc_score(y, p))
    assert r.brier_score == pytest.approx(np.mean((p - y) ** 2))
    assert sum(b.n_samples for b in r.reliability_bins) == 200


def test_small_or_single_class_samples_are_flagged_not_scored():
    r = evaluate_predictions([0, 0, 0], [0.1, 0.2, 0.3])
    assert r.auroc is None and r.auprc is None and r.warnings
    with pytest.raises(ValueError):
        evaluate_predictions([0, 1], [0.5])


def test_activity_strata_partition_uses_threshold_inclusively():
    df = make_meals(30, ("a",), noise_sd=20)
    df.loc[df.index[0], "activity_level"] = 0.5
    probs = np.random.default_rng(0).uniform(size=len(df))
    out = compare_models_on_activity_strata(df, {"A": probs}, 0.5)
    n_active = int((df.activity_level >= 0.5).sum())
    assert out["A"]["active"].n_samples == n_active
    assert out["A"]["sedentary"].n_samples == len(df) - n_active


# ---------- Model A ----------

def test_model_a_is_reproducible_valid_and_rejects_single_class():
    df = make_meals(60, ("a", "b"), noise_sd=15)
    p1 = PopulationBaselineModel().fit(df).predict_proba(df)
    p2 = PopulationBaselineModel().fit(df).predict_proba(df)
    np.testing.assert_array_equal(p1, p2)
    assert ((p1 >= 0) & (p1 <= 1)).all()
    with pytest.raises(ValueError):
        PopulationBaselineModel().fit(df.assign(label_exceeds_180=0))
    with pytest.raises(RuntimeError):
        PopulationBaselineModel().predict_proba(df)
