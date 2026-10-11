# GlycoTwin Complete Test Report and Windows Testing Guide

> **GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.**
>
> Passing the checks in this report shows that the *software behaves as built*. It does **not** show that the model is scientifically valid, accurate, or clinically safe.

> **Update, 2026-10-11 (accounts and ownership).** This report was written at commit `49e9402`, when Sign In and Create Account were previews and the backend had no authentication. Real accounts, sessions and per-account twin ownership have since been implemented (uncommitted at the time of this update). Sections 3, 4.2, 7, 8.2, 8.3, 9, 10, 14 and 15 below were revised to match. The command log in Section 5 and the counts in Section 6 describe the **original audit at `49e9402`** (769 Python tests, 17 frontend tests) and are kept as history. Current Linux results after the accounts work: Python **815 passed**, frontend **37 tests passed**, typecheck clean, production build succeeded, Chromium walk-through 30/30 on a temporary database. Windows, other browsers, real phones, screen readers and any external security review remain **not done**.

| | |
|---|---|
| Report date | 2026-10-11 |
| Where the checks were run | **A cloud Linux workspace (Python 3.11.15, Node 22.22.0, npm 10.9.4, headless Chromium).** This is **not** your Windows laptop. Nothing in this report was run on Windows. |
| Branch / commit inspected | `claude/glycotwin-initial-scaffold-gegpzd` at `49e9402287e2c84c48db96b87f40af0d614d495a` ("Docs: website testing guide and frontend README for preview-only auth") |
| Remote check | `git fetch` showed `origin/claude/glycotwin-initial-scaffold-gegpzd` = the same commit, so GitHub has this commit. **There is no evidence that it has reached your Windows laptop**: you must run `git pull` there (Section 12). |
| Working tree when inspected | clean before this report; the only changes now are the two new documents listed in Section 2 (not committed) |
| Git stash | 0 entries in the cloud workspace. Your own stash/safety backup on the laptop was not visible to and not touched by this work. |
| Application code changed by this audit | **None.** |

**Evidence labels used below:** **RAN** = executed in the cloud workspace and the result is quoted; **NOT RUN** = not executed (reason given); **MANUAL** = needs you to do it.

---

## 1. Overall status

**WORKING WITH LIMITATIONS.** Every automated check that could be run passed (original audit at `49e9402`: typecheck, 17 frontend tests, production build, 769 Python tests, 52 live API checks, scripted browser walkthroughs). No critical or high bugs were found. The limitations are by design or are documented: (original audit; accounts and ownership were added afterwards, see the update note and Section 8.3), synthetic demonstration prior only, no real-data validation here, and some usability quirks (Section 8).

---

## 2. What was inspected and what was changed

### 2.1 Repository facts (verified by commands)
| Item | Result |
|---|---|
| Latest commits | `49e9402` Docs (website testing guide, README); `588a6c5` Frontend dark landing + preview auth; `5ab05a4` React dashboard; `d7bd3bb` Backend explanation/sensitivity/etc.; `1a8846f` FastAPI + SQLite backend |
| Landing page, Sign In, Create Account, dashboard present in code? | **Yes.** `frontend/src/pages/Landing.tsx`, `pages/Auth.tsx` (`#/login`, `#/register`), `dashboard/*` (7 pages). Confirmed by running them. |
| Research functionality present? | **Yes.** `src/glycotwin/models/*` (Models A, B, C), `src/glycotwin/twin/*` (versioned twin, insight, state view, quality), `scripts/*` (research runners, audits). |
| Real dataset in the cloud workspace? | **No.** `data/raw/` and `data/interim/` are empty. All real-data runs are therefore **NOT RUN** here. |
| File counts | 46 Python files under `src/glycotwin`, 22 scripts, 38 test files, 35 frontend source files, 19 docs |

### 2.2 Files changed by this audit
Only two **new, uncommitted** documents were created. No application code, tests, configuration, data, databases, stashes or backups were modified.

| File | Why |
|---|---|
| `docs/GLYCOTWIN_COMPLETE_TEST_REPORT.md` | This report |
| `docs/HOW_GLYCOTWIN_WORKS.md` | Step-by-step explanation of how the system works |

---

## 3. Architecture (actual)

```
Browser (React 19 + Vite 6 + TypeScript)           http://127.0.0.1:5173
   │  fetch("/api/...")      hash routes: #/ #/login #/register #/app/<page>
   ▼
Vite dev server proxy: strips "/api"               (no CORS needed)
   ▼
FastAPI backend  glycotwin.backend.app:app         http://127.0.0.1:8000   (docs at /docs)
   routers/ (auth, twins) → deps.py (session cookie, ownership) → services.py (one DB transaction per operation) → store.py (SqlTwinStore)
   ▼
Existing research engine (unchanged): twin/state.py, twin/insight.py, twin/state_view.py,
twin/quality.py, models/bayesian.py       (Models B and C, closed-form Bayesian update)
   ▼
SQLite file (default data/interim/glycotwin_backend.sqlite3, git-ignored)
```
* **Frontend** only displays what the backend returns; it does not re-implement the model and draws no invented glucose curve.
* **Backend** validates every input, enforces the lifecycle (forecast → observe → apply), and stores each twin update as a **new version**.
* **Accounts and ownership (added after the original audit):** register/login/guest/logout/me, scrypt-hashed passwords, a random session token in an HttpOnly `glycotwin_session` cookie (only its SHA-256 is stored), and an ownership check on every `/twins/{id}…` route (401 not signed in; identical 404 for a twin that is not yours). No CORS.
* Database tables (11): `twins`, `twin_states`, `parameter_snapshots`, `forecasts`, `observations`, `reconciliations`, `what_if_runs`, `data_quality_flags`, plus `users`, `sessions`, `twin_owners`. Existing databases get the three new tables on start-up; old twins have no owner and stay hidden until claimed with `scripts/claim_twin.py`.

