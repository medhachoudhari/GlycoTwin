# Backend architecture (FastAPI + SQLite)

Research software. Forecasts are experimental outputs of the GlycoTwin research prototype; not clinically validated; no diagnosis, no diet, medication or insulin advice.

```
HTTP client ──> FastAPI routers (backend/routers)      validation: Pydantic schemas (backend/schemas.py): units, ranges, id patterns, no extra fields
                   │
                   ▼
               services (backend/services.py)          one DB transaction per operation; rollback on any error; idempotency and leakage guards
                   │
                   ▼
               SqlTwinStore (backend/store.py)         the existing TwinStore interface, backed by SQLite, scoped to one twin
                   │
                   ▼
               existing engine, unchanged              twin/state.py forecast_meal / reconcile_forecast / exclude_forecast,
                                                       models/bayesian.py (conjugate update), twin/insight.py, twin/state_view.py, twin/quality.py
```

**One engine.** The services call the research engine's own functions; the Bayesian update, its guards and the forecast arithmetic are not re-implemented.
A test replays a whole lifecycle through the API and through the in-memory TwinStore and requires identical forecasts and posteriors.

## Tables
| Table | Holds | Key constraints |
|---|---|---|
| `twins` | pseudonymous label, prior source/scheme/gamma width and provenance, static profile (glycaemic group only), config, synthetic flag | label unique |
| `twin_states` | version, parent version, time, number of observations, reconciliation that produced it | unique (twin_id, version) |
| `parameter_snapshots` | Model B and C posterior (mean, covariance, noise, counts; beta/gamma summary columns) per version | unique (state, model) |
| `forecasts` | client event id, meal time, inputs, both models' probability, mean, sd and 90% interval, version used, model version, engine provenance, data quality | unique (twin_id, event_id) |
| `observations` | observed peak, derived rise and label, observed-through time, window completeness, exclusion reason | one per forecast |
| `reconciliations` | outcome (updated / excluded), versions before/after, hit, Brier component, interval coverage, standardised error | one per forecast, one per observation |
| `what_if_runs` | hypothetical scenarios, results, version used | never linked to a state change |
| `data_quality_flags` | forecast-time and observation-time findings with stage and code | FK to forecast / observation |
| `users` | accounts: id, display name, unique lower-case email, scrypt password hash (NULL for guests), `is_guest`, created / last sign-in time | unique email (several NULL emails allowed for guests) |
| `sessions` | one row per sign-in: SHA-256 of the session token, user, created / expires / revoked time | unique token hash; FK to `users` (cascade) |
| `twin_owners` | which account owns which twin: `twin_id` (primary key), `user_id`, `source` (`created` or `claimed`), created time | one owner per twin; FKs to `twins` and `users` (cascade deletes only the link) |
The last three tables were **added** for accounts and ownership; the eight research tables above them are unchanged (a test compares their columns and rows before and after the upgrade). Foreign keys are enforced (SQLite `PRAGMA foreign_keys=ON`). Initialisation (`init_db`, application start-up, `scripts/init_db.py`) only creates missing tables; it contains no drop or delete statement (tested), so repeating it never changes existing rows. No raw CGM traces are stored; only per-meal summaries.

## Lifecycle and guarantees
Every twin route below requires a signed-in session and that the twin belongs to the caller (see *Accounts, sessions and ownership*); a request without a session gets 401 and a twin that is not yours gets 404.
* `POST /twins/{id}/forecast`: forecast from the current version; a repeat with the same `event_id` and inputs returns the stored forecast (200), different inputs give 409.
  A forecast whose meal time is earlier than the close of an outcome window the twin already learned from is refused (409): it would see the future.
* `POST /twins/{id}/observe`: records the outcome only after the 120-minute window has closed (`observed_through`); rise and label are derived on the server from the forecast's
  baseline (label: peak >= 180 mg/dL); one observation per forecast (identical repeat 200, different 409). Observing never changes the twin.
* `POST /twins/{id}/reconcile`: applies the observation with the engine's `reconcile_forecast` (or `exclude_forecast` for an excluded meal, which never updates the twin), writing
  the new version, its parameters and the reconciliation in one transaction. Any failure rolls all of it back. Repeats return the stored reconciliation; the twin is updated exactly once.
  A concurrent second writer hits the unique (twin_id, version) constraint and receives 409 with nothing changed.
