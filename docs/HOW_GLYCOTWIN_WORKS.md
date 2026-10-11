# How GlycoTwin Works: the Working Plan, Step by Step

> **GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.**

This is a plain-language explanation of what the system does and why, written for a student. Everything here is taken from the code and documents in this repository (`src/glycotwin/…`, `docs/model_card.md`, `docs/BACKEND.md`, `docs/modelling_assumptions.md`) and from the test run in `docs/GLYCOTWIN_COMPLETE_TEST_REPORT.md`. Statements about real data are what the research documents *say*; they were not re-checked here because the dataset is not in the cloud workspace.

---

## 1. The idea in one minute
Different people's glucose rises by different amounts after the same meal. GlycoTwin keeps a small **statistical model of one person**, called a *twin*. The twin holds:
* a **best guess** of how many mg/dL that person's glucose rises per gram of carbohydrate (called β), and optionally how that changes with recent physical activity (γ), and
* **how unsure** it is about those numbers.

Before a meal the twin gives a **forecast**: *the probability that the highest glucose in the next 2 hours reaches 180 mg/dL*, plus a 90 % range for that highest value. After the meal you tell it what really happened. The twin **learns** from that one meal and becomes a new **version**. Nothing is overwritten, so you can always see how the twin changed.

The research question: does adding *recent activity* (Model C) make the forecasts better calibrated than the same model without it (Model B)? The honest result so far is **inconclusive** (nearly every paired comparison interval contained zero). No claim that C beats B is made.

---

## 2. The two models
| | Formula (rise = how much the highest glucose is above the pre-meal value) | Meaning |
|---|---|---|
| **Model B** | `rise = β × carbs + noise` | personal carbohydrate sensitivity only |
| **Model C** | `rise = (β + γ × activity) × carbs + noise` | sensitivity that can depend on activity in the 4 hours before the meal |

Both are **Bayesian linear models with Gaussian noise**. "Bayesian" means: start from a *prior* (what a typical person looks like), then update with each observed meal using a closed-form formula (no iterative training). Each update shrinks the uncertainty ("narrower posterior"). Model A (a population XGBoost classifier) is a research baseline and is not used by the website.

---

## 3. Step-by-step: the life of a twin (what the system does)

### Step 0: Start the system
1. The **backend** (`glycotwin.backend.app:app`, FastAPI + SQLite) starts and creates any missing database tables (it never drops or deletes data).
2. The **frontend** (React + Vite) starts. Its dev server forwards `/api/...` requests to the backend so the browser needs no special permission (CORS). Both must run together; the site cannot work without the backend.

### Step 0b: Sign in (accounts, sessions, ownership)
* Every dashboard page needs an account. You **register** (name, email, password of 10–128 characters), **log in**, or choose **Continue as demo**, which creates a temporary **guest** account (24 hours). The password is stored only as a salted **scrypt** hash; the browser receives a random session token in an **HttpOnly** cookie (`glycotwin_session`, 7 days; guests 24 hours) and the backend stores only a hash of that token. **Log out** revokes the session.
* A twin belongs to the account that created it. Every `/twins/{id}…` route checks the session first (401 "not signed in") and then ownership; a twin that is not yours looks exactly like a twin that does not exist (404). `GET /twins` lists only your own twins.
* Twins that were created before accounts existed have no owner and are hidden until the database owner assigns them with `scripts/claim_twin.py` (a dry run unless `--apply`).
* Not built: password recovery, email verification, account deletion, cleanup of old guest accounts, persistent login rate limits. See `docs/BACKEND.md`, "Accounts, sessions and ownership".

### Step 1: Create a twin (`POST /twins`)
* You choose only a **label** (unique across the whole database, no spaces). You become the twin's owner. The backend picks the starting prior:
  * **Synthetic demonstration prior** (default): fitted on a *simulated* population on a *simulated 0–1 activity scale*. It exists so you can try the product without any real person's data.
  * **Prior file**: an aggregate prior written offline by `scripts/export_prior.py` (means, covariances, noise, counts only; the API refuses files that contain participant-level data).
* The twin starts as **version 0**. The twin knows nothing about *you* yet; it is just the population starting point.