---

## 4. Module inventory

### 4.1 Backend and research package (`src/glycotwin/`)
| File | Purpose (first line of its own docstring) |
|---|---|
| `backend/app.py` | FastAPI application factory (`glycotwin.backend.app:app`) |
| `backend/config.py` | Settings from environment variables (`GLYCOTWIN_DATABASE_URL`, `GLYCOTWIN_PRIOR_DIR`, `GLYCOTWIN_REFERENCE_ACTIVITY`) |
| `backend/db.py` | Engine, sessions, schema creation (creates missing tables only; foreign keys on) |
| `backend/models.py` | Relational schema (SQLAlchemy 2) |
| `backend/schemas.py` | Request validation (Pydantic v2): units and ranges |
| `backend/services.py` | Service layer: one transaction per operation, calls the existing engine |
| `backend/store.py` | `SqlTwinStore` (and read-only `AsOfStore`) over the database |
| `backend/priors.py` | Where a live twin's starting prior comes from (synthetic demo or aggregate prior file) |
| `backend/routers/health.py`, `routers/twins.py` | HTTP routes |
| `config.py`, `features.py` | Dataset path configuration; meal-event schema and leakage-safe splitting |
| `data/discovery.py`, `inventory.py`, `groups.py`, `meals.py`, `events.py`, `leakage_check.py` | Read-only dataset tools, meal extraction, event table, leakage test |
| `models/baseline.py` | Model A (population XGBoost) |
| `models/bayesian.py` | Models B and C (closed-form Bayesian carbohydrate sensitivity) |
| `models/blueprint_prior.py`, `prior_schemes.py`, `prior_compare.py` | Alternative prior and sensitivity analyses |
| `models/model_a_cv.py`, `model_b_cv.py`, `model_c_cv.py`, `model_bc_compare.py`, `experiment.py`, `evaluation.py`, `activity_strata.py`, `reliability_svg.py`, `simulation.py` | Research evaluation code |
| `twin/state.py`, `state_view.py`, `insight.py`, `quality.py`, `replay.py`, `adapter.py`, `demo.py` | Versioned twin, formal twin state, insights/what-if, data-quality flags, replay, synthetic demo |

### 4.2 Frontend (`frontend/src/`)
| File | Purpose |
|---|---|
| `App.tsx`, `main.tsx`, `lib/router.ts` | Entry and the single hash router |
| `pages/Landing.tsx` | Dark landing page (hero, product, how it works, research, docs, footer) |
| `pages/Auth.tsx`, `auth/AuthContext.tsx` | Sign In and Create Account (real; talk to the backend), sign-in state, route protection |
| `dashboard/Shell.tsx`, `views.tsx`, `forms.tsx`, `panels.tsx`, `ResponseChart.tsx`, `workspace.tsx` | Dashboard layout, 7 pages, forms, panels, signature chart, state |
| `api/client.ts`, `types.ts`, `validate.ts` | Typed API client with runtime response checks |
| `components/ui/*`, `components/organic/*` | Disclaimer, fields, status, decorative artwork and particle wave |
| `lib/*` | config (verbatim disclaimer), format, chart math, registry (localStorage), organic shapes |
| `styles/*.css` | tokens, base, landing, chart, app, theme (dark), auth |
| `test/*.test.tsx`, `test/fakeBackend.ts` | 37 frontend tests (4 files) |

### 4.3 Scripts and tests
* `scripts/` (22 files): research runners (`run_model_a/b/c.py`, `run_experiment.py`), audits, comparisons, `export_prior.py`, `init_db.py` (creates tables; `--demo` adds a **synthetic** twin), `demo_twin_lifecycle.py`. Most research scripts need the real dataset, which is **not present** here (NOT RUN).
* `tests/` (38 files): about 574 test functions, expanded by parametrisation to **769 test cases**. Largest groups: `test_model_bc_compare` (39), `test_innovation_features` (34), `test_model_b_cv` (30), `test_model_a_cv`/`test_model_c_cv` (29 each), `test_backend` (48).

---

## 5. Commands executed and actual results (cloud workspace)