* `POST /twins/{id}/what-if`: runs the engine's pure what-if on the current version; stored as a run; the twin is not modified.

## Priors and leakage
A live twin starts from a population prior only, from (a) the simulated demo population (labelled synthetic) or (b) an aggregate prior artifact in `GLYCOTWIN_PRIOR_DIR`, written offline by
`scripts/export_prior.py` (means, covariances, noise, counts and provenance only; the API refuses artifacts that do not declare `contains_participant_level_data: false` or that carry other keys).
The export requires an explicit decision: exclude the live person if they are in the research data, or declare that they are not. No research replay outcome is used to initialise a live twin;
research replay (`scripts/replay_participant.py`) and interactive operation are separate code paths.

## Activity scale and the synthetic demo
Model C uses raw, un-centred activity (the research equations are unchanged). The synthetic demo prior is fitted on a SIMULATED 0-1 activity scale, not METs; real wrist-device METs are
typically 1-3 or more, where the demo's gamma would extrapolate (the predicted rise falls towards zero and below). A demo twin therefore **rejects** forecast and what-if requests with
`activity_level` outside [0, 1] (HTTP 422, nothing stored). A twin built from a prior file that records the fitted population's activity range (written by `scripts/export_prior.py`) is not
rejected outside that range but the forecast carries a low-data-quality reason, a stored `activity_outside_prior_range` flag and a warning; the forecast itself is not altered.

