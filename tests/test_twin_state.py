import numpy as np
import pandas as pd
import pytest

from synthetic import make_hierarchical_meals
from glycotwin.features import OUTCOME_WINDOW
from glycotwin.models.bayesian import (MODEL_B_FEATURES, MODEL_C_FEATURES, conjugate_update,
                                       fit_population_prior)
from glycotwin.twin.state import TwinStore, forecast_meal, reconcile_forecast

PID = "p000"


def _setup(seed=7):
    df = make_hierarchical_meals(12, 20, seed=seed)
    s = TwinStore()
    s.initialize_twin(PID, fit_population_prior(df, MODEL_B_FEATURES, exclude_participants=(PID,)),
                      fit_population_prior(df, MODEL_C_FEATURES, exclude_participants=(PID,)))
    return s, df[df.participant_id == PID].reset_index(drop=True), df


def _reconcile(s, rec, row, **kw):
    return reconcile_forecast(s, rec.forecast_id, float(row.peak_glucose_rise),
                              bool(row.label_exceeds_180), **kw)


def test_reconcile_creates_new_version_and_keeps_history():
    s, meals, _ = _setup()
    rec = forecast_meal(s, PID, meals.iloc[0])
    assert rec.twin_version_at_forecast == 0 and len(s.pending_forecasts(PID)) == 1
    new = _reconcile(s, rec, meals.iloc[0])
    h = s.twin_history(PID)
    assert new.version == 1 and [t.version for t in h] == [0, 1]
    assert h[0].model_b.n_observations_used == 0 and h[1].model_b.n_observations_used == 1
    assert s.pending_forecasts(PID) == [] and s.is_reconciled(rec.forecast_id)


def test_store_pipeline_equals_direct_batch_update():
    """Forecast->reconcile N times must land on the same posterior as one batch update."""
    s, meals, _ = _setup()
    prior_c = s.current_twin(PID).model_c
    for i in range(10):
        _reconcile(s, forecast_meal(s, PID, meals.iloc[i]), meals.iloc[i])
    batch = conjugate_update(prior_c, meals.iloc[:10])
    np.testing.assert_allclose(s.current_twin(PID).model_c.mean, batch.mean, rtol=1e-7, atol=1e-9)
    np.testing.assert_allclose(s.current_twin(PID).model_c.covariance, batch.covariance, rtol=1e-7, atol=1e-9)
    assert s.current_twin(PID).version == 10


def test_overlapping_meals_reconciled_in_either_order_give_the_same_twin():
    outcomes = []
    for order in ((0, 1), (1, 0)):
        s, meals, _ = _setup()
        recs = [forecast_meal(s, PID, meals.iloc[i]) for i in (0, 1)]   # both forecast at version 0
        assert all(r.twin_version_at_forecast == 0 for r in recs)
        for i in order:
            _reconcile(s, recs[i], meals.iloc[i])
        outcomes.append(s.current_twin(PID).model_c)
    np.testing.assert_allclose(outcomes[0].mean, outcomes[1].mean, rtol=1e-9)
    np.testing.assert_allclose(outcomes[0].covariance, outcomes[1].covariance, rtol=1e-9)


def test_forecast_for_a_meal_depends_only_on_earlier_meals():
    """Leakage property of the pipeline: change every LATER outcome drastically and the
    forecasts already issued for earlier meals must be bit-identical."""
    def run(perturb_after):
        s, meals, _ = _setup()
        probs = []
        for i in range(8):
            rec = forecast_meal(s, PID, meals.iloc[i])
            probs.append((rec.model_b_forecast.probability_exceeds_180,
                          rec.model_c_forecast.probability_exceeds_180))
            row = meals.iloc[i].copy()
            if i > perturb_after:
                row["peak_glucose_rise"] += 500.0
                row["label_exceeds_180"] = 1
            _reconcile(s, rec, row)
        return probs
    base, perturbed = run(perturb_after=99), run(perturb_after=3)
    assert base[:5] == perturbed[:5]            # forecasts 0..4 saw only outcomes 0..3 (+0..3)
    assert base[5:] != perturbed[5:]            # and the perturbation is visible afterwards


def test_uncertainty_shrinks_across_reconciliations():
    s, meals, _ = _setup()
    first = s.current_twin(PID).model_c.coefficient("carbs_g")[1]
    for i in range(10):
        _reconcile(s, forecast_meal(s, PID, meals.iloc[i]), meals.iloc[i])
    assert s.current_twin(PID).model_c.coefficient("carbs_g")[1] < first


def test_guards_reject_double_reconcile_early_window_and_inconsistent_label_without_changing_state():
    s, meals, _ = _setup()
    row = meals.iloc[0]
    rec = forecast_meal(s, PID, row)
    too_early = row.meal_time + OUTCOME_WINDOW - pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="window"):
        _reconcile(s, rec, row, observed_through=too_early)
    with pytest.raises(ValueError, match="inconsistent"):
        reconcile_forecast(s, rec.forecast_id, float(row.peak_glucose_rise), not bool(row.label_exceeds_180))
    with pytest.raises(ValueError, match="finite"):
        reconcile_forecast(s, rec.forecast_id, float("nan"), False)
    assert s.current_twin(PID).version == 0 and s.pending_forecasts(PID)   # nothing was applied
    _reconcile(s, rec, row, observed_through=row.meal_time + OUTCOME_WINDOW)  # exactly complete: ok
    with pytest.raises(ValueError, match="already reconciled"):
        _reconcile(s, rec, row)
    assert s.current_twin(PID).version == 1                                  # not double counted


def test_twin_summary_reports_reference_activity_and_errors():
    s, meals, _ = _setup()
    summary = s.current_twin(PID).carb_sensitivity_summary()
    assert 0 < summary["model_c_reference_activity"] < 1
    with pytest.raises(KeyError):
        s.current_twin("nobody")
    with pytest.raises(ValueError):
        s.initialize_twin(PID, s.current_twin(PID).model_b, s.current_twin(PID).model_c)
