"""Stage B: twin ownership and route protection. Every test uses a temporary database and fake accounts. Nothing here touches a real database."""

from __future__ import annotations

import json
import sqlite3
import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from glycotwin.backend.app import create_app
from glycotwin.backend.config import Settings
from glycotwin.backend.deps import owned_twin_id
from glycotwin.backend.models import TwinOwner
from glycotwin.backend.ownership import ClaimError, claim_twin, list_unowned

OLD_TABLES = ("twins", "twin_states", "parameter_snapshots", "forecasts", "observations", "reconciliations", "what_if_runs", "data_quality_flags")
UNKNOWN = "123e4567-e89b-12d3-a456-426614174000"


def make_app(tmp_path):
    prior = tmp_path / "priors"
    prior.mkdir(exist_ok=True)
    return create_app(Settings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}", prior_dir=prior))


def register(app, name, email, password="a-long-test-passphrase"):
    c = TestClient(app)
    r = c.post("/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return c


def login(app, email, password="a-long-test-passphrase"):
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": email, "password": password}).status_code == 200
    return c


def meal(i=0, **kw):
    return {"event_id": f"own-meal-{i}", "meal_time": f"2026-01-0{i + 1}T08:00:00", "carbs_g": 60, "activity_level": 0.3, "baseline_glucose": 110, **kw}


def build_history(c, label="alice-twin"):
    """A full life for one twin: forecast -> observe -> apply (version 1), a second forecast, and an excluded meal."""
    tid = c.post("/twins", json={"label": label}).json()["data"]["twin_id"]
    f1 = c.post(f"/twins/{tid}/forecast", json=meal(0)).json()["data"]
    assert c.post(f"/twins/{tid}/observe", json={"forecast_id": f1["forecast_id"], "observed_through": "2026-01-01T10:00:00", "peak_glucose_mg_dl": 190}).status_code == 201
    assert c.post(f"/twins/{tid}/reconcile", json={"forecast_id": f1["forecast_id"]}).status_code == 201
    f2 = c.post(f"/twins/{tid}/forecast", json=meal(2)).json()["data"]
    f3 = c.post(f"/twins/{tid}/forecast", json=meal(3)).json()["data"]
    assert c.post(f"/twins/{tid}/observe", json={"forecast_id": f3["forecast_id"], "observed_through": "2026-01-04T10:00:00", "excluded_reason": "sensor gap over 30 minutes"}).status_code == 201
    return tid, f1["forecast_id"], f2["forecast_id"]


def dump(tmp_path, tables=OLD_TABLES):
    con = sqlite3.connect(tmp_path / "db.sqlite3")
    try:
        return {t: con.execute(f"select * from {t} order by 1").fetchall() for t in tables}
    finally:
        con.close()


def twin_routes(app):
    """Every (method, path) in the live OpenAPI document that is scoped to a twin: the test enumerates them so a future route cannot be forgotten."""
    out = []
    for path, ops in app.openapi()["paths"].items():
        if "{twin_id}" in path:
            for m in ops:
                out.append((m.upper(), path))
    return sorted(out)


def call(c, method, path, tid, fid):
    url = path.replace("{twin_id}", tid).replace("{forecast_id}", fid)
    if method == "GET":
        return c.get(url + ("?activities=0,1" if url.endswith("/sensitivity") else ""))
    return c.request(method, url, json={})


@pytest.fixture
def world(tmp_path):
    app = make_app(tmp_path)
    alice = register(app, "Alice", "alice@example.com")
    tid, f_done, f_pending = build_history(alice)
    return {"app": app, "tmp": tmp_path, "alice": alice, "tid": tid, "f_done": f_done, "f_pending": f_pending}


# ------------------------------------------------------------------ the safety net: every twin route is protected

def test_every_twin_route_has_the_ownership_check_in_front_of_it(tmp_path):
    from glycotwin.backend.routers import twins as twins_module                                  # newer FastAPI wraps included routers, so inspect the router itself
    make_app(tmp_path)
    found = 0
    for route in twins_module.router.routes:
        if isinstance(route, APIRoute) and "{twin_id}" in route.path:
            found += 1
            stack, seen = list(route.dependant.dependencies), False
            while stack:
                d = stack.pop()
                seen = seen or d.call is owned_twin_id
                stack.extend(d.dependencies)
            assert seen, f"{route.methods} {route.path} is missing owned_twin_id"
    assert found >= 10


def test_the_openapi_route_list_is_what_the_tests_expect(world):
    routes = twin_routes(world["app"])
    assert len(routes) >= 10 and ("GET", "/twins/{twin_id}/sensitivity") in routes and ("POST", "/twins/{twin_id}/what-if") in routes
    assert ("POST", "/twins/{twin_id}/observe") in routes and ("POST", "/twins/{twin_id}/reconcile") in routes and ("GET", "/twins/{twin_id}/history") in routes


# ------------------------------------------------------------------ not signed in

def test_nobody_signed_in_is_rejected_on_every_twin_route_and_on_create_and_list(world):
    anon = TestClient(world["app"])
    for method, path in twin_routes(world["app"]):
        r = call(anon, method, path, world["tid"], world["f_done"])
        assert r.status_code == 401 and r.json()["detail"] == "not signed in", (method, path, r.status_code)
    assert anon.get("/twins").status_code == 401
    assert anon.post("/twins", json={"label": "anon-twin"}).status_code == 401
    assert anon.post("/twins", json={"label": "anon-twin"}).json()["detail"] == "not signed in"
    # a malformed id does not change that (still 401, not a hint about the id format)
    assert anon.get("/twins/abc").status_code == 401


def test_after_logout_or_with_an_expired_session_the_owner_is_locked_out_too(world, tmp_path):
    alice = world["alice"]
    assert alice.get(f"/twins/{world['tid']}").status_code == 200
    con = sqlite3.connect(world["tmp"] / "db.sqlite3"); con.execute("update sessions set expires_at = datetime('now', '-1 minute')"); con.commit(); con.close()
    assert alice.get(f"/twins/{world['tid']}").status_code == 401
    again = login(world["app"], "alice@example.com")
    assert again.get(f"/twins/{world['tid']}").status_code == 200
    again.post("/auth/logout")
    assert again.get(f"/twins/{world['tid']}").status_code == 401 and again.get("/twins").status_code == 401


# ------------------------------------------------------------------ User B cannot list, read, modify or infer

def test_user_b_gets_the_same_404_for_alices_twin_as_for_a_twin_that_does_not_exist(world):
    bob = register(world["app"], "Bob", "bob@example.com")
    for method, path in twin_routes(world["app"]):
        theirs = call(bob, method, path, world["tid"], world["f_done"])
        nothing = call(bob, method, path, UNKNOWN, world["f_done"])
        assert theirs.status_code == nothing.status_code == 404, (method, path, theirs.status_code)
        assert theirs.json() == nothing.json() == {"detail": "twin not found", "disclaimer": theirs.json()["disclaimer"]}      # no way to tell "not mine" from "does not exist"


def test_user_b_cannot_list_alices_twins(world):
    bob = register(world["app"], "Bob", "bob@example.com")
    assert bob.get("/twins").json()["data"]["twins"] == []
    mine = world["alice"].get("/twins").json()["data"]["twins"]
    assert [t["twin_id"] for t in mine] == [world["tid"]] and mine[0]["label"] == "alice-twin" and mine[0]["current_version"] == 1
    bob_twin = bob.post("/twins", json={"label": "bob-twin"}).json()["data"]["twin_id"]
    assert [t["twin_id"] for t in bob.get("/twins").json()["data"]["twins"]] == [bob_twin]
    assert [t["twin_id"] for t in world["alice"].get("/twins").json()["data"]["twins"]] == [world["tid"]]                  # and Alice does not see Bob's


def test_user_b_cannot_modify_anything_of_alices(world):
    bob = register(world["app"], "Bob", "bob@example.com")
    before = dump(world["tmp"])
    tid, f_pending = world["tid"], world["f_pending"]
    attempts = [("POST", f"/twins/{tid}/forecast", meal(7)), ("POST", f"/twins/{tid}/observe", {"forecast_id": f_pending, "observed_through": "2026-01-03T10:00:00", "peak_glucose_mg_dl": 150}),
                ("POST", f"/twins/{tid}/reconcile", {"forecast_id": f_pending}), ("POST", f"/twins/{tid}/what-if", {"baseline_glucose": 110, "scenarios": [{"carbs_g": 50, "activity_level": 0.2}]})]
    for method, url, body in attempts:
        assert bob.request(method, url, json=body).status_code == 404
    assert dump(world["tmp"]) == before                                                         # not one row of any research table changed
    assert world["alice"].get(f"/twins/{tid}").json()["data"]["state"]["historical_response_state"]["version_number"] == 1


def test_a_forecast_id_from_another_user_is_useless_even_inside_bobs_own_twin(world):
    bob = register(world["app"], "Bob", "bob@example.com")
    bt = bob.post("/twins", json={"label": "bob-twin"}).json()["data"]["twin_id"]
    unknown = str(uuid.uuid4())
    for url, method, body in [(f"/twins/{bt}/forecasts/{world['f_done']}/explanation", "GET", None),
                              (f"/twins/{bt}/observe", "POST", {"forecast_id": world["f_pending"], "observed_through": "2026-01-03T10:00:00", "peak_glucose_mg_dl": 150}),
                              (f"/twins/{bt}/reconcile", "POST", {"forecast_id": world["f_done"]})]:
        r = bob.request(method, url, json=body) if body else bob.get(url)
        same_shape = bob.request(method, url.replace(world["f_done"], unknown).replace(world["f_pending"], unknown), json=(json.loads(json.dumps(body).replace(world["f_pending"], unknown).replace(world["f_done"], unknown)) if body else None)) if body else bob.get(url.replace(world["f_done"], unknown))
        assert r.status_code == same_shape.status_code == 404 and r.json()["detail"] == same_shape.json()["detail"]   # A's forecast looks exactly like one that does not exist


def test_bobs_data_never_contains_alices_data(world):
    bob = register(world["app"], "Bob", "bob@example.com")
    bt = bob.post("/twins", json={"label": "bob-twin"}).json()["data"]["twin_id"]
    assert bob.get(f"/twins/{bt}/forecasts").json()["data"]["total"] == 0
    assert len(bob.get(f"/twins/{bt}/history").json()["data"]["versions"]) == 1
    everything = json.dumps([bob.get("/twins").json(), bob.get(f"/twins/{bt}").json(), bob.get(f"/twins/{bt}/forecasts").json(), bob.get(f"/twins/{bt}/reconciliations").json()])
    assert world["tid"] not in everything and world["f_done"] not in everything and "alice" not in everything.lower()


def test_the_only_thing_user_b_can_learn_is_that_a_label_is_taken(world):
    """A KNOWN, accepted limitation (labels are globally unique for now): creating a twin with Alice's label returns 409. It reveals the label exists, never the id or any data."""
    bob = register(world["app"], "Bob", "bob@example.com")
    r = bob.post("/twins", json={"label": "alice-twin"})
    assert r.status_code == 409 and world["tid"] not in r.text and "alice@example.com" not in r.text
    assert bob.get("/twins").json()["data"]["twins"] == []


# ------------------------------------------------------------------ the owner keeps full, persistent access

def test_the_owner_can_use_every_route_and_gets_the_same_data_after_signing_out_and_in_and_after_a_restart(world, tmp_path):
    a = world["alice"]
    tid = world["tid"]
    reads = [f"/twins/{tid}", f"/twins/{tid}/history", f"/twins/{tid}/forecasts", f"/twins/{tid}/reconciliations", f"/twins/{tid}/sensitivity?activities=0,0.5,1",
             f"/twins/{tid}/forecasts/{world['f_done']}/explanation?model=model_c"]
    first = {u: a.get(u).json() for u in reads}
    assert all(a.get(u).status_code == 200 for u in reads)
    assert a.post(f"/twins/{tid}/what-if", json={"baseline_glucose": 110, "scenarios": [{"carbs_g": 50, "activity_level": 0.2}]}).status_code == 200
    a.post("/auth/logout")
    second_client = login(world["app"], "alice@example.com")                                    # a new sign-in later
    assert {u: second_client.get(u).json() for u in reads} == first
    restarted = login(make_app(world["tmp"]), "alice@example.com")                              # a new server process on the same database file
    assert {u: restarted.get(u).json() for u in reads} == first
    assert [t["twin_id"] for t in restarted.get("/twins").json()["data"]["twins"]] == [tid]
    forecasts = restarted.get(f"/twins/{tid}/forecasts").json()["data"]
    assert forecasts["total"] == 3
    assert sorted(f["status"] for f in forecasts["forecasts"]) == ["observed", "pending", "reconciled"]
    assert len(restarted.get(f"/twins/{tid}/history").json()["data"]["versions"]) == 2


def test_creating_a_twin_records_its_owner_in_the_same_step(world):
    con = sqlite3.connect(world["tmp"] / "db.sqlite3")
    uid = con.execute("select id from users where email='alice@example.com'").fetchone()[0]
    assert con.execute("select user_id, source from twin_owners where twin_id=?", (world["tid"],)).fetchall() == [(uid, "created")]
    assert con.execute("select count(*) from twins").fetchone()[0] == con.execute("select count(*) from twin_owners").fetchone()[0] == 1
    con.close()


def test_a_twin_can_have_only_one_owner(world):
    bob = register(world["app"], "Bob", "bob@example.com")
    bob_id = bob.get("/auth/me").json()["data"]["user"]["id"]
    s = world["app"].state.session_factory()
    try:
        s.add(TwinOwner(twin_id=world["tid"], user_id=bob_id, source="claimed"))
        with pytest.raises(IntegrityError):
            s.commit()
    finally:
        s.rollback(); s.close()
    assert bob.get(f"/twins/{world['tid']}").status_code == 404


# ------------------------------------------------------------------ guests have the same protection

def test_a_guest_is_isolated_in_both_directions(world):
    guest = TestClient(world["app"])
    assert guest.post("/auth/guest").status_code == 201
    for method, path in twin_routes(world["app"]):
        assert call(guest, method, path, world["tid"], world["f_done"]).status_code == 404
    assert guest.get("/twins").json()["data"]["twins"] == []
    gt = guest.post("/twins", json={"label": "guest-twin"}).json()["data"]["twin_id"]
    assert guest.get(f"/twins/{gt}").status_code == 200
    assert world["alice"].get(f"/twins/{gt}").status_code == 404                                # Alice cannot see the guest's twin
    other_guest = TestClient(world["app"]); other_guest.post("/auth/guest")
    assert other_guest.get(f"/twins/{gt}").status_code == 404 and other_guest.get("/twins").json()["data"]["twins"] == []


# ------------------------------------------------------------------ old (unowned) twins stay hidden until claimed

def _unowned_twin(app, label="legacy-twin"):
    from glycotwin.backend import services
    from glycotwin.backend.schemas import ForecastRequest, TwinCreate
    s = app.state.session_factory()
    try:
        tid = services.create_twin(s, app.state.settings, TwinCreate(label=label))["twin_id"]
        services.forecast(s, tid, ForecastRequest(event_id="old-1", meal_time="2026-01-01T08:00:00", carbs_g=60, activity_level=0.3, baseline_glucose=110))
        return tid
    finally:
        s.close()


def test_unowned_twins_are_hidden_from_everyone_and_nothing_is_assigned_automatically(tmp_path):
    app = make_app(tmp_path)
    old = _unowned_twin(app)
    first_user = register(app, "First", "first@example.com")                                  # the first account ever registered must NOT inherit old twins
    second_user = register(app, "Second", "second@example.com")
    guest = TestClient(app); guest.post("/auth/guest")
    for c in (first_user, second_user, guest):
        assert c.get("/twins").json()["data"]["twins"] == []
        assert c.get(f"/twins/{old}").status_code == 404 and c.get(f"/twins/{old}/history").status_code == 404
    assert TestClient(app).get(f"/twins/{old}").status_code == 401
    assert dump(tmp_path)["twins"] and sqlite3.connect(tmp_path / "db.sqlite3").execute("select count(*) from twin_owners").fetchone()[0] == 0


# ------------------------------------------------------------------ the claim tool

def _claim_world(tmp_path):
    app = make_app(tmp_path)
    old = _unowned_twin(app)
    alice, bob = register(app, "Alice", "alice@example.com"), register(app, "Bob", "bob@example.com")
    return app, old, alice, bob


def test_claim_dry_run_changes_nothing_and_apply_gives_the_twin_to_exactly_one_person(tmp_path):
    app, old, alice, bob = _claim_world(tmp_path)
    before = dump(tmp_path)
    s = app.state.session_factory()
    try:
        res = claim_twin(s, old, "Alice@Example.com", apply=False)
        assert res["applied"] is False and res["claimed_by"] == "alice@example.com"
        assert alice.get(f"/twins/{old}").status_code == 404                                    # dry run: still hidden
        assert [t["twin_id"] for t in list_unowned(s)] == [old]
        res = claim_twin(s, old, "alice@example.com", apply=True)
        assert res["applied"] is True
    finally:
        s.close()
    assert alice.get(f"/twins/{old}").status_code == 200 and alice.get("/twins").json()["data"]["twins"][0]["twin_id"] == old
    assert bob.get(f"/twins/{old}").status_code == 404 and bob.get("/twins").json()["data"]["twins"] == []
    assert dump(tmp_path) == before                                                             # claiming wrote ONE ownership row and changed no research row
    assert sqlite3.connect(tmp_path / "db.sqlite3").execute("select source from twin_owners").fetchall() == [("claimed",)]
    s = app.state.session_factory()
    try:
        assert list_unowned(s) == []
    finally:
        s.close()


def test_claim_can_never_transfer_or_overwrite_an_owned_twin(tmp_path):
    app, old, alice, bob = _claim_world(tmp_path)
    s = app.state.session_factory()
    try:
        claim_twin(s, old, "alice@example.com", apply=True)
        for who in ("bob@example.com", "alice@example.com"):                                     # a different person AND the same person again
            for apply in (False, True):
                with pytest.raises(ClaimError, match="already has an owner"):
                    claim_twin(s, old, who, apply=apply)
    finally:
        s.close()
    assert alice.get(f"/twins/{old}").status_code == 200 and bob.get(f"/twins/{old}").status_code == 404
    twin_made_by_alice = alice.post("/twins", json={"label": "created-by-alice"}).json()["data"]["twin_id"]
    s = app.state.session_factory()
    try:
        with pytest.raises(ClaimError, match="already has an owner"):                           # twins made through the API are owned from the start
            claim_twin(s, twin_made_by_alice, "bob@example.com", apply=True)
    finally:
        s.close()
    assert bob.get(f"/twins/{twin_made_by_alice}").status_code == 404


def test_claim_refuses_bad_requests_and_changes_nothing(tmp_path):
    app, old, _alice, _bob = _claim_world(tmp_path)
    s = app.state.session_factory()
    try:
        with pytest.raises(ClaimError, match="no twin"):
            claim_twin(s, UNKNOWN, "alice@example.com", apply=True)
        with pytest.raises(ClaimError, match="no account"):
            claim_twin(s, old, "nobody@example.com", apply=True)
        with pytest.raises(ClaimError, match="no account"):                                     # guests have no email at all, so they can never be targeted by email
            claim_twin(s, old, "", apply=True)
        assert [t["twin_id"] for t in list_unowned(s)] == [old]
    finally:
        s.close()
    assert sqlite3.connect(tmp_path / "db.sqlite3").execute("select count(*) from twin_owners").fetchone()[0] == 0


def test_claim_script_lists_dry_runs_applies_and_refuses(tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("claim_twin_script", Path(__file__).resolve().parents[1] / "scripts" / "claim_twin.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    app, old, alice, bob = _claim_world(tmp_path)
    url = f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
    before = dump(tmp_path)
    assert mod.main(["--database-url", url, "--list-unowned"]) == 0
    listed = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert listed["count"] == 1 and listed["unowned_twins"][0]["twin_id"] == old and listed["unowned_twins"][0]["n_forecasts"] == 1
    assert mod.main(["--database-url", url, "--twin-id", old, "--email", "alice@example.com"]) == 0              # dry run by default
    assert "DRY RUN" in capsys.readouterr().out and alice.get(f"/twins/{old}").status_code == 404
    assert mod.main(["--database-url", url, "--twin-id", old, "--email", "alice@example.com", "--apply"]) == 0
    assert '"applied": true' in capsys.readouterr().out and alice.get(f"/twins/{old}").status_code == 200
    assert mod.main(["--database-url", url, "--twin-id", old, "--email", "bob@example.com", "--apply"]) == 2     # already owned: refused, exit code 2
    assert "REFUSED" in capsys.readouterr().err and bob.get(f"/twins/{old}").status_code == 404
    assert dump(tmp_path) == before
    with pytest.raises(SystemExit):                                                             # arguments are required
        mod.main(["--database-url", url])


# ------------------------------------------------------------------ existing rows unchanged; initialising again is safe

def test_restarting_the_app_changes_no_row_and_keeps_every_owner(world):
    before_rows = dump(world["tmp"], OLD_TABLES + ("users", "twin_owners"))
    make_app(world["tmp"]); make_app(world["tmp"])
    from glycotwin.backend.db import init_db
    init_db(world["app"].state.engine); init_db(world["app"].state.engine)
    assert dump(world["tmp"], OLD_TABLES + ("users", "twin_owners")) == before_rows
    assert login(world["app"], "alice@example.com").get(f"/twins/{world['tid']}").status_code == 200


def test_the_ownership_table_is_the_only_new_structure_and_twins_is_untouched(tmp_path):
    make_app(tmp_path)
    con = sqlite3.connect(tmp_path / "db.sqlite3")
    assert [r[1] for r in con.execute("pragma table_info(twins)")] == ["id", "label", "created_at", "prior_source", "prior_scheme", "gamma_relative_sd", "prior_provenance", "profile", "config", "is_synthetic"]
    assert [(r[1], r[5]) for r in con.execute("pragma table_info(twin_owners)")] == [("twin_id", 1), ("user_id", 0), ("source", 0), ("created_at", 0)]
    fks = {(r[2], r[3]) for r in con.execute("pragma foreign_key_list(twin_owners)")}
    assert fks == {("twins", "twin_id"), ("users", "user_id")}
    con.close()