## Endpoints
Accounts and sessions (never touch twins): `POST /auth/register`, `POST /auth/login`, `POST /auth/guest`, `POST /auth/logout`, `GET /auth/me`.
Twins (**every one requires a signed-in session cookie; every `{id}` route also requires that the twin is yours**): `GET /twins` (lists only the caller's own twins), `POST /twins`,
`GET /twins/{id}`, `GET /twins/{id}/history`, `POST /twins/{id}/forecast`, `GET /twins/{id}/forecasts`, `POST /twins/{id}/observe`, `POST /twins/{id}/reconcile`,
`POST /twins/{id}/what-if`, `GET /twins/{id}/forecasts/{forecast_id}/explanation`, `GET /twins/{id}/sensitivity`, `GET /twins/{id}/reconciliations`.
Public: `GET /health`. There is no endpoint that lists other people's twins, unowned twins or research participants. Interactive docs: `/docs`.

## Innovation integration (this phase)
* **Reconcile → parameter_change**: the reconcile response now reports, for both Model B and Model C, the posterior mean and sd of beta (and gamma for C)
  before and after the update, with the sd ratio (< 1 means the observation narrowed the estimate). Computed from the two stored `parameter_snapshots` rows;
  nothing is recomputed outside the engine. Idempotent: a repeated reconcile call returns the same `parameter_change`, not a freshly computed one.
* **`GET /forecasts/{id}/explanation`**: calls the existing `twin.insight.explain_forecast_in_context` on an `AsOfStore`, a read-only view of the twin
  frozen at `twin_version_at_forecast`. This guarantees the explanation of an old forecast can never show what the twin learned afterwards, even if the
  forecast has since been reconciled. Returns the model's own additive terms, the parameter-vs-noise variance split, and the contributing-factor list
  (carbs, activity, trend, similar past meals); explicitly labelled "not a causal claim".
* **`GET /sensitivity`**: `twin.insight.effective_sensitivity` evaluated over a short list of activity values, with the beta-gamma covariance in the
  uncertainty (Model C) and the single Model B value. Subject to the same demo/prior-file activity-range enforcement as forecasts (`check_activity_support`).
* **`GET /reconciliations`**: `twin.insight.reconciliation_report` plus `hit_rate_trend` and the rolling calibration score from `twin_state_view`
  (forecast-vs-observed history, hits at the 50% threshold, Brier components, standardised errors). Descriptive; a few meals per person cannot assess calibration.
* **What-if `comparison` table**: the existing `insight.what_if` output, reshaped into a flat side-by-side table (one row per scenario, both models,
  deltas relative to the first/reference scenario). The simulation itself is unchanged and still never touches the twin.
All four reuse the existing read-only `twin.insight` / `twin.state_view` functions; no new uncertainty formula, confidence level, or clinical claim was added.

## Accounts, sessions and ownership (implemented)
* **Register / sign in:** `POST /auth/register` (name, email, password; signs you in, 201), `POST /auth/login`, `POST /auth/logout` (revokes the session on the server; idempotent), `GET /auth/me` (401 when nobody is signed in).
  Emails are stored lower-case and are unique. Passwords: 10 to 128 characters, not equal to the email or name, not trivially repetitive; there are no composition rules.
* **Password hashing:** Python's built-in `hashlib.scrypt` (N = 2^15, r = 8, p = 1, 16-byte random salt per password, about 0.15 s per check), stored as `scrypt$N$r$p$salt$hash`. The plaintext is never stored, logged or returned. Old cost settings are upgraded at the next successful sign-in. No extra package is needed.
* **Sessions:** a random 32-byte token in the cookie `glycotwin_session` (`HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `GLYCOTWIN_COOKIE_SECURE=true`). Only the SHA-256 of the token is stored, so a copy of the database cannot be used to sign in. Every sign-in creates a new token; sessions last `GLYCOTWIN_SESSION_DAYS` (default 7). No signing secret is needed.
* **Guest (demonstration) accounts:** `POST /auth/guest` creates a temporary account with no email and no password (it can never be signed in to again) and a short session (`GLYCOTWIN_GUEST_HOURS`, default 24). A guest has exactly the same ownership protections as a registered user.
* **Ownership:** every route with `{twin_id}` first checks the session (otherwise **401 "not signed in"**) and then that the twin is yours. A twin that is someone else's, unowned, or does not exist all give the **same 404 "twin not found"**, so a signed-in user cannot probe for other people's twin ids. `POST /twins` writes the owner in the same transaction as the twin. A test walks the router and fails if a twin route lacks the ownership check.
* **Old (unowned) twins** (made before accounts existed, or by `scripts/init_db.py --demo`) are **hidden from everyone** until claimed. `scripts/claim_twin.py` is the only way: dry run by default, `--apply` to write, refuses any twin that already has an owner (no force option, no transfer), requires an existing non-guest account, and only adds one row to `twin_owners`. `--list-unowned` is read-only.
* **Cross-site protection:** cookie-based POSTs to `/auth/*` are refused (403) when the browser's `Origin` does not match the host being called; the backend has no CORS settings, and the Vite proxy keeps the browser on one origin.
* **Brute-force limits:** 5 failed sign-ins per email per 15 minutes give 429 with `Retry-After`; guest creation is limited to 20 per address per hour.
* **Settings** (environment variables, see `.env.example`): `GLYCOTWIN_SESSION_DAYS`, `GLYCOTWIN_GUEST_HOURS`, `GLYCOTWIN_COOKIE_SECURE`, `GLYCOTWIN_ALLOW_REGISTRATION` (false: new registrations get 403), `GLYCOTWIN_ALLOW_GUEST`.
* **Migration:** none is needed and none exists (no migration tool). Start-up runs `create_all`, which only **adds** the missing `users`, `sessions` and `twin_owners` tables; existing tables and rows are never altered. Rollback: stop the app and restore your copy of the database file, or drop the three new tables (the previous code ignores them). Take a copy of the database file before the first start with the new code.

### Known limitations (not implemented or not solved)
* **No password recovery, email verification or account deletion** (they need an email service and a retention policy).
* **Guest cleanup:** expired guest accounts and their twins stay in the database; there is no cleanup job.
* **The brute-force counters are in memory:** they reset when the server restarts and apply per process; a deliberate attacker can also lock out a victim's email for 15 minutes.
* **Twin labels are globally unique** (one existing `UNIQUE` column that cannot be changed without rebuilding the table), so a label used by another account gives 409. That reveals only that the label is taken, never the twin, its id or its data.
* **Registration is open by default** (set `GLYCOTWIN_ALLOW_REGISTRATION=false` to close it).
* **Run the backend only on `127.0.0.1`** (the documented default). It has no TLS and no rate limiting beyond the above; do not expose it on a network. If it is ever served over HTTPS, set `GLYCOTWIN_COOKIE_SECURE=true`.
* **Not independently audited:** this is a student research prototype; the account system is covered by automated tests (`tests/test_auth.py`, `tests/test_ownership.py`) but has had no external security review. Not clinically validated.

## Not included
A migration tool (tables are created if missing; changing an existing table would need one), password recovery, email verification, account deletion, a real-data validation of the model, and a security audit. The React research dashboard lives in `frontend/` (`frontend/README.md`); it only displays what these endpoints return and is an investigational research prototype, not a clinically validated medical device.