| # | Command (directory) | Result | Status |
|---|---|---|---|
| 1 | `git branch --show-current`, `git rev-parse HEAD`, `git status`, `git stash list` (project root) | branch `claude/glycotwin-initial-scaffold-gegpzd`; HEAD `49e9402…`; clean; stash empty | RAN |
| 2 | `git fetch origin claude/glycotwin-initial-scaffold-gegpzd` | `origin/...` = `49e9402…` (same as local) | RAN |
| 3 | `python -m compileall -q src scripts tests` | exit 0 (no syntax errors) | RAN |
| 4 | Import every module in package `glycotwin` | **45 modules imported, 0 failures** | RAN |
| 5 | `npm run typecheck` (`frontend`) | clean, no errors | RAN |
| 6 | `npm test` (`frontend`) | **3 files, 17 tests passed** (core 10, landing 1, auth 6) | RAN |
| 7 | `npm run build` (`frontend`) | built in 1.8 s; JS 308.9 kB (94.6 kB gzip), CSS 28.3 kB | RAN |
| 8 | `python -m pytest -p no:cacheprovider -q` (project root) | **769 passed, 1 warning** in 548.6 s (the warning is a library deprecation notice from Starlette about `httpx`; it is not an application bug) | RAN |
| 9 | Live API audit: 52 HTTP checks against a real backend on a **temporary** database (Section 7) | **52 passed, 0 failed** | RAN |
| 10 | Scripted browser run (Chromium): landing, login, register at 1440×900, 1280×800, 768×1024, 390×844 | no console errors, no horizontal overflow at any size | RAN |
| 11 | Scripted browser dashboard run: create twin → forecast → record outcome → apply → second forecast → history → insights → what-if → explanation → sensitivity | all steps behaved as documented; no console errors | RAN |
| 12 | Scripted error states: empty forms, bad UUID, unknown twin (404), invalid values, early observation (422), back-dated forecast (409), backend stopped | all showed the expected message | RAN |
| 13 | Auth preview checks: empty/invalid/valid submit on `#/login` and `#/register`, network capture | **no network request**; message says "not signed in"/"not registered"; password cleared; no Forgot-password link | RAN |
| 14 | `npm audit --omit=dev` / `npm audit` (`frontend`) | production dependencies: **0 vulnerabilities**; including dev tooling: 6 (see Section 9) | RAN |
| 15 | `git diff --check` | clean | RAN |
| 16 | Secret/format scans of tracked files | no keys/tokens; no data, database or `.env` files tracked (only `.env.example` placeholders) | RAN |
| — | Real-data runs (`scripts/run_model_*.py`, `build_event_table.py`, leakage check on real files) | **NOT RUN**: the CGMacros dataset is not in the cloud workspace, and you asked that it not be used for interface testing | NOT RUN |
| — | Windows, Edge/Firefox/Safari, real phones, screen readers | **NOT RUN / MANUAL** | NOT RUN |

All servers and databases used for these checks were disposable (the database file lived outside the repository). They were stopped afterwards.

---

## 6. Test counts

| Suite | Tests | Result |
|---|---|---|
| Python (`pytest`) | 769 | all passed |
| Frontend (`vitest`) | 17 | all passed |
| Live API audit (script) | 52 | all passed |
| Typecheck / build | — | clean / succeeded |

---

## 7. API reference (from the real code and OpenAPI) with verified examples

Base: backend `http://127.0.0.1:8000` (interactive docs `/docs`). From the browser the same routes are reached at `/api/...` through the Vite proxy (the proxy removes `/api`). Success bodies are `{ "disclaimer": "...", "data": {...} }`; errors are `{ "detail": ..., "disclaimer": ... }` (FastAPI validation errors put a list in `detail`). `/health` is not wrapped.

| Method + path | Purpose | Changes twin state? | Success |
|---|---|---|---|
| `GET /health` | status, tables, engine version | no | 200 |
| `POST /auth/register`, `/auth/login`, `/auth/guest` | create an account / sign in / temporary guest (sets the session cookie) | creates user + session | 201 / 200 / 201 |
| `POST /auth/logout`, `GET /auth/me` | sign out / who am I (401 when signed out) | no twin state | 200 |
| `GET /twins` | list **your own** twins | no | 200 |
| `POST /twins` | create a twin (you become its owner) | creates twin (version 0) | 201 |
| `GET /twins/{id}` | twin and state view | no | 200 |
| `GET /twins/{id}/history` | versions, parameter history, hit-rate trend, exclusions | no | 200 |
| `POST /twins/{id}/forecast` | forecast one meal | stores a forecast; **twin version unchanged** | 201 (200 + `created:false` for an identical repeat) |
| `GET /twins/{id}/forecasts?limit=&offset=` | list forecasts | no | 200 |
| `POST /twins/{id}/observe` | record real outcome (peak or exclusion) | stores observation; **twin unchanged** | 201 (200 identical repeat) |
| `POST /twins/{id}/reconcile` | apply the observation | **new twin version** (not for excluded) | 201 (200 repeat) |
| `POST /twins/{id}/what-if` | scenario comparison | twin unchanged (stores a what-if run) | 200 |
| `GET /twins/{id}/forecasts/{fid}/explanation?model=model_b\|model_c` | why this forecast (as of its own version) | no | 200 |
| `GET /twins/{id}/sensitivity?activities=0,0.5,1` | sensitivity vs activity | no | 200 |
| `GET /twins/{id}/reconciliations` | forecast vs outcome, hit-rate, calibration | no | 200 |

