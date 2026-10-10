"""Backend (FastAPI + SQLite) tests. SYNTHETIC data only (simulated demo population and meals); no CGMacros data is read."""
import copy
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from glycotwin.backend import DISCLAIMER, services
from glycotwin.backend.app import create_app
from glycotwin.backend.config import Settings
from glycotwin.backend.models import (DataQualityFlag, ForecastRow, ObservationRow, ParameterSnapshot, ReconciliationRow, Twin, TwinStateRow,
                                      WhatIfRun)
from glycotwin.backend.priors import PriorError, demo_prior, load_prior_file, make_prior_artifact
from glycotwin.backend.store import SqlTwinStore
from glycotwin.twin import insight
from glycotwin.twin import state as engine
from glycotwin.twin.demo import demo_events
from glycotwin.twin.state import TwinStore, forecast_meal, reconcile_forecast

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 1, 1, 8, 0)
TABLES = {"twins", "twin_states", "parameter_snapshots", "forecasts", "observations", "reconciliations", "what_if_runs", "data_quality_flags"}


def make_app(tmp_path, url=None):
    prior_dir = tmp_path / "priors"
    prior_dir.mkdir(exist_ok=True)
    return create_app(Settings(database_url=url or f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}", prior_dir=prior_dir))


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    return TestClient(app)


def new_twin(client, label="tw-1", **kw):
    r = client.post("/twins", json={"label": label, **kw})
    assert r.status_code == 201, r.text
    return r.json()["data"]["twin_id"]


def meal(i=0, **kw):
    d = {"event_id": f"m{i}", "meal_time": (T0 + timedelta(hours=6 * i)).isoformat(), "carbs_g": 50.0 + 5 * i, "activity_level": 0.3 + 0.1 * i,
         "baseline_glucose": 105.0}
    d.update(kw)
    return d


def cycle(client, tid, i, peak=170.0, **kw):
    m = meal(i, **kw)
    f = client.post(f"/twins/{tid}/forecast", json=m).json()["data"]
    t = datetime.fromisoformat(m["meal_time"]) + timedelta(minutes=120)
    o = client.post(f"/twins/{tid}/observe", json={"forecast_id": f["forecast_id"], "observed_through": t.isoformat(), "peak_glucose_mg_dl": peak})
    assert o.status_code == 201, o.text
    r = client.post(f"/twins/{tid}/reconcile", json={"forecast_id": f["forecast_id"]})
    assert r.status_code == 201, r.text
    return f, r.json()["data"]


def session_of(app):
    return app.state.session_factory()


# ------------------------------------------------------------------ database creation and relationships

def test_tables_created_idempotently_and_foreign_keys_enforced(app, tmp_path):
    assert TABLES <= set(inspect(app.state.engine).get_table_names())
    c = TestClient(app)
    tid = new_twin(c)
    make_app(tmp_path)                                                       # second initialisation on the same file: nothing dropped
    with session_of(app) as s:
        assert s.get(Twin, tid) is not None
        s.add(ForecastRow(id="x" * 36, twin_id="no-such-twin", event_id="e", meal_time=T0, inputs={}, input_sha256="0", twin_version_at_forecast=0,
                          model_version="v", b_probability=0, b_mean_rise=0, b_sd=1, b_interval_low=0, b_interval_high=0, c_probability=0,
                          c_mean_rise=0, c_sd=1, c_interval_low=0, c_interval_high=0))
        with pytest.raises(IntegrityError):
            s.flush()                                                        # FOREIGN KEY enforced on SQLite
        s.rollback()


def test_version_zero_has_both_parameter_snapshots_and_the_relationships_navigate(client, app):
    tid = new_twin(client)
    with session_of(app) as s:
        t = s.get(Twin, tid)
        assert [st.version for st in t.states] == [0] and t.states[0].parent_version is None
        p = {x.model: x for x in t.states[0].parameters}
        assert set(p) == {"B", "C"} and p["B"].feature_names == ["carbs_g"] and p["C"].feature_names == ["carbs_g", "carbs_x_activity"]
        assert p["B"].gamma_mean is None and p["C"].gamma_var > 0 and p["C"].n_observations_used == 0


def test_state_persists_across_application_restarts(tmp_path):
    c1 = TestClient(make_app(tmp_path))
    tid = new_twin(c1)
    cycle(c1, tid, 0)
    c2 = TestClient(make_app(tmp_path))                                      # a new process on the same SQLite file
    d = c2.get(f"/twins/{tid}/history").json()["data"]
    assert [v["version"] for v in d["versions"]] == [0, 1] and d["versions"][1]["parent_version"] == 0
    assert c2.get(f"/twins/{tid}/forecasts").json()["data"]["total"] == 1


def test_health_reports_database_and_tables(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["database"] == "ok" and TABLES <= set(h["tables"]) and h["disclaimer"] == DISCLAIMER


# ------------------------------------------------------------------ request/response validation

@pytest.mark.parametrize("body", [{"label": "CGMacros-007"}, {"label": "has space"}, {"label": ""}, {"label": "ok", "extra": 1},
                                  {"label": "ok", "prior": {"prior_scheme": "empirical_bayes", "gamma_relative_sd": 0.5}},
                                  {"label": "ok", "prior": {"prior_scheme": "blueprint", "gamma_relative_sd": 0.3}},
                                  {"label": "ok", "prior": {"source": "prior_file"}}, {"label": "ok", "prior": {"source": "synthetic_demo", "name": "x.json"}},
                                  {"label": "ok", "glycaemic_group": "unknown"}, {"label": "ok", "reference_activity": -1}])
def test_create_twin_validation(client, body):
    assert client.post("/twins", json=body).status_code == 422


@pytest.mark.parametrize("change", [{"carbs_g": -1}, {"carbs_g": 501}, {"baseline_glucose": 10}, {"baseline_glucose": 700}, {"activity_level": 30},
                                    {"event_id": "bad id"}, {"event_id": "../x"}, {"activity_coverage": 1.5}, {"trend_slope_30min": 50}, {"unknown": 1},
                                    {"carbs_g": "lots"}, {"meal_time": "not a time"}])
def test_forecast_validation(client, change):
    tid = new_twin(client)
    assert client.post(f"/twins/{tid}/forecast", json=meal(0, **change)).status_code == 422
    assert client.get(f"/twins/{tid}/forecasts").json()["data"]["total"] == 0


def test_ids_and_missing_resources(client):
    assert client.get("/twins/not-a-uuid").status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    for method, path, body in (("get", f"/twins/{missing}", None), ("get", f"/twins/{missing}/history", None), ("get", f"/twins/{missing}/forecasts", None),
                               ("post", f"/twins/{missing}/forecast", meal(0)), ("post", f"/twins/{missing}/what-if",
                                                                                {"scenarios": [{"carbs_g": 1, "activity_level": 1}], "baseline_glucose": 100})):
        r = getattr(client, method)(path, **({"json": body} if body else {}))
        assert r.status_code == 404 and r.json()["disclaimer"] == DISCLAIMER


def test_observe_and_reconcile_and_what_if_validation(client):
    tid = new_twin(client)
    f = client.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    t = (T0 + timedelta(minutes=121)).isoformat()
    bad = [{"forecast_id": f["forecast_id"], "observed_through": t},                                             # neither peak nor exclusion
           {"forecast_id": f["forecast_id"], "observed_through": t, "peak_glucose_mg_dl": 150, "excluded_reason": "sensor gap"},
           {"forecast_id": f["forecast_id"], "observed_through": t, "peak_glucose_mg_dl": 5},
           {"forecast_id": f["forecast_id"], "observed_through": t, "peak_glucose_mg_dl": 150, "window_completeness": 2}]
    for b in bad:
        assert client.post(f"/twins/{tid}/observe", json=b).status_code == 422
    assert client.post(f"/twins/{tid}/reconcile", json={}).status_code == 422
    for w in ({"scenarios": [], "baseline_glucose": 100}, {"scenarios": [{"carbs_g": 1, "activity_level": 1}] * 11, "baseline_glucose": 100},
              {"scenarios": [{"carbs_g": -5, "activity_level": 1}], "baseline_glucose": 100}):
        assert client.post(f"/twins/{tid}/what-if", json=w).status_code == 422


def test_every_success_response_carries_the_research_disclaimer(client):
    tid = new_twin(client)
    f, r = cycle(client, tid, 0)
    for resp in (client.get(f"/twins/{tid}"), client.get(f"/twins/{tid}/history"), client.get(f"/twins/{tid}/forecasts"),
                 client.post(f"/twins/{tid}/what-if", json={"scenarios": [{"carbs_g": 30, "activity_level": 0.5}], "baseline_glucose": 100})):
        assert resp.status_code == 200 and resp.json()["disclaimer"] == DISCLAIMER
    assert "not a diagnosis" in DISCLAIMER and "Not clinically validated" in DISCLAIMER


# ------------------------------------------------------------------ forecast persistence, history and engine compatibility

def test_forecast_is_persisted_with_both_models_uncertainty_version_and_provenance(client, app):
    tid = new_twin(client)
    r = client.post(f"/twins/{tid}/forecast", json=meal(0, activity_coverage=0.2))
    assert r.status_code == 201
    d = r.json()["data"]
    for m in ("model_b", "model_c"):
        lo, hi = d[m]["interval90_rise_mg_dl"]
        assert 0 <= d[m]["p_peak_at_least_180"] <= 1 and lo < d[m]["mean_rise_mg_dl"] < hi and d[m]["sd_mg_dl"] > 0
    assert d["twin_version_at_forecast"] == 0 and d["status"] == "pending" and d["created"] is True and "prior=empirical_bayes" in d["model_version"]
    assert "git_commit" in d["engine_provenance"] and d["data_quality"]["low_data_quality"] and d["data_quality"]["insufficient_history"]
    with session_of(app) as s:
        codes = sorted(x.code for x in s.scalars(select(DataQualityFlag).where(DataQualityFlag.forecast_id == d["forecast_id"])))
        assert codes == ["insufficient_history", "low_data_quality"]
    lst = client.get(f"/twins/{tid}/forecasts").json()["data"]
    assert lst["total"] == 1 and lst["forecasts"][0]["forecast_id"] == d["forecast_id"]


def test_forecasts_equal_the_in_memory_engine_through_a_whole_lifecycle(client):
    """Regression compatibility: the database-backed twin reproduces the in-memory TwinStore exactly (same engine, no second implementation)."""
    tid = new_twin(client)
    prior_b, prior_c, _ = demo_prior()
    mem = TwinStore()
    mem.initialize_twin("x", prior_b, prior_c)
    peaks = [150, 210, 175, 190, 160]
    for i, peak in enumerate(peaks):
        m = meal(i)
        api_f, _ = cycle(client, tid, i, peak=peak)
        row = pd.Series({"meal_time": pd.Timestamp(m["meal_time"]), "carbs_g": m["carbs_g"], "activity_level": m["activity_level"],
                         "baseline_glucose": m["baseline_glucose"]})
        rec = forecast_meal(mem, "x", row)
        assert api_f["model_c"]["p_peak_at_least_180"] == pytest.approx(rec.model_c_forecast.probability_exceeds_180, abs=1e-12)
        assert api_f["model_b"]["mean_rise_mg_dl"] == pytest.approx(rec.model_b_forecast.mean_rise, abs=1e-9)
        reconcile_forecast(mem, rec.forecast_id, peak - m["baseline_glucose"], peak >= 180)
    h = client.get(f"/twins/{tid}/history").json()["data"]["versions"][-1]["parameters"]
    tw = mem.current_twin("x")
    assert h["C"]["beta_mean"] == pytest.approx(tw.model_c.mean[0], abs=1e-12) and h["C"]["gamma_var"] == pytest.approx(tw.model_c.covariance[1, 1], abs=1e-15)
    assert h["B"]["beta_mean"] == pytest.approx(tw.model_b.mean[0], abs=1e-12)
    assert services.forecast_meal is engine.forecast_meal and services.reconcile_forecast is engine.reconcile_forecast   # one engine, reused


def test_history_has_every_version_with_parent_links_and_insight_views(client):
    tid = new_twin(client)
    for i in range(3):
        cycle(client, tid, i, peak=150 + 20 * i)
    d = client.get(f"/twins/{tid}/history").json()["data"]
    assert [v["version"] for v in d["versions"]] == [0, 1, 2, 3] and [v["parent_version"] for v in d["versions"]] == [None, 0, 1, 2]
    assert all(v["reconciliation_id"] for v in d["versions"][1:]) and d["versions"][0]["reconciliation_id"] is None
    assert d["posterior_convergence"]["monotone_non_increasing"]["model_c_beta_sd"] and d["hit_rate_trend"]["n_reconciled"] == 3
    s = client.get(f"/twins/{tid}").json()["data"]
    assert s["state"]["historical_response_state"]["version_number"] == 3 and s["insight"]["n_reconciled_observations"] == 3


def test_forecast_list_pagination_and_status(client):
    tid = new_twin(client)
    cycle(client, tid, 0)
    for i in (1, 2, 3):
        client.post(f"/twins/{tid}/forecast", json=meal(i))
    d = client.get(f"/twins/{tid}/forecasts?limit=2&offset=1").json()["data"]
    assert d["total"] == 4 and [f["event_id"] for f in d["forecasts"]] == ["m1", "m2"]
    allf = client.get(f"/twins/{tid}/forecasts").json()["data"]["forecasts"]
    assert [f["status"] for f in allf] == ["reconciled", "pending", "pending", "pending"]


# ------------------------------------------------------------------ forecast-observation linkage

def test_observation_is_linked_to_its_forecast_and_derived_correctly(client, app):
    tid = new_twin(client)
    f = client.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    t = (T0 + timedelta(minutes=120)).isoformat()
    o = client.post(f"/twins/{tid}/observe", json={"forecast_id": f["forecast_id"], "observed_through": t, "peak_glucose_mg_dl": 180, "window_completeness": 0.9}).json()["data"]
    assert o["forecast_id"] == f["forecast_id"] and o["peak_glucose_rise_mg_dl"] == pytest.approx(75.0) and o["label_peak_at_least_180"] is True   # 180 is inclusive
    assert client.get(f"/twins/{tid}/forecasts").json()["data"]["forecasts"][0]["status"] == "observed"
    with session_of(app) as s:
        assert s.get(ForecastRow, f["forecast_id"]).observation.id == o["observation_id"]
        assert s.scalars(select(DataQualityFlag).where(DataQualityFlag.code == "partial_window")).first() is not None
    assert client.get(f"/twins/{tid}").json()["data"]["state"]["historical_response_state"]["version_number"] == 0   # observing alone never updates


def test_an_outcome_window_that_has_not_closed_is_refused(client):
    tid = new_twin(client)
    f = client.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    r = client.post(f"/twins/{tid}/observe", json={"forecast_id": f["forecast_id"], "observed_through": (T0 + timedelta(minutes=119)).isoformat(), "peak_glucose_mg_dl": 150})
    assert r.status_code == 422 and "window" in r.json()["detail"]


def test_reconcile_requires_an_observation_and_an_excluded_meal_never_updates(client):
    tid = new_twin(client)
    f = client.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    assert client.post(f"/twins/{tid}/reconcile", json={"forecast_id": f["forecast_id"]}).status_code == 409
    client.post(f"/twins/{tid}/observe", json={"forecast_id": f["forecast_id"], "observed_through": (T0 + timedelta(minutes=130)).isoformat(),
                                                "excluded_reason": "sensor gap over 30 minutes"})
    r = client.post(f"/twins/{tid}/reconcile", json={"forecast_id": f["forecast_id"]}).json()["data"]
    assert r["outcome"] == "excluded" and r["twin_version_before"] == r["twin_version_after"] == 0
    h = client.get(f"/twins/{tid}/history").json()["data"]
    assert len(h["versions"]) == 1 and h["exclusions"] == [{"forecast_id": f["forecast_id"], "reason": "sensor gap over 30 minutes"}]
    assert client.get(f"/twins/{tid}/forecasts").json()["data"]["forecasts"][0]["status"] == "excluded"


# ------------------------------------------------------------------ atomic reconciliation and rollback

def _counts(app):
    with session_of(app) as s:
        return {m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in (TwinStateRow, ParameterSnapshot, ReconciliationRow, ForecastRow)}


def test_a_failure_in_the_middle_of_reconciliation_rolls_everything_back(app, monkeypatch):
    client = TestClient(app, raise_server_exceptions=False)
    tid = new_twin(client)
    f = client.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    client.post(f"/twins/{tid}/observe", json={"forecast_id": f["forecast_id"], "observed_through": (T0 + timedelta(minutes=120)).isoformat(), "peak_glucose_mg_dl": 200})
    before = _counts(app)

    def boom(self, record):                                     # the new version has already been written when this runs
        raise RuntimeError("simulated failure after the version was written")
    monkeypatch.setattr(SqlTwinStore, "save_observation", boom)
    assert client.post(f"/twins/{tid}/reconcile", json={"forecast_id": f["forecast_id"]}).status_code == 500
    assert _counts(app) == before                               # no new version, no parameters, no reconciliation
    assert client.get(f"/twins/{tid}").json()["data"]["state"]["historical_response_state"]["version_number"] == 0
    monkeypatch.undo()
    r = client.post(f"/twins/{tid}/reconcile", json={"forecast_id": f["forecast_id"]})
    assert r.status_code == 201 and r.json()["data"]["twin_version_after"] == 1


def test_a_failure_while_storing_a_forecast_leaves_nothing_behind(app, monkeypatch):
    client = TestClient(app, raise_server_exceptions=False)
    tid = new_twin(client)
    real = SqlTwinStore.save_forecast

    def half(self, record):
        real(self, record)
        raise RuntimeError("fail after the forecast row was flushed")
    monkeypatch.setattr(SqlTwinStore, "save_forecast", half)
    assert client.post(f"/twins/{tid}/forecast", json=meal(0)).status_code == 500
    with session_of(app) as s:
        assert s.scalar(select(func.count()).select_from(ForecastRow)) == 0 and s.scalar(select(func.count()).select_from(DataQualityFlag)) == 0


def test_a_concurrent_version_conflict_is_refused_and_rolled_back(app):
    client = TestClient(app)
    tid = new_twin(client)
    f = client.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    client.post(f"/twins/{tid}/observe", json={"forecast_id": f["forecast_id"], "observed_through": (T0 + timedelta(minutes=120)).isoformat(), "peak_glucose_mg_dl": 200})
    with session_of(app) as s:                                   # another writer already created version 1
        s.add(TwinStateRow(twin_id=tid, version=1, parent_version=0, n_observations=1))
        s.commit()
    before = _counts(app)
    r = client.post(f"/twins/{tid}/reconcile", json={"forecast_id": f["forecast_id"]})
    assert r.status_code == 409 and _counts(app) == before


# ------------------------------------------------------------------ duplicate requests

def test_repeated_requests_are_idempotent_and_conflicting_repeats_are_refused(client):
    tid = new_twin(client)
    a = client.post(f"/twins/{tid}/forecast", json=meal(0))
    b = client.post(f"/twins/{tid}/forecast", json=meal(0))
    assert a.status_code == 201 and b.status_code == 200 and b.json()["data"]["created"] is False
    assert a.json()["data"]["forecast_id"] == b.json()["data"]["forecast_id"]
    assert client.post(f"/twins/{tid}/forecast", json=meal(0, carbs_g=99)).status_code == 409
    fid = a.json()["data"]["forecast_id"]
    obs = {"forecast_id": fid, "observed_through": (T0 + timedelta(minutes=120)).isoformat(), "peak_glucose_mg_dl": 190}
    assert client.post(f"/twins/{tid}/observe", json=obs).status_code == 201
    assert client.post(f"/twins/{tid}/observe", json=obs).status_code == 200
    assert client.post(f"/twins/{tid}/observe", json={**obs, "peak_glucose_mg_dl": 150}).status_code == 409
    r1 = client.post(f"/twins/{tid}/reconcile", json={"forecast_id": fid})
    r2 = client.post(f"/twins/{tid}/reconcile", json={"forecast_id": fid})
    assert r1.status_code == 201 and r2.status_code == 200 and r2.json()["data"]["created"] is False
    assert r1.json()["data"]["reconciliation_id"] == r2.json()["data"]["reconciliation_id"]
    assert [v["version"] for v in client.get(f"/twins/{tid}/history").json()["data"]["versions"]] == [0, 1]       # updated exactly once
    assert client.get(f"/twins/{tid}/forecasts").json()["data"]["total"] == 1
    assert client.post("/twins", json={"label": "tw-1"}).status_code == 409


# ------------------------------------------------------------------ twin isolation

def test_twins_are_isolated(client):
    a, b = new_twin(client, "tw-a"), new_twin(client, "tw-b")
    fa, _ = cycle(client, a, 0, peak=230)
    assert client.get(f"/twins/{b}/forecasts").json()["data"]["total"] == 0
    assert client.get(f"/twins/{b}").json()["data"]["state"]["historical_response_state"]["version_number"] == 0
    t = (T0 + timedelta(minutes=120)).isoformat()
    assert client.post(f"/twins/{b}/observe", json={"forecast_id": fa["forecast_id"], "observed_through": t, "peak_glucose_mg_dl": 150}).status_code == 404
    assert client.post(f"/twins/{b}/reconcile", json={"forecast_id": fa["forecast_id"]}).status_code == 404
    assert client.post(f"/twins/{b}/forecast", json=meal(0)).status_code == 201          # the same client event id is independent per twin
    hb = client.get(f"/twins/{b}/history").json()["data"]["versions"]
    ha = client.get(f"/twins/{a}/history").json()["data"]["versions"]
    assert len(hb) == 1 and len(ha) == 2 and hb[0]["parameters"]["C"]["beta_mean"] == ha[0]["parameters"]["C"]["beta_mean"]


# ------------------------------------------------------------------ what-if never changes the twin

def test_what_if_leaves_the_twin_unchanged_and_is_recorded(client, app):
    tid = new_twin(client)
    cycle(client, tid, 0)
    state_before = client.get(f"/twins/{tid}/history").json()["data"]
    counts_before = _counts(app)
    body = {"scenarios": [{"label": "current", "carbs_g": 60, "activity_level": 0.4}, {"label": "less", "carbs_g": 40, "activity_level": 0.4}], "baseline_glucose": 110}
    d = client.post(f"/twins/{tid}/what-if", json=body).json()["data"]
    assert client.get(f"/twins/{tid}/history").json()["data"] == state_before and _counts(app) == counts_before
    assert "not a diet prescription" in d["screen_label"] and d["twin_version_used"] == 1
    assert d["scenarios"][1]["difference_from_first_scenario"]["model_c"]["mean_rise_mg_dl"] < 0
    with session_of(app) as s:
        run = s.get(WhatIfRun, d["what_if_id"])
        assert run is not None and run.twin_version_used == 1 and run.request["baseline_glucose"] == 110
        tw = SqlTwinStore(s, tid).current_twin(tid)
    ref = insight.what_if(tw, [{"label": "current", "carbs_g": 60, "activity_level": 0.4}, {"label": "less", "carbs_g": 40, "activity_level": 0.4}], 110.0,
                          {"carbs_g": (50.0, 50.0), "activity_level": (0.3, 0.3)})
    assert d["scenarios"][0]["model_c"]["p_peak_at_least_180"] == pytest.approx(ref["scenarios"][0]["model_c"]["p_peak_at_least_180"])
    assert d["scenarios"][1]["extrapolation_warnings"]                                    # 40 g lies outside the twin's observed range


# ------------------------------------------------------------------ leakage safeguards

def test_a_back_dated_forecast_after_learning_is_refused(client):
    tid = new_twin(client)
    cycle(client, tid, 2)                                                              # learned from the window closing at meal 2 + 120 min
    early = meal(1, event_id="early")
    r = client.post(f"/twins/{tid}/forecast", json=early)
    assert r.status_code == 409 and "back-dated" in r.json()["detail"]
    ok = meal(2, event_id="after", meal_time=(T0 + timedelta(hours=12, minutes=120)).isoformat())
    assert client.post(f"/twins/{tid}/forecast", json=ok).status_code == 201


def _artifact(prior_dir, name="p.json", **over):
    b, c, _ = demo_prior()
    art = make_prior_artifact(b, c, {"prior_scheme": "empirical_bayes", "gamma_relative_sd": None, "fitted_on": "test", "excluded_participants_count": 0})
    art.update(over)
    (prior_dir / name).write_text(json.dumps(art))
    return art


def test_prior_files_are_aggregate_only_and_strictly_validated(tmp_path, app):
    client = TestClient(app)
    prior_dir = app.state.settings.prior_dir
    _artifact(prior_dir, "good.json")
    r = client.post("/twins", json={"label": "file-twin", "prior": {"source": "prior_file", "name": "good.json"}})
    assert r.status_code == 201 and r.json()["data"]["prior_provenance"]["contains_participant_level_data"] is False
    _artifact(prior_dir, "flag.json", contains_participant_level_data=True)
    _artifact(prior_dir, "events.json", events=[{"participant_id": "x"}])
    bad_cov = _artifact(prior_dir, "tmp.json")
    bad_cov["model_c"]["covariance"] = [[1.0, 2.0], [2.0, 1.0]]
    (prior_dir / "cov.json").write_text(json.dumps(bad_cov))
    for i, name in enumerate(("flag.json", "events.json", "cov.json", "missing.json", "../good.json", "good.txt")):
        resp = client.post("/twins", json={"label": f"bad-{i}", "prior": {"source": "prior_file", "name": name}})
        assert resp.status_code == 422, name
    assert client.post("/twins", json={"label": "mismatch", "prior": {"source": "prior_file", "name": "good.json", "prior_scheme": "blueprint"}}).status_code == 422
    with pytest.raises(PriorError):
        load_prior_file(prior_dir, "../../etc/passwd.json")


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


def _event_table(tmp_path):
    from test_model_c_cv import make_events
    ev = make_events(per=8, seed=3)
    p = tmp_path / "event_table_Libre_GL.csv"
    ev.to_csv(p, index=False)
    return ev, p


def test_export_prior_excludes_the_live_person_and_writes_aggregates_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GLYCOTWIN_PRIOR_DIR", str(tmp_path / "priors"))
    mod = _load_script("export_prior")
    ev, table = _event_table(tmp_path)
    with pytest.raises(SystemExit):
        mod.main(["--event-table", str(table), "--name", "a.json"])                    # an explicit exclusion decision is required
    assert mod.main(["--event-table", str(table), "--name", "a.json", "--exclude-participant", "CGMacros-999"]) == 2   # not in the population
    assert mod.main(["--event-table", str(table), "--name", "a.json", "--exclude-participant", "CGMacros-010"]) == 0
    art = json.loads((tmp_path / "priors" / "a.json").read_text())
    assert art["contains_participant_level_data"] is False and art["provenance"]["n_participants"] == 44 and art["provenance"]["excluded_participants_count"] == 1
    assert "CGMacros-" not in json.dumps(art) and "2000-01-01" not in json.dumps(art)
    changed = ev.copy()
    m = changed["participant_id"] == "CGMacros-010"
    changed.loc[m, "peak_glucose_rise"] = changed.loc[m, "peak_glucose_rise"] * 9 + 400
    t2 = tmp_path / "x" / "event_table_Libre_GL.csv"; t2.parent.mkdir(); changed.to_csv(t2, index=False)
    assert mod.main(["--event-table", str(t2), "--name", "b.json", "--exclude-participant", "CGMacros-010"]) == 0
    art2 = json.loads((tmp_path / "priors" / "b.json").read_text())
    assert art2["model_c"]["mean"] == art["model_c"]["mean"] and art2["model_b"]["covariance"] == art["model_b"]["covariance"]   # own outcomes never enter
    assert mod.main(["--event-table", str(table), "--name", "a.json", "--live-person-not-in-population"]) == 2                    # never overwrites
    capsys.readouterr()


def test_no_endpoint_lists_twins_or_research_participants(app):
    spec = app.openapi()["paths"]
    paths = {(p, tuple(sorted(m.upper() for m in ops))) for p, ops in spec.items()}
    api = set(spec)
    assert api == {"/health", "/twins", "/twins/{twin_id}", "/twins/{twin_id}/history", "/twins/{twin_id}/forecast", "/twins/{twin_id}/forecasts",
                   "/twins/{twin_id}/observe", "/twins/{twin_id}/reconcile", "/twins/{twin_id}/what-if"}
    assert ("/twins", ("POST",)) in paths                                                # creating, never listing
    assert all("participant" not in p for p in api)


def test_the_research_engine_and_research_protocol_are_untouched_by_the_backend():
    for f in ("src/glycotwin/twin/state.py", "src/glycotwin/models/bayesian.py", "src/glycotwin/data/events.py"):
        assert "glycotwin.backend" not in (ROOT / f).read_text(encoding="utf-8")
    from glycotwin.models.prior_schemes import DEFAULT_SCHEME
    assert DEFAULT_SCHEME == "empirical_bayes"


# ------------------------------------------------------------------ init script and synthetic demo

def test_init_db_script_is_safe_to_repeat_and_creates_a_labelled_synthetic_demo(tmp_path, capsys):
    mod = _load_script("init_db")
    url = f"sqlite:///{(tmp_path / 'demo.sqlite3').as_posix()}"
    assert mod.main(["--database-url", url, "--demo"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["label"] == "demo-synthetic-001" and "SYNTHETIC" in first["note"]
    assert mod.main(["--database-url", url, "--demo"]) == 0
    assert "already present" in json.loads(capsys.readouterr().out)["demo"]
    client = TestClient(make_app(tmp_path, url))
    d = client.get(f"/twins/{first['demo_twin_id']}/history").json()["data"]
    assert len(d["versions"]) == 9 and d["versions"][-1]["parameters"]["C"]["n_observations_used"] == 8
    assert client.get(f"/twins/{first['demo_twin_id']}").json()["data"]["is_synthetic"] is True


def test_the_store_is_scoped_to_one_twin(client, app):
    a, b = new_twin(client, "tw-a"), new_twin(client, "tw-b")
    fb = client.post(f"/twins/{b}/forecast", json=meal(0)).json()["data"]
    with session_of(app) as s:
        sa = SqlTwinStore(s, a)
        for call in (lambda: sa.current_twin(b), lambda: sa.reconciliation_log(b), lambda: sa.pending_forecasts(b), lambda: sa.get_forecast(fb["forecast_id"])):
            with pytest.raises(KeyError):
                call()
        assert sa.twin_history(b) == [] and sa.participants() == [a] and sa._forecasts == {}
        with pytest.raises(NotImplementedError):
            sa._snapshot()


# ------------------------------------------------------------------ activity scale: the synthetic demo prior must not extrapolate silently

def test_demo_prior_declares_its_activity_scale_and_matches_the_simulated_population():
    from glycotwin.backend.priors import DEMO_ACTIVITY_RANGE
    from glycotwin.twin.demo import demo_events, demo_population
    _, _, prov = demo_prior()
    assert prov["supported_activity_range"] == list(DEMO_ACTIVITY_RANGE) == [0.0, 1.0] and prov["activity_range_enforcement"] == "reject"
    assert "not METs" in prov["activity_scale"] and prov["SYNTHETIC"] is True
    for df in (demo_population(0), demo_population(3), demo_events(0, 200)):                  # the declared range really covers the simulator
        assert df["activity_level"].min() >= DEMO_ACTIVITY_RANGE[0] and df["activity_level"].max() <= DEMO_ACTIVITY_RANGE[1]


@pytest.mark.parametrize("bad", [1.0001, 1.2, 3.0, 8.0, 25.0])
def test_demo_twin_rejects_activity_outside_the_simulated_scale_and_stores_nothing(client, app, bad):
    tid = new_twin(client)
    before = _counts(app)
    r = client.post(f"/twins/{tid}/forecast", json=meal(0, activity_level=bad))
    assert r.status_code == 422 and "supported by this synthetic demo twin" in r.json()["detail"] and "not METs" in r.json()["detail"]
    assert _counts(app) == before and client.get(f"/twins/{tid}/forecasts").json()["data"]["total"] == 0
    w = client.post(f"/twins/{tid}/what-if", json={"scenarios": [{"carbs_g": 50, "activity_level": 0.5}, {"carbs_g": 50, "activity_level": bad}], "baseline_glucose": 100})
    assert w.status_code == 422
    with session_of(app) as s:
        assert s.scalar(select(func.count()).select_from(WhatIfRun)) == 0                      # a rejected request is not recorded


@pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
def test_demo_twin_accepts_activity_on_its_scale_including_the_boundaries(client, ok):
    tid = new_twin(client)
    assert client.post(f"/twins/{tid}/forecast", json=meal(0, activity_level=ok)).status_code == 201
    assert client.post(f"/twins/{tid}/what-if", json={"scenarios": [{"carbs_g": 50, "activity_level": ok}], "baseline_glucose": 100}).status_code == 200


def test_a_rejected_forecast_can_be_resubmitted_correctly_and_a_stored_one_is_not_re_judged(client):
    tid = new_twin(client)
    assert client.post(f"/twins/{tid}/forecast", json=meal(0, activity_level=2.0)).status_code == 422
    assert client.post(f"/twins/{tid}/forecast", json=meal(0, activity_level=0.4)).status_code == 201     # same event id, valid input
    assert client.post(f"/twins/{tid}/forecast", json=meal(0, activity_level=0.4)).status_code == 200     # idempotent repeat unaffected


def test_the_unscaled_demo_forecast_would_have_been_misleading(client):
    """Why the rejection exists: on the raw prior, METs-sized activity drives the predicted rise towards zero and below."""
    import pandas as pd
    from glycotwin.models.bayesian import forecast_exceeds_180
    _, c, _ = demo_prior()
    rises = [forecast_exceeds_180(c, pd.Series({"carbs_g": 60.0, "activity_level": a}), 105.0).mean_rise for a in (0.5, 3.0, 8.0)]
    assert rises[0] > 40 and rises[1] < 10 and rises[2] < 0


def test_prior_file_twins_flag_but_do_not_reject_activity_outside_the_fitted_range(app):
    client = TestClient(app)
    prior_dir = app.state.settings.prior_dir
    art = _artifact(prior_dir, "ranged.json")
    art["provenance"]["activity_range"] = [1.0, 2.0]
    (prior_dir / "ranged.json").write_text(json.dumps(art))
    tid = client.post("/twins", json={"label": "ranged", "prior": {"source": "prior_file", "name": "ranged.json"}}).json()["data"]["twin_id"]
    inside = client.post(f"/twins/{tid}/forecast", json=meal(0, activity_level=1.5)).json()["data"]
    assert not any("outside" in r for r in inside["data_quality"]["reasons"])
    out = client.post(f"/twins/{tid}/forecast", json=meal(1, activity_level=5.0))
    assert out.status_code == 201
    dq = out.json()["data"]["data_quality"]
    assert dq["low_data_quality"] and any("outside the range [1, 2]" in r for r in dq["reasons"]) and "OUTSIDE PRIOR RANGE" in dq["warning"]
    with session_of(app) as s:
        assert s.scalars(select(DataQualityFlag).where(DataQualityFlag.code == "activity_outside_prior_range")).first() is not None
    w = client.post(f"/twins/{tid}/what-if", json={"scenarios": [{"carbs_g": 50, "activity_level": 5.0}], "baseline_glucose": 100})
    assert w.status_code == 200 and w.json()["data"]["prior_support_warnings"]
    plain = _artifact(prior_dir, "plain.json")                                           # no recorded range: nothing to enforce or flag
    t2 = client.post("/twins", json={"label": "plain", "prior": {"source": "prior_file", "name": "plain.json"}}).json()["data"]["twin_id"]
    assert client.post(f"/twins/{t2}/forecast", json=meal(0, activity_level=5.0)).status_code == 201


def test_export_prior_records_the_aggregate_activity_range(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GLYCOTWIN_PRIOR_DIR", str(tmp_path / "priors"))
    mod = _load_script("export_prior")
    ev, table = _event_table(tmp_path)
    assert mod.main(["--event-table", str(table), "--name", "r.json", "--live-person-not-in-population"]) == 0
    prov = json.loads((tmp_path / "priors" / "r.json").read_text())["provenance"]
    assert prov["activity_range"] == [pytest.approx(ev["activity_level"].min()), pytest.approx(ev["activity_level"].max())]
    capsys.readouterr()


# ------------------------------------------------------------------ fresh initialisation and re-initialisation never drop data

def _dump(engine):
    from sqlalchemy import text
    out = {}
    with engine.connect() as c:
        for t in sorted(TABLES):
            rows = c.execute(text(f"SELECT * FROM {t} ORDER BY 1, 2")).fetchall()
            out[t] = [tuple(map(str, r)) for r in rows]
    return out


def test_fresh_initialisation_creates_exactly_the_documented_tables_indexes_and_constraints(tmp_path):
    url = f"sqlite:///{(tmp_path / 'new' / 'nested' / 'fresh.sqlite3').as_posix()}"              # the folder does not exist yet
    a = make_app(tmp_path, url)
    insp = inspect(a.state.engine)
    assert set(insp.get_table_names()) == TABLES
    uniques = {t: [tuple(u["column_names"]) for u in insp.get_unique_constraints(t)] for t in ("twin_states", "forecasts", "parameter_snapshots")}
    assert ("twin_id", "version") in uniques["twin_states"] and ("twin_id", "event_id") in uniques["forecasts"] and ("twin_state_id", "model") in uniques["parameter_snapshots"]
    idx = {t: {tuple(i["column_names"]) for i in insp.get_indexes(t)} for t in ("forecasts", "twin_states", "observations", "reconciliations")}
    assert ("forecast_id",) in idx["observations"] and ("forecast_id",) in idx["reconciliations"] and ("twin_id", "meal_time") in idx["forecasts"]
    fks = {fk["referred_table"] for fk in insp.get_foreign_keys("forecasts")}
    assert fks == {"twins"}
    assert TestClient(a).get("/health").json()["status"] == "ok"
    assert (tmp_path / "new" / "nested" / "fresh.sqlite3").exists()


def test_reinitialising_a_populated_database_changes_no_row_and_drops_no_table(tmp_path, capsys):
    url = f"sqlite:///{(tmp_path / 'pop.sqlite3').as_posix()}"
    a = make_app(tmp_path, url)
    c = TestClient(a)
    t1, t2 = new_twin(c, "keep-1"), new_twin(c, "keep-2")
    cycle(c, t1, 0, peak=200)
    c.post(f"/twins/{t1}/forecast", json=meal(1))
    c.post(f"/twins/{t1}/what-if", json={"scenarios": [{"carbs_g": 40, "activity_level": 0.4}], "baseline_glucose": 100})
    before = _dump(a.state.engine)
    assert all(before[t] for t in ("twins", "twin_states", "parameter_snapshots", "forecasts", "observations", "reconciliations", "what_if_runs", "data_quality_flags"))
    from glycotwin.backend.db import init_db
    init_db(a.state.engine)                                                                    # function, repeated
    init_db(a.state.engine)
    make_app(tmp_path, url)                                                                    # application start-up, repeated
    mod = _load_script("init_db")
    assert mod.main(["--database-url", url]) == 0                                              # script, without and with --demo
    assert mod.main(["--database-url", url, "--demo"]) == 0
    capsys.readouterr()
    after = _dump(a.state.engine)
    demo_twin_rows = [r for r in after["twins"] if "demo-synthetic-001" in r]
    assert len(demo_twin_rows) == 1                                                            # the demo is ADDED (new rows), existing rows untouched
    for t in TABLES:
        assert set(before[t]) <= set(after[t]), t                                              # every pre-existing row is still there, unchanged
    only_new = [r for r in after["twins"] if r not in before["twins"]]
    assert len(only_new) == 1 and set(inspect(a.state.engine).get_table_names()) == TABLES
    assert mod.main(["--database-url", url, "--demo"]) == 0                                    # now a pure no-op
    capsys.readouterr()
    assert _dump(a.state.engine) == after
    assert c.get(f"/twins/{t1}/history").json()["data"]["versions"][1]["parent_version"] == 0


def test_init_never_issues_drop_or_delete_statements():
    import re
    for f in ("src/glycotwin/backend/db.py", "scripts/init_db.py", "src/glycotwin/backend/app.py"):
        text = (ROOT / f).read_text(encoding="utf-8")
        assert not re.search(r"drop_all|DROP\s+TABLE|DELETE\s+FROM|\.delete\(|remove\(|unlink\(|rmtree", text, re.I), f