### Step 2: Forecast a meal (`POST /twins/{id}/forecast`)
You enter four things: **carbohydrate (g)**, **pre-meal activity**, **pre-meal glucose (mg/dL)** and **meal time**.
1. The backend validates ranges (carbs 0–500, glucose 20–600, activity 0–25; a demo twin accepts only 0–1).
2. It refuses a **back-dated** forecast (a meal earlier than an outcome window the twin already learned from), because that would let the twin "see the future".
3. It computes, for each model: the **expected rise**, the **predictive standard deviation**, a **90 % interval**, and the probability that *pre-meal glucose + rise ≥ 180 mg/dL* using the normal distribution:
   `P = 1 − Φ((180 − pre-meal − expected rise) / predictive SD)`.
   Example from a verified run: pre-meal 110, expected rise 47.3, SD 16.5 → P = 8.4 %.
4. It attaches **data-quality flags** (for example "insufficient personal history": fewer than 3 observed meals). These are warnings only; they do **not** change the probability or the interval.
5. It stores the forecast as **pending**. The twin is **not** changed.

### Step 3: See the forecast (the website chart)
The chart shows only what step 2 returned: the 120-minute window, your pre-meal value, the 180 mg/dL line, each model's expected maximum and 90 % interval (a flat band across the window because the model predicts the *maximum*, not *when* it happens), and a side curve showing the probability distribution of that maximum. **There is no glucose-over-time curve**, because none is predicted.

### Step 4: Wait for the outcome window to close
The outcome is "the highest glucose reading in the 120 minutes after the meal". It can only be recorded once that window is complete (`observed_through` must be at least meal time + 120 minutes). For a classroom demo the website does not wait two real hours: the field is pre-filled with meal time + 120 minutes. In real use the number must come from a real measurement.

### Step 5: Record the outcome (`POST /twins/{id}/observe`)
You enter the **observed maximum glucose** (or mark the meal as **excluded** with a reason such as a sensor gap).
* The backend works out the observed rise (observed maximum − pre-meal) and whether it reached 180 mg/dL.
* **Recording does not change the twin.** One observation per forecast.

### Step 6: Apply it to the twin (`POST /twins/{id}/reconcile`)
1. If the outcome is usable, the engine performs the **Bayesian update**: new β/γ estimates and **narrower uncertainty**. The twin becomes **version 1** (then 2, 3 …); the old version stays in the history.
2. It also records how the forecast did (was the outcome inside the 90 % interval? what probability had been given to what happened?).
3. If the meal was **excluded**, the twin is **not** changed.
4. Applying twice is safe: the second call returns the stored result.
Everything happens in **one database transaction**; if anything fails, nothing is saved.

### Step 7: Forecast again
The next forecast uses the new version, so its numbers differ. The rule "next meal at least 2 hours after the last applied meal" prevents leakage of the future.

### Step 8: Look back and understand
Read-only pages that never change the twin:
* **History**: all forecasts and their status, how β changed over versions, hit rate so far (a few meals say little).
* **Insights**: how the twin's carbohydrate sensitivity varies with activity (sensitivity), and forecast versus real outcome.
* **Why this forecast?**: the model's own terms (for example the carbohydrate term and the activity term), and how much of the uncertainty comes from not knowing the person's parameters versus ordinary meal-to-meal noise. It is computed on the twin *as it was when the forecast was made*.
* **Compare scenarios (what-if)**: the same twin's forecast for other carbohydrate/activity values side by side. This describes the *model*, not a causal effect on the person, and it is not advice.

---

## 4. Where each part lives in the code
| Step | Code |
|---|---|
| Web pages | `frontend/src/pages/*`, `frontend/src/dashboard/*` |
| API client (talks to backend, checks replies) | `frontend/src/api/client.ts`, `validate.ts` |
| Routes | `src/glycotwin/backend/routers/twins.py`, `routers/auth.py` |
| Accounts, sessions, ownership | `backend/security.py` (hashing, tokens, throttle), `auth_service.py`, `ownership.py`, `deps.py`; frontend `src/auth/AuthContext.tsx`, `pages/Auth.tsx` |
| Claiming old twins | `scripts/claim_twin.py` |
| Input rules (ranges, patterns) | `src/glycotwin/backend/schemas.py` |
| Lifecycle rules and transactions | `src/glycotwin/backend/services.py` |
| Database | `src/glycotwin/backend/models.py`, `store.py` |
| Forecast maths and Bayesian update | `src/glycotwin/models/bayesian.py` (`forecast_exceeds_180`) |
| Versioned twin, forecast/reconcile | `src/glycotwin/twin/state.py` |
| Explanations, sensitivity, what-if | `src/glycotwin/twin/insight.py` |
| Data-quality flags | `src/glycotwin/twin/quality.py` |

