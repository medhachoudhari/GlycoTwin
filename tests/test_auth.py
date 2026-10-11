"""Stage A: accounts and sessions. Every test uses a temporary database (never the real one) and fake credentials."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from glycotwin.backend import security
from glycotwin.backend.app import create_app
from glycotwin.backend.config import Settings
from glycotwin.backend.db import Base

PW = "correct-horse-battery"
REG = {"name": "Test User", "email": "Test.User@Example.com", "password": PW}


def make_app(tmp_path, **kw):
    prior = tmp_path / "priors"
    prior.mkdir(exist_ok=True)
    return create_app(Settings(database_url=f"sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}", prior_dir=prior, **kw))


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    return TestClient(app)


def db_path(tmp_path):
    return tmp_path / "db.sqlite3"


def rows(tmp_path, sql, *args):
    con = sqlite3.connect(db_path(tmp_path))
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


# ------------------------------------------------------------------ password hashing and tokens (unit)

def test_password_hash_is_scrypt_salted_and_never_the_plaintext():
    h1, h2 = security.hash_password(PW), security.hash_password(PW)
    assert h1.startswith("scrypt$32768$8$1$") and PW not in h1
    assert h1 != h2                                                      # a random salt per password
    assert security.verify_password(PW, h1) and security.verify_password(PW, h2)
    assert not security.verify_password(PW + "x", h1)
    assert not security.verify_password(PW, "") and not security.verify_password(PW, None) and not security.verify_password(PW, "not$a$hash")
    assert not security.verify_password(PW, "bcrypt$1$2$3$aa$bb")
    assert not security.needs_rehash(h1)
    assert security.needs_rehash(security.hash_password(PW, n=2 ** 14))  # older, cheaper parameters are flagged for an upgrade at next sign-in


def test_password_policy_is_length_based_and_honest():
    assert security.password_problem("short") and "at least 10" in security.password_problem("short")
    assert "at most 128" in security.password_problem("x" * 129)
    assert security.password_problem("a@b.co1234", email="a@b.co1234")
    assert security.password_problem("aaaaaaaaaaaa")
    assert security.password_problem(PW) is None
    assert security.password_problem("Spaces and symbols !? ok") is None  # no composition rules


def test_session_tokens_are_random_and_only_their_hash_is_comparable():
    t1, t2 = security.new_token(), security.new_token()
    assert t1 != t2 and len(t1) >= 40
    assert security.hash_token(t1) != t1 and len(security.hash_token(t1)) == 64


def test_throttle_blocks_after_the_limit_and_clears():
    th = security.Throttle(3, 60)
    for _ in range(3):
        assert th.retry_after("k") == 0
        th.record("k")
    assert th.retry_after("k") > 0 and th.retry_after("other") == 0
    th.clear("k")
    assert th.retry_after("k") == 0


# ------------------------------------------------------------------ registration

def test_register_creates_an_account_signs_in_and_never_returns_or_stores_the_password(client, tmp_path):
    r = client.post("/auth/register", json=REG)
    assert r.status_code == 201
    body = r.json()
    assert "disclaimer" in body
    u = body["data"]["user"]
    assert u["name"] == "Test User" and u["email"] == "test.user@example.com" and u["is_guest"] is False
    assert PW not in r.text and "password" not in str(u).lower() and "hash" not in str(u).lower()
    c = r.headers["set-cookie"].lower()
    assert "glycotwin_session=" in c and "httponly" in c and "samesite=lax" in c and "path=/" in c and "secure" not in c.replace("samesite", "")
    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["data"]["user"]["id"] == u["id"]
    (stored,) = rows(tmp_path, "select password_hash from users where id=?", u["id"])[0]
    assert stored.startswith("scrypt$") and PW not in stored
    assert PW.encode() not in db_path(tmp_path).read_bytes()             # the plaintext appears nowhere in the database file


def test_session_token_is_not_stored_only_its_hash(client, tmp_path):
    client.post("/auth/register", json=REG)
    token = client.cookies.get("glycotwin_session")
    assert token and token.encode() not in db_path(tmp_path).read_bytes()
    assert rows(tmp_path, "select count(*) from sessions where token_hash=?", security.hash_token(token))[0][0] == 1


def test_register_rejects_duplicate_email_case_insensitively_and_bad_input(client):
    assert client.post("/auth/register", json=REG).status_code == 201
    dup = client.post("/auth/register", json={**REG, "email": "TEST.USER@EXAMPLE.COM", "name": "Other"})
    assert dup.status_code == 409 and "already exists" in dup.json()["detail"]
    for bad, why in [({"password": "short"}, "short"), ({"password": "x" * 200}, "long"), ({"email": "nope"}, "email"), ({"email": ""}, "empty email"), ({"name": "  "}, "blank name"),
                     ({"name": "a" * 81}, "long name"), ({"name": "bad\x01name"}, "control char"), ({"password": "fresh@example.com", "email": "fresh@example.com"}, "password = email")]:
        r = client.post("/auth/register", json={**REG, "email": "new@example.com", **bad})
        assert r.status_code == 422, (why, r.text)
    assert client.post("/auth/register", json={**REG, "email": "x@example.com", "admin": True}).status_code == 422     # unknown fields refused
    assert client.post("/auth/register", json={"name": "A"}).status_code == 422


def test_register_can_be_switched_off(tmp_path):
    c = TestClient(make_app(tmp_path, allow_registration=False))
    r = c.post("/auth/register", json=REG)
    assert r.status_code == 403 and "disabled" in r.json()["detail"]


def test_secure_cookie_flag_follows_the_setting(tmp_path):
    c = TestClient(make_app(tmp_path, cookie_secure=True))
    assert "secure" in c.post("/auth/register", json=REG).headers["set-cookie"].lower().replace("samesite", "")


# ------------------------------------------------------------------ login, logout, sessions

def test_login_success_and_generic_failures(app):
    TestClient(app).post("/auth/register", json=REG)
    c = TestClient(app)
    assert c.get("/auth/me").status_code == 401 and c.get("/auth/me").json()["detail"] == "not signed in"
    ok = c.post("/auth/login", json={"email": "TEST.user@example.com ", "password": PW})
    assert ok.status_code == 200 and ok.json()["data"]["user"]["email"] == "test.user@example.com" and c.get("/auth/me").status_code == 200
    wrong = TestClient(app).post("/auth/login", json={"email": REG["email"], "password": PW + "!"})
    unknown = TestClient(app).post("/auth/login", json={"email": "nobody@example.com", "password": PW})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "incorrect email or password"       # no hint whether the email exists
    assert "set-cookie" not in wrong.headers


def test_repeated_failed_logins_are_throttled_per_email(app):
    TestClient(app).post("/auth/register", json=REG)
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/auth/login", json={"email": REG["email"], "password": "wrong-password-1"}).status_code == 401
    blocked = c.post("/auth/login", json={"email": REG["email"], "password": PW})              # even the right password waits
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    other = TestClient(app).post("/auth/login", json={"email": "someone.else@example.com", "password": "wrong-password-1"})
    assert other.status_code == 401                                                              # another email is not affected


def test_a_successful_login_resets_the_failure_count(app):
    TestClient(app).post("/auth/register", json=REG)
    c = TestClient(app)
    for _ in range(4):
        c.post("/auth/login", json={"email": REG["email"], "password": "wrong-password-1"})
    assert c.post("/auth/login", json={"email": REG["email"], "password": PW}).status_code == 200
    for _ in range(4):
        assert c.post("/auth/login", json={"email": REG["email"], "password": "wrong-password-1"}).status_code == 401


def test_logout_revokes_the_session_on_the_server(app):
    c = TestClient(app)
    c.post("/auth/register", json=REG)
    old = c.cookies.get("glycotwin_session")
    out = c.post("/auth/logout")
    assert out.status_code == 200 and out.json()["data"]["signed_out"] is True
    assert "glycotwin_session" in out.headers["set-cookie"].lower() and ("max-age=0" in out.headers["set-cookie"].lower() or "expires" in out.headers["set-cookie"].lower())
    stolen = TestClient(app)
    stolen.cookies.set("glycotwin_session", old)                                                 # replaying the old token must fail: revoked server-side
    assert stolen.get("/auth/me").status_code == 401
    assert TestClient(app).post("/auth/logout").status_code == 200                               # idempotent without a session


def test_each_login_is_a_new_independent_session(app):
    TestClient(app).post("/auth/register", json=REG)
    a, b = TestClient(app), TestClient(app)
    a.post("/auth/login", json={"email": REG["email"], "password": PW})
    b.post("/auth/login", json={"email": REG["email"], "password": PW})
    assert a.cookies.get("glycotwin_session") != b.cookies.get("glycotwin_session")
    a.post("/auth/logout")
    assert a.get("/auth/me").status_code == 401 and b.get("/auth/me").status_code == 200


def test_expired_sessions_are_refused(app, tmp_path):
    c = TestClient(app)
    c.post("/auth/register", json=REG)
    assert c.get("/auth/me").status_code == 200
    con = sqlite3.connect(db_path(tmp_path))
    con.execute("update sessions set expires_at = datetime('now', '-1 minute')")
    con.commit(); con.close()
    assert c.get("/auth/me").status_code == 401


def test_a_tampered_or_unknown_token_is_refused(app):
    c = TestClient(app)
    c.cookies.set("glycotwin_session", "not-a-real-token")
    assert c.get("/auth/me").status_code == 401


def test_account_and_sign_in_persist_across_sessions_and_a_server_restart(tmp_path):
    first = TestClient(make_app(tmp_path))
    uid = first.post("/auth/register", json=REG).json()["data"]["user"]["id"]
    first.post("/auth/logout")
    restarted = TestClient(make_app(tmp_path))                                                   # a brand-new app object on the same database file
    r = restarted.post("/auth/login", json={"email": REG["email"], "password": PW})
    assert r.status_code == 200 and r.json()["data"]["user"]["id"] == uid
    assert restarted.get("/auth/me").json()["data"]["user"]["name"] == "Test User"


def test_old_password_hash_parameters_are_upgraded_at_login(app, tmp_path):
    TestClient(app).post("/auth/register", json=REG)
    weak = security.hash_password(PW, n=2 ** 14)
    con = sqlite3.connect(db_path(tmp_path)); con.execute("update users set password_hash=?", (weak,)); con.commit(); con.close()
    assert TestClient(app).post("/auth/login", json={"email": REG["email"], "password": PW}).status_code == 200
    (now,) = rows(tmp_path, "select password_hash from users")[0]
    assert now.startswith("scrypt$32768$8$1$") and now != weak


# ------------------------------------------------------------------ cross-site protection and content type

def test_cross_origin_posts_are_refused_but_same_origin_and_scripts_work(app):
    c = TestClient(app)
    evil = c.post("/auth/login", json={"email": REG["email"], "password": PW}, headers={"Origin": "http://evil.example"})
    assert evil.status_code == 403
    assert c.post("/auth/register", json=REG, headers={"Origin": "http://testserver"}).status_code == 201   # same host as the request
    assert c.post("/auth/logout", headers={"Origin": "http://evil.example"}).status_code == 403


def test_form_encoded_posts_are_not_accepted(client):
    r = client.post("/auth/login", data={"email": REG["email"], "password": PW})
    assert r.status_code == 422


# ------------------------------------------------------------------ guest (demonstration) accounts

def test_guest_account_is_temporary_isolated_and_cannot_be_signed_in_to(app, tmp_path):
    g1, g2 = TestClient(app), TestClient(app)
    r1, r2 = g1.post("/auth/guest"), g2.post("/auth/guest")
    assert r1.status_code == r2.status_code == 201
    u1, u2 = r1.json()["data"]["user"], r2.json()["data"]["user"]
    assert u1["is_guest"] is True and u1["email"] is None and u1["id"] != u2["id"]
    assert g1.get("/auth/me").json()["data"]["user"]["id"] == u1["id"] and g2.get("/auth/me").json()["data"]["user"]["id"] == u2["id"]
    assert rows(tmp_path, "select password_hash from users where id=?", u1["id"])[0][0] is None
    assert TestClient(app).post("/auth/login", json={"email": "guest", "password": PW}).status_code in (401, 422)
    hours = rows(tmp_path, "select (julianday(expires_at)-julianday(created_at))*24 from sessions limit 1")[0][0]
    assert 23 < hours < 25                                                                         # guest sessions last guest_hours (24), not days


def test_guest_access_can_be_switched_off_and_is_rate_limited(tmp_path):
    off, on = tmp_path / "off", tmp_path / "on"
    off.mkdir(); on.mkdir()
    assert TestClient(make_app(off, allow_guest=False)).post("/auth/guest").status_code == 403
    c = TestClient(make_app(on))
    codes = [c.post("/auth/guest").status_code for _ in range(21)]
    assert codes[:20] == [201] * 20 and codes[20] == 429


# ------------------------------------------------------------------ database safety (additive only)

OLD_TABLES = {"twins", "twin_states", "parameter_snapshots", "forecasts", "observations", "reconciliations", "what_if_runs", "data_quality_flags"}


def _legacy_twin_with_a_forecast(app):
    """A twin made the way it was BEFORE accounts existed: created by the service layer with no owner, plus one forecast."""
    from glycotwin.backend import services
    from glycotwin.backend.schemas import ForecastRequest, TwinCreate
    s = app.state.session_factory()
    try:
        tid = services.create_twin(s, app.state.settings, TwinCreate(label="legacy-twin"))["twin_id"]
        services.forecast(s, tid, ForecastRequest(event_id="m1", meal_time="2026-01-01T08:00:00", carbs_g=60, activity_level=0.3, baseline_glucose=110))
        return tid
    finally:
        s.close()


def test_upgrade_only_adds_tables_and_leaves_existing_rows_and_columns_unchanged(tmp_path):
    _legacy_twin_with_a_forecast(make_app(tmp_path))
    # simulate a database created BEFORE accounts existed: remove only the three new tables
    con = sqlite3.connect(db_path(tmp_path))
    for t in ("twin_owners", "sessions", "users"):
        con.execute(f"drop table {t}")
    con.commit(); con.close()

    def snapshot():
        con = sqlite3.connect(db_path(tmp_path))
        try:
            out = {}
            for t in sorted(OLD_TABLES):
                out[t] = (con.execute(f"pragma table_info({t})").fetchall(), con.execute(f"select * from {t} order by 1").fetchall())
            return out, {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        finally:
            con.close()
    before, tables_before = snapshot()
    assert not ({"users", "sessions", "twin_owners"} & tables_before)
    TestClient(make_app(tmp_path))                                                               # start-up creates the missing tables
    after, tables_after = snapshot()
    assert before == after                                                                       # existing tables: same columns, same rows
    assert tables_after - tables_before == {"users", "sessions", "twin_owners"}
    TestClient(make_app(tmp_path))                                                               # running it again changes nothing
    again, tables_again = snapshot()
    assert again == after and tables_again == tables_after
    assert rows(tmp_path, "select label from twins")[0][0] == "legacy-twin"
    assert rows(tmp_path, "select count(*) from twin_owners")[0][0] == 0                         # the old twin was NOT given to anyone


def test_the_twins_table_definition_is_unchanged(tmp_path):
    make_app(tmp_path)
    cols = [r[1] for r in rows(tmp_path, "pragma table_info(twins)")]
    assert cols == ["id", "label", "created_at", "prior_source", "prior_scheme", "gamma_relative_sd", "prior_provenance", "profile", "config", "is_synthetic"]


def test_new_tables_are_registered_and_foreign_keys_cascade(app, tmp_path):
    assert {"users", "sessions"} <= set(Base.metadata.tables)
    c = TestClient(app)
    uid = c.post("/auth/register", json=REG).json()["data"]["user"]["id"]
    con = sqlite3.connect(db_path(tmp_path)); con.execute("pragma foreign_keys=on")
    con.execute("delete from users where id=?", (uid,)); con.commit()
    assert con.execute("select count(*) from sessions").fetchone()[0] == 0                       # sessions cannot outlive their user
    con.close()