**Required request fields (verified in `schemas.py` and by the API audit):**
* **Create twin** `{ "label": "audit-twin-1" }` — label pattern `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$` (no spaces), must not contain "cgmacros", must be unique. Optional `prior` (`source` `synthetic_demo`|`prior_file`, `name`, `prior_scheme` `empirical_bayes`|`blueprint`), `glycaemic_group`, `reference_activity` (0–25). Default prior = synthetic demonstration prior.
* **Forecast** `{ "event_id": "audit-meal-1", "meal_time": "2026-01-01T08:00:00", "carbs_g": 60, "activity_level": 0.3, "baseline_glucose": 110 }` — `carbs_g` 0–500; `activity_level` 0–25 (a **synthetic demo twin accepts only 0–1**, a simulated scale, not METs); `baseline_glucose` 20–600 mg/dL. Optional `activity_coverage` (0–1), `baseline_age_minutes` (0–1440), `trend_slope_30min` (−20…20), `time_since_last_meal_min`.
* **Observe** `{ "forecast_id": "<id>", "observed_through": "2026-01-01T10:00:00", "peak_glucose_mg_dl": 185, "window_completeness": 1 }` — `observed_through` must be ≥ meal time + 120 minutes; give **either** `peak_glucose_mg_dl` (20–600) **or** `excluded_reason` (3–200 chars), never both.
* **Reconcile** `{ "forecast_id": "<id>" }`
* **What-if** `{ "baseline_glucose": 110, "scenarios": [ {"label":"ref","carbs_g":60,"activity_level":0.3}, {"label":"more","carbs_g":90,"activity_level":0.3} ] }` — 1–10 scenarios.

**Verified example outputs (synthetic demonstration prior, empirical Bayes, fresh twin; values come from the real run and may change with the engine version — compare with your own backend, do not use them as pass/fail numbers):**
* Forecast for the inputs above: `model_c` = `{"p_peak_at_least_180": 0.084, "mean_rise_mg_dl": 47.292, "sd_mg_dl": 16.462, "interval90_rise_mg_dl": [20.216, 74.369]}`; `horizon_minutes` 120; `status` "pending". The UI adds your pre-meal glucose to the rise interval to draw the maximum-glucose interval (about 130 to 184 mg/dL). Arithmetic check: P = 1 − Φ((180 − 110 − 47.29) / 16.46) = 0.084, matching the engine.
* Forecast response keys: `created_at, data_quality, engine_provenance, event_id, forecast_id, horizon_minutes, inputs, meal_time, model_b, model_c, model_version, observation_id, reconciliation_id, status, twin_version_at_forecast`.
* Observation with peak 185 and baseline 110: `peak_glucose_rise_mg_dl` 75.0, `label_peak_at_least_180` true; twin version still 0.
* Reconcile: `twin_version_before` 0, `twin_version_after` 1, `outcome` "updated"; `parameter_change.model_c` β mean 0.863 → 1.047, β SD 0.168 → 0.127 (ratio 0.759).
* History keys: `exclusions, hit_rate_trend, parameter_history, posterior_convergence, reference_activity, twin_id, versions`.
* Sensitivity curve point: `{"activity_level": 0.0, "mean": 1.047, "sd": 0.127, "interval90": [0.838, 1.257]}` (mg/dL of peak rise per gram).
* What-if (60 g vs 90 g at activity 0.3): the 90 g scenario had a higher probability and a higher expected rise; the response carries the label "This is a research simulation based on this patient's learned model. It is not a diet prescription, treatment recommendation, or insulin dosing suggestion."
* Explanation sentence (version 1 twin): "model_c expects a peak rise of 59 mg/dL (sd 15) for 60 g carbohydrate at activity 0.3."

**Verified error responses:** unknown twin 404 "twin not found"; malformed id 422; duplicate label 409 "a twin with this label already exists"; same `event_id` with different inputs 409; demo twin activity 5 → 422 "activity_level 5 is outside the range [0, 1] supported by this synthetic demo twin…"; observe too early 422 "the outcome window is not complete: observed_through must be at or after meal_time + 120 minutes"; reconcile before observe 409 "no observation has been submitted for this forecast yet"; second different observation 409; back-dated forecast 409 "the twin already learned from an outcome window that closes after this meal time; a back-dated forecast is refused"; sensitivity activity 26 → 422; extra field → 422 `extra_forbidden`.

### 7.1 The 52 live API checks (all passed)
Health; twin creation (201), duplicate label (409), 7 invalid-create cases (empty/space label, extra field, "cgmacros" label, prior file without name, missing prior file, path-traversal file name) all rejected with 4xx; unknown twin 404; malformed id 422; forecast 201; probabilities within [0,1] and ordered intervals; identical repeat idempotent; 409 on conflicting inputs; 6 invalid-forecast cases rejected; reconcile-before-observe 409; early observe 422; observe without value or with both 422; observe 201 with correct rise (75); observing does **not** change the twin version; repeat reconcile does not update twice; back-dated forecast 409; later forecast made from version 1; history, paging, explanation (valid, bad model, unknown forecast), sensitivity (valid, demo-out-of-range, 26, empty); reconciliation view; read-only endpoints leave versions and forecast count unchanged; what-if ordering and no state change; empty-scenario and out-of-range rejection; exclusion flow leaves the twin unchanged. The script was run once against a disposable database; it is not stored in the repository.

---

## 8. Findings (problems, limitations, risks)

Missing features are listed separately and are **not** counted as bugs.

### 8.1 Bugs / defects
| Severity | Finding | Impact | Suggested handling |
|---|---|---|---|
| Critical | none found | | |
| High | none found | | |
| Medium | none found | | |
| Low | **Double-clicking "Request forecast" creates two forecasts** for the same meal (each click gets a new internal meal id). | Duplicate rows in History; the first can be left pending. | Disable the button while a request is in flight and keep one meal id per form fill. Not changed (design decision). |
| Low | **Home "Awaiting outcome" card can show 0 while forecasts are pending.** It counts forecasts whose window closed relative to the twin's latest event. | Understates pending work. | Use History or the Observations drop-down as the source of truth, or change the card's definition. |
| Low | **An observed value that has been recorded but not applied is not shown after a page refresh** (the Apply row remains). | Cosmetic; the outcome is still stored. | Could fetch the observation from the API. |
| Low | **`docs/PROJECT_STATUS.md` top gate table and root `README.md` are out of date** (they say no backend/dashboard exists). `requirements.txt` still calls the frontend a later phase. | Misleading documentation. | Update wording in a docs-only commit. |
| Info | Test-run deprecation warning: Starlette says using `httpx` with its test client is deprecated. | None now. | Revisit when upgrading dependencies. |