---

## 5. The research pipeline (separate from the website)
The website uses the twin engine. The **research** side, run from `scripts/` on a local copy of the dataset (not part of the website, not run in the cloud test), does this:
1. **Inventory and audit** the dataset read-only (`audit_dataset.py` and friends).
2. **Build an event table** of meals: one row per meal with carbohydrate, past-only baseline glucose, pre-meal activity, and the 120-minute outcome label (`build_event_table.py`).
3. **Check for leakage**: features must use only information from *before* the meal (`check_leakage_on_data.py`).
4. **Run models** (`run_model_a.py`, `run_model_b.py`, `run_model_c.py`) with leave-participants-out style evaluation and forecast-then-learn sequences.
5. **Compare B and C** with paired statistics (`compare_models_b_c.py`), and compare prior choices (`compare_priors.py`).
6. **Export an aggregate prior** (`export_prior.py`) if a live twin should start from real-data population statistics. No participant-level rows are exported.
Results so far per `docs/model_card.md`: B vs C inconclusive; limitations include 34 eligible participants, self-reported macronutrients, wrist-device activity, a lower-bound label, and Gaussian assumptions.

---

## 6. Safety and honesty rules built into the system
* The disclaimer is shown on every screen and returned in every API reply.
* No dosing, medication or diet advice is produced; what-if text says so.
* Uncertainty is never hidden; data-quality warnings are shown but are not used to invent wider bands.
* Demonstration data is labelled as simulated.
* **Accounts are real but a research-prototype implementation**: hashed passwords, HttpOnly session cookie, ownership checks on every twin route. They have had no external security review, there is no password recovery, email verification or account deletion, login rate limits live in memory, and the cookie is not `Secure` unless configured. The backend must stay bound to `127.0.0.1` (your own computer); do not expose it on a network.

---

## 7. Project plan and status (step by step)
Taken from the repository history and `docs/PROJECT_STATUS.md` / `docs/BLUEPRINT_CONFORMANCE.md`. `PROJECT_STATUS.md` has been updated for the backend, dashboard and accounts; where an older paragraph there is marked superseded, this table and the dated sections are current.

| Phase | What | Status |
|---|---|---|
| 1 | Repository, data layer, meal extraction, leakage-safe features | Done (tested on synthetic data; not verified on the real dataset in this environment) |
| 2 | Models A, B, C and evaluation machinery | Done in code; B vs C reported **inconclusive** |
| 3 | Versioned twin: forecast → observe → reconcile, insights, what-if, data-quality flags | Done (815 Python tests pass in the author's Linux run) |
| 4 | SQLite + FastAPI backend (persistent history, idempotent updates) | Done |
| 5 | React research dashboard and dark landing page | Done (37 frontend tests; browser-checked on Linux) |
| 6 | Registration, sign in, guest mode, sessions, per-account twin ownership | **Done** (Linux tests and a Chromium walk-through; Windows and external security review pending) |
| 7 | Windows manual verification | **Pending, for you** (checklist in the test report, Section 14) |
| 8 | Real-data validation and the full A/B/C key experiment | **Pending**: needs the real dataset, a human review of decisions, and several unverified assumptions listed in `docs/modelling_assumptions.md` |
| 9 | Password recovery, email verification, account deletion, guest cleanup, persistent rate limits, HTTPS/deployment hardening | **Not started** |

---

## 8. Glossary
* **Twin**: one person's statistical model plus its history.
* **Prior / posterior**: the starting belief / the belief after learning from data.
* **Version**: a saved state of the twin; each applied outcome creates the next one.
* **Forecast window**: the 120 minutes after the meal.
* **90 % interval**: the range that the model believes contains the maximum 90 % of the time, *if the model were correct*.
* **Reconcile / apply**: update the twin using the real outcome.
* **Leakage**: accidentally using information from the future when making a forecast.
* **Calibration**: whether "30 % chance" events happen about 30 % of the time. A few meals per person cannot establish it.
* **Synthetic**: simulated, not from real people.