### 8.2 Missing features (by design, not bugs)
Password recovery, email verification, account deletion, cleanup of old guest accounts, persistent login rate limits (accounts, sessions, logout, ownership and `GET /twins` now exist); editing or deleting twins, forecasts or observations; importing glucose data in the UI; real glucose time series (the model forecasts only the window **maximum**); CSV export; heart-rate features; a screen for every one of the 13 blueprint screens.

### 8.3 Security and privacy
| Level | Finding |
|---|---|
| Resolved since the original audit | The original finding was *no authentication or authorisation in the backend*. Accounts, sessions and ownership checks on every twin route now exist (tests in `tests/test_auth.py` and `tests/test_ownership.py`). **Still true:** there has been no external security review; the backend must stay on `127.0.0.1` (never `--host 0.0.0.0`); the cookie is not `Secure` unless `GLYCOTWIN_COOKIE_SECURE=1`; there is no HTTPS in the dev setup. |
| Medium (known limitation) | No password recovery, email verification or account deletion; guest accounts are never cleaned up; login/guest rate limits are in memory and reset on backend restart; twin labels are globally unique (a 409 on create can reveal that another account used a label). |
| Medium | **No CORS configuration** (verified: no `Access-Control-Allow-Origin` header). This is safe by default; the Vite proxy is used instead. Do not "fix" it by allowing all origins. |
| Medium (dev tooling only) | `npm audit` reports 6 vulnerabilities (2 critical, 1 high, 3 moderate) in **development tooling** (vitest, tinypool, vite, esbuild and related). **Production dependencies: 0.** They matter only while running the dev server/test tools (the dev server binds to `127.0.0.1`). Fixing needs major-version upgrades (`npm audit fix --force`), which was **not** done to avoid breaking the working app. Do not open the dev server to other machines. |
| Low | `localStorage` stores only the last-open twin id under `glycotwin.active.<userId>.v2` (the older keys `glycotwin.twins.v1`/`glycotwin.active.v1` are no longer used); no glucose values, no password and no session token (the token is in an HttpOnly cookie). |
| Low / info | `data/audit/dataset_inventory_summary.md` (tracked, existing) lists per-participant file names and row counts (pseudonymous dataset ids). It is consistent with the repository's "aggregate summaries only" rule but is more detailed than a pure aggregate; review whether you want that in a public repository. No rows of data, no secrets, no `.env`, no databases are tracked. |
| Good | Input is validated server-side with strict schemas (unknown fields rejected); SQL goes through SQLAlchemy (no string-built queries found); prior-file names cannot traverse paths (tested); labels containing "cgmacros" are refused; React escapes output (no `dangerouslySetInnerHTML`); no secrets in tracked files. |
| Info | Twin ids are random UUIDs; they are not secrets, but knowing one no longer gives access: a twin that is not yours returns the same 404 as one that does not exist. |

### 8.4 Scientific validity and safety review
| Check | Result |
|---|---|
| UI invents glucose time-series curves? | **No.** The charts draw only: the pre-meal value you typed, each model's 90 % interval and expected value for the **maximum** glucose in the 120-minute window (flat across the window because the model does not say *when*), the Gaussian density implied by the reported mean and SD, the real observed maximum, and parameter/sensitivity values. Captions state "no time course is drawn". The only random numbers in the frontend are seeded decorative shapes and meal ids. |
| Probability computed correctly? | Verified by hand: P = 1 − Φ((180 − baseline − mean_rise) / predictive_sd) matches the engine to 3 decimals. |
| Diagnostic or treatment claims in the UI? | **None found.** Words found are only disclaimers and "not clinically validated" statements. The what-if label says it is not a diet, treatment or insulin recommendation. |
| B vs C result described as inconclusive? | **Yes** (landing page, model card). The landing page's "963 meals from 34 participants" figure comes from `docs/model_card.md`; it could **not** be re-verified here because the dataset is not present. |
| Uncertainty shown only from the backend? | Yes. Data-quality warnings are shown but, per the backend note, they do **not** change the probability or interval. |
| Demonstration values identified? | Yes ("SYNTHETIC DEMONSTRATION PRIOR", activity "(simulated scale)" with "not METs"). |
| Leakage safeguards | A forecast earlier than an already-applied outcome window is refused (409); an observation cannot be recorded before the window closes; an observation can be applied only once; explanations use the twin **as it was at forecast time**; excluded meals never update the twin. |

**Scientific assumptions and limitations (from `docs/model_card.md` and `docs/modelling_assumptions.md`):** Gaussian, constant-variance, no-intercept rise model (real peaks are likely skewed with variance growing with carbohydrate); known noise variance; the label is a **lower bound** (the maximum *observed* glucose); few participants (34 eligible) and one dataset; self-reported macronutrients; wrist-device activity; the activity coefficient γ may be weakly identified and correlated with β; the posterior only gains precision (no forgetting); Libre and Dexcom disagree on the label in about 23 % of matched events; one fold assignment; no multiplicity correction; the B-vs-C paired comparison is inconclusive. The demonstration prior is **simulated**, so demo forecasts say nothing about real people. A few meals per person cannot establish calibration.

---

## 9. Automated versus manual checks

| Area | Automated here (cloud) | Still needs you (MANUAL) |
|---|---|---|
| Code correctness | typecheck, frontend tests, Python tests (original audit 17 / 769; now 37 / 815), 45-module import check, 52 API checks | none required |
| Frontend ↔ backend integration | scripted browser run with real backend | repeat on Windows (Section 12) |
| Error and empty states | scripted | glance at them yourself |
| Layout / overflow / console | Chromium 4 sizes, no errors | check on your browser, especially fonts and Edge |
| Keyboard focus | tab order and outline scripted | visual check |
| Accessibility | partial (labels, focus, contrast calculations) | screen reader, Lighthouse/axe, real phone — **not done** |
| Real data / model results | none | run research scripts yourself on the real dataset, outside this web test |
| Authentication and ownership | backend tests, fake-backend frontend tests, Chromium run on a temporary database | repeat on Windows; independent security review |

---

## 10. How to test sign-in and registration (they are real)

Use a **test** database (Section 14, step 4), never your real one. Use throw-away values only; do not type a password you use anywhere else.

1. Open `http://127.0.0.1:5173/#/register`. Submit empty: messages appear. Enter name `Test Person`, email `test1@example.com`, a throw-away password of at least 10 characters, the same value in "confirm", tick the checkbox, **Create account**. *Pass:* you land in the workspace signed in; Settings → Account shows the name and email.
2. **Log out** (Settings). *Pass:* you return to the landing page; opening `http://127.0.0.1:5173/#/app/home` sends you to the sign-in page.
3. `#/login`: wrong password → "incorrect email or password" (the same text for an unknown email). The correct password signs you in. Five wrong attempts for one email within 15 minutes give "Too many attempts" (restart the **test** backend to reset).
4. **Continue as demo** creates a temporary guest account (24 hours); the sidebar says it is a guest.
5. Create a twin as `test1@example.com`, log out, register `test2@example.com`: that account must not see the twin (it appears in neither Settings nor by id; the API answers 404).
6. DevTools → Application → Cookies: `glycotwin_session` is **HttpOnly**, SameSite Lax. `document.cookie` in the Console must not show it. Local Storage holds at most `glycotwin.active.<userId>.v2`.
7. There is no Forgot-password link, no Remember-me, no email verification and no account deletion (not built).

The full account test cases (AU-01…AU-18, DM, OW, CL) are in `docs/WEBSITE_TESTING_GUIDE.md`, Section 3.

---

## 11. Browser testing walkthrough (exact inputs)

Prerequisite: both servers running (Section 12), backend on a **test** database, and you are signed in (Section 10). Use a **new label every run** (labels must be unique). All values are made-up demonstration numbers, not medical data.

| Step | Where / what to do | Input | Expect |
|---|---|---|---|
| 1 | `http://127.0.0.1:5173/` | — | Dark landing page; both buttons **Open the application** and **Explore the research** and the strip "Model family / Engine / Backend" visible without scrolling at 1440×900; Backend "online · database ok" |
| 2 | Click **Open the application** | — | Not signed in: the sign-in page. Register (or **Continue as demo**), then the dashboard opens; if you have no twin, "No twin selected" |
| 3 | **Settings → Create a twin** | **Twin label:** `win-test-1` · **Prior source:** Synthetic demonstration prior · **Prior scheme:** Empirical Bayes · click **Create twin** | Green: "Twin “win-test-1” created at version 0." and the twin listed as ACTIVE |
| 4 | **My Twin** | — | Version 0; parameter table with finite numbers; "SYNTHETIC DEMONSTRATION PRIOR" |
| 5 | **Forecast → Meal** | **Carbohydrate (g)** `60` · **Pre-meal activity** `0.3` · **Pre-meal glucose (mg/dL)** `110` · **Meal time (UTC)** `2026-01-01 08:00` · click **Request forecast** | "Forecast stored from twin version 0."; chart with bands "B · expected max …" and "C · expected max …", "P(max ≥ 180) = …%", status "FORECAST · AWAITING OUTCOME"; data-quality notice "Insufficient personal history: 0 observed meals so far." |
| 6 | Same page, scroll | click **Model B** in "Why this forecast?" | explanation changes; Model B has only the `carbs_g` term |
| 7 | **Observations → Record an outcome** | leave **Observed through** as pre-filled `2026-01-01 10:00` · **Observed maximum glucose** `185` · **Window completeness** `1` · **Record outcome** | "Observation recorded. The twin has not been updated yet."; Twin version still 0 |
| 8 | Same page, **Apply to the twin** | click **Apply** | "Twin updated: version 0 → 1." plus a line "Model C β: … → … ; its SD ratio …" |
| 9 | **Forecast** again | glucose `105`, meal time `2026-01-01 09:00` | **Refused**: "…a back-dated forecast is refused" |
| 10 | Same, meal time `2026-01-01 12:00` | **Request forecast** | "Forecast stored from twin version 1." and different numbers than step 5 |
| 11 | **History** | — | Forecast table (reconciled + awaiting), parameter chart with v0 and v1, "Hit rate so far" |
| 12 | **Insights** | — | Sensitivity chart (activity 0–1); "Forecast versus outcome" row with observed rise `75.0 mg/dL` |
| 13 | **Forecast → Compare scenarios** | Pre-meal glucose `110`; Scenario 1: `60` g, activity `0.3`; Scenario 2: `90` g, activity `0.3` (the field may default to 0.8: type 0.3); **Compare** | table with Scenario 1 "(reference)" and Scenario 2 showing a higher Model C probability "(+N pts)" |
| 14 | Invalid inputs | carbohydrate `501`; glucose `19`; activity `5`; empty fields | red messages: "must be between 0 and 500", "between 20 and 600", "between 0 and 1", "is required" |
| 15 | Exclude flow (optional) | new forecast, Observations → tick **Exclude this meal**, reason `sensor gap over 30 minutes`, **Record outcome**, **Apply** | "Excluded: the twin was not changed."; version unchanged |

**Input fields actually required**
* Create twin: only **Twin label**.
* Forecast: **Carbohydrate (g)**, **Pre-meal activity**, **Pre-meal glucose (mg/dL)**, **Meal time (UTC)**.
* Observation: **Forecast** (selector), **Observed through (UTC)**, and either **Observed maximum glucose in the window (mg/dL)** or the **Exclude** checkbox + **Reason**; **Window completeness** is optional.
* Apply: no input, just the **Apply** button.

The longer test-case catalogue (IDs LP, AU, DM, OW, CL, SH, HM, TW, FC, OB, HI, IN, WI, ST, ER, VR, RI) is in `docs/WEBSITE_TESTING_GUIDE.md`.

---

## 12. Running on Windows PowerShell (reference)
The simple checklist is Section 14. Key facts: the backend entry point is `glycotwin.backend.app:app` (verified), run from the **project root** (the folder containing `pyproject.toml`); the frontend commands run inside the **`frontend`** folder.

---

## 13. Remaining limitations of this report
* Nothing was run on Windows, Edge, Firefox, Safari or a real phone. Fonts and pixel positions will differ slightly on Windows.
* Real-data model results, the leakage check on real files, and the "963 meals / 34 participants" statement were **not re-verified** (no dataset available here).
* Screen-reader and automated accessibility audits were not performed.
* The 52-check API script and the browser scripts were temporary and are not committed.
* The Windows database URL form `sqlite:///C:/...` (used in Section 14) follows the standard SQLAlchemy form but was not tested on Windows.

---

## 14. Simple Windows checklist (beginner-friendly)

**Before you start:** these steps were **written on Linux and have not been run on Windows**. This uses **two PowerShell windows**. Your real database and research files are not touched, because step 4 points the backend at a throw-away test database in your Temp folder. If anything below shows something unexpected, **stop and send me the output**; do not run any "reset", "clean" or "stash drop" commands.

### A. Window 1: the project root folder
The **project root** is the folder that contains `pyproject.toml`, `README.md` and the folders `src`, `docs` and `frontend`.

1. Open **PowerShell** (Start menu → type `PowerShell`). Go to the project root (change the path to where you cloned it):
   ```powershell
   cd "C:\path\to\GlycoTwin"
   ```
   *Pass:* `dir` shows `pyproject.toml`.
2. Look at the current state (read-only):
   ```powershell
   git status
   git branch --show-current
   git stash list
   ```
   *Pass:* branch is `claude/glycotwin-initial-scaffold-gegpzd`. If `git status` lists changed files that you did not expect, **stop and send me the output** before the next step (your own work and stash are safe; do not run reset or clean).
3. Get the latest code (this only downloads; it does not delete your files):
   ```powershell
   git pull origin claude/glycotwin-initial-scaffold-gegpzd
   git log -1 --oneline
   ```
   *Pass:* the last line shows the commit you expect. The accounts work is **not on GitHub until it is committed and pushed**, so if you have not pulled a commit that contains `routers/auth.py`, steps 8–10 below will not match. If it says something else, send me that line.
4. Point the backend at a **test** database (a new empty file in your Temp folder) and start it:
   ```powershell
   $env:GLYCOTWIN_DATABASE_URL = "sqlite:///" + ($env:TEMP -replace '\\','/') + "/glycotwin_test.sqlite3"
   python --version
   python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000
   ```
   *Pass:* the window prints `Uvicorn running on http://127.0.0.1:8000` and stays open. **Leave this window running.**
   * If you see `ModuleNotFoundError`, stop it with Ctrl+C, run `python -m pip install -e ".[dev]"`, and start again (step 4's last line).
5. In your browser open `http://127.0.0.1:8000/health`. *Pass:* you see `"status":"ok"` and `"database":"ok"`.

### B. Window 2: the `frontend` folder
6. Open a **second** PowerShell window and run:
   ```powershell
   cd "C:\path\to\GlycoTwin\frontend"
   npm install
   npm run dev
   ```
   *Pass:* it prints `Local: http://127.0.0.1:5173/` (use the address it prints). **Leave this window running.** (The first `npm install` can take a few minutes; warnings about "vulnerabilities" are expected, see Section 8.3.)

### C. Website checks (in your browser)
Use Chrome or Edge. Press **F12** to open DevTools if something looks wrong.

7. **Landing page.** Open `http://127.0.0.1:5173/`. Make the window about 1440×900 (maximised on a laptop is fine).
   *Pass:* dark page; you can see **Open the application**, **Explore the research** and the line "Backend … online · database ok" **without scrolling**.
8. **Create an account.** Open `http://127.0.0.1:5173/#/register`. Click **Create account →** empty (messages appear). Then use name `Win Tester`, email `win-test@example.com`, a throw-away password (10+ characters) twice, tick the box, submit.
   *Pass:* you are taken into the dashboard and signed in. Wrong or short passwords show the message from the page or backend.
9. **Log out and back in.** Settings → **Log out** (landing page appears). Open `#/login` and sign in with the same email and password. Try a wrong password once (*Pass:* "incorrect email or password").
10. **Continue as demo (guest).** Log out, then click **Continue as demo**. *Pass:* the dashboard opens and the sidebar says you are a temporary guest. Log out and sign in again as `win-test@example.com` for the next steps.
11. **Create a twin.** Click **Settings** → **Twin label** `win-test-1` → **Create twin**. *Pass:* green "Twin “win-test-1” created at version 0." (A twin you create belongs to your account only.)
    (If you run this again later, use `win-test-2`; labels must be new.)
12. **Forecast.** Click **Forecast**. Enter **Carbohydrate (g)** `60`, **Pre-meal activity** `0.3`, **Pre-meal glucose (mg/dL)** `110`, **Meal time (UTC)** `2026-01-01 08:00` → **Request forecast**.
    *Pass:* "Forecast stored from twin version 0." and a chart with bands and "P(max ≥ 180) = …%" (about 8 % on a fresh demo twin). The chart has **no** smooth glucose curve.
13. **Observation.** Click **Observations**. Leave "Observed through" as it is; **Observed maximum glucose** `185`; **Window completeness** `1` → **Record outcome**.
    *Pass:* "Observation recorded. The twin has not been updated yet."
14. **Apply.** Click **Apply** (right panel). *Pass:* "Twin updated: version 0 → 1."
15. **History and Insights.** Click **History** (forecast table, parameter chart with v0 and v1) and **Insights** (sensitivity chart, "Forecast versus outcome" row with observed rise 75.0 mg/dL). *Pass:* both load without red errors.
16. **Error check.** On **Forecast** type carbohydrate `501` → **Request forecast**. *Pass:* red "Carbohydrate must be between 0 and 500."
17. **Mobile layout.** In Chrome/Edge press **Ctrl+Shift+M** (device toolbar), choose **Responsive**, set width **390** and height **844**. Open the landing page, `#/login`, `#/register` and the dashboard.
    *Pass:* no sideways scrolling; the **Menu** button opens the links.
18. **Keyboard focus.** Click the page background, then press **Tab** repeatedly on `#/login`. *Pass:* every item you land on has a visible outline (order: Skip to content, GlycoTwin, Back to home, Email, Password, Show password, Sign in, Continue as demo, Create one). If you are signed in, `#/login` redirects to the workspace; log out first.
19. **Ownership (optional).** Log out, register a second email, and check that the first account's twin is not listed. (A twin from the old database, if any, is hidden until claimed: `python scripts\claim_twin.py --list-unowned` is read-only; see `docs/BACKEND.md` and **back up the database file before using `--apply`**.)

### D. Optional automated checks on your laptop
Window 2 (`frontend` folder) after pressing **Ctrl+C** to stop the dev server:
```powershell
npm run typecheck
npm test
npm run build
```
*Pass:* typecheck prints no errors; `npm test` ends with `Tests  17 passed (17)`; build ends with `built in …`.
Window 1 (project root) after stopping the backend with Ctrl+C:
```powershell
python -m pytest -p no:cacheprovider -q tests/test_backend.py
```
*Pass:* `… passed`. (The full suite takes about 9 minutes: `python -m pytest -p no:cacheprovider -q`; it uses temporary databases and does not touch your real one.)

### E. If something fails: what to send me
* A screenshot of the **whole browser window** showing the problem, including the red message.
* A screenshot of the **DevTools Console** tab (F12 → Console) and of the **Network** tab with the failing request selected (Response tab visible).
* The last 30 lines of **both** PowerShell windows (copy and paste as text).
* The output of `git log -1 --oneline` and `git status` from Window 1.
* Which numbered step above failed.

### F. Stop safely
1. In Window 2 click the window and press **Ctrl+C** (answer `Y` if asked to terminate). Close it.
2. In Window 1 click the window and press **Ctrl+C**. Close it.
3. Optional: the test database is just the file `glycotwin_test.sqlite3` in your Temp folder; you can leave it. Your real database and research files were never used.
4. Do **not** run `git reset`, `git clean` or `git stash drop`.

---

## 15. What I would do next (in order)
1. Run Section 14 on Windows and send me anything that fails.
2. Review and commit the accounts work (backend, frontend, documentation as separate commits), then decide on the remaining account gaps: password recovery, email verification, account deletion, guest cleanup, persistent rate limits, per-account labels, HTTPS/deployment, and an independent security review.
3. Small fixes if you want them: disable the Request-forecast button while sending; fix the "Awaiting outcome" card; refresh the stale statements in `README.md`, `requirements.txt` and `docs/PROJECT_STATUS.md`.
4. Consider upgrading the dev tooling (vitest/vite) to clear the dev-only audit warnings, after checking the tests still pass.
5. Run the real-data research scripts yourself on your dataset (outside this web test) following `docs/REAL_DATA_RUNBOOK.md`.
