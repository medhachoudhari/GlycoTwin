# GlycoTwin Website Testing & Verification Guide

> **GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.**
>
> Passing every test in this guide shows that the *website works as built*. It does **not** show that the model is scientifically valid or clinically safe. Nothing here is clinically validated.

**Audience:** a student developer testing the whole site by hand, as a user, a developer and a hackathon evaluator.
**Source of truth:** the repository at the time of writing: commit `49e9402` **plus the account, ownership and frontend-integration changes (Stages A to D) that were uncommitted when this was written**. Run `git log -1 --oneline` and `git status` to see which commit you have; if your copy is older than these changes, the account tests below will not match it. Where something could not be confirmed, this guide says so.

**Important change:** the Sign In and Create Account pages are now **real**. They talk to the backend, every dashboard page needs a signed-in account (a registered account or a temporary guest), and each account sees only its own twins. Earlier versions of this guide described them as preview-only; that is no longer true.

### How to read the evidence labels

| Label | Meaning |
|---|---|
| **[Code]** | Read directly from the source files (frontend, backend, schemas, docs). |
| **[Run]** | Observed by the author of this guide while running the real backend (temporary SQLite database) and the real frontend on Linux, driven by an automated Chromium script, `curl` and Python test scripts. It was **not** observed on your Windows machine. |
| **[Unverified]** | Expected from the code but not observed. You must check it yourself and write down what you see. |

Numbers marked **[Run]** came from the *synthetic demonstration prior* and were identical in two separate runs, but they depend on the engine version. **Never use a number in this guide as a pass/fail criterion.** The pass criterion is always: *the screen matches what the backend actually returned* (see Section 7 for how to look at the backend response).

---

## Table of contents
1. [Project and environment overview](#1-project-and-environment-overview)
2. [Complete website inventory](#2-complete-website-inventory)
3. [Step-by-step manual test cases](#3-step-by-step-manual-test-cases)
4. [Exact test data and safe scenarios](#4-exact-test-data-and-safe-testing-scenarios)
5. [Visual design and responsive testing](#5-visual-design-and-responsive-testing)
6. [End-to-end digital twin workflow](#6-end-to-end-digital-twin-workflow)
7. [API integration testing](#7-api-integration-testing)
8. [Research integrity and scientific limitations](#8-research-integrity-and-scientific-limitations)
9. [Troubleshooting](#9-troubleshooting)
10. [Automated verification](#10-automated-verification)
11. [Final test report and checklist](#11-final-test-report-and-checklist)
12. [Known documentation and behaviour discrepancies found while writing this guide](#12-known-discrepancies-found-while-writing-this-guide)

---

## 1. Project and environment overview

### 1.1 What GlycoTwin does (plain language)
A *Digital Twin* here means a small statistical model of **one person's** glucose response to carbohydrate. It is stored as a *posterior* (a best guess **plus** how unsure the model is). The workflow is a loop:

1. **Forecast** – before a meal, the twin gives the probability that the highest glucose in the next 120 minutes reaches **180 mg/dL**, plus a 90 % interval for that highest value.
2. **Observe** – after the 120-minute window has closed, you record the real highest glucose (or mark the meal as unusable).
3. **Apply (reconcile)** – the observation is applied once, creating a **new, versioned** twin state. Nothing is overwritten; excluded meals never change the twin.

The model (from the landing page and `docs/BACKEND.md`): `rise = (β + γ · activity) × carbohydrate + noise`. **Model B** has no activity term; **Model C** adds it. The site shows both. **[Code]**

### 1.2 What the frontend and backend each do
| Part | Technology | Job |
|---|---|---|
| Backend (`src/glycotwin/backend/`) | FastAPI + SQLite (SQLAlchemy) + Pydantic | Holds the twin database and the user accounts, validates every request, signs users in, enforces that each twin is visible only to its owner, calls the research engine and enforces the lifecycle rules. Every success reply has the shape `{ "disclaimer": ..., "data": ... }`; errors have `{ "detail": ..., "disclaimer": ... }` (validation errors may carry a list in `detail`). `/health` is **not** wrapped in `data`. **[Code][Run]** |
| Frontend (`frontend/`) | React 19 + Vite 6 + TypeScript | Dark-themed landing page, **real** Sign In and Create Account pages, and a research dashboard (light theme with a dark sidebar) that is available only to signed-in users. It only **displays** what the backend returns. It does **not** re-implement the Bayesian model and does not invent glucose curves. **[Code]** |

### 1.3 How the browser reaches FastAPI (the Vite proxy)
The backend has **no CORS configuration**, so the browser must not call it directly from another origin. Instead:

```
Browser  ──>  http://127.0.0.1:5173/api/twins/...   (Vite dev server, "/api" prefix)
                      │  Vite removes the "/api" prefix
                      ▼
              http://127.0.0.1:8000/twins/...       (FastAPI)
```
* Frontend code uses the base URL `/api` (setting `VITE_API_BASE_URL`, default `/api`).
* The proxy target defaults to `http://127.0.0.1:8000` (setting `VITE_API_PROXY_TARGET`).
* **Important when you inspect traffic:** the *Network tab* shows `/api/twins/...`; the *FastAPI docs* (`/docs`) show `/twins/...`. They are the same endpoint. **[Code][Run]**
* The proxy exists for both `npm run dev` (port 5173) and `npm run preview` (port 4173). **[Code]**

### 1.3b Page addresses (hash routes)
The app uses one router that reads the part of the address after `#` (so refresh and direct links work with any static host). **[Code][Run]**

| Address | Page | Who may open it |
|---|---|---|
| `#/` | Landing page. Anchors `#/product`, `#/research`, `#/how`, `#/docs` scroll to that section | everyone |
| `#/login` | Sign In (real) | everyone; a signed-in user is sent to `#/app/home` |
| `#/register` | Create Account (real) | everyone; a signed-in user is sent to `#/app/home` |
| `#/app/home`, `#/app/twin`, `#/app/forecast`, `#/app/observations`, `#/app/history`, `#/app/insights`, `#/app/settings` | Dashboard pages | **signed-in users only**; a signed-out visitor is sent to `#/login`. Unknown `#/app/...` names show Home |
| `#/forgot-password` | **Does not exist** | there is no recovery flow; opening it just shows the landing page |

Use `#/login`, not `/login`: a path without `#` is not a route in this app. Do not expect dedicated 404 pages. **[Code]**

### 1.4 Folder structure relevant to testing
```
GlycoTwin/                       <- PROJECT ROOT (contains pyproject.toml)
├─ pyproject.toml, requirements.txt
├─ src/glycotwin/backend/        app.py, routers/{auth,twins}.py, schemas.py, services.py, store.py, config.py,
                                 security.py, auth_service.py, ownership.py, deps.py, models.py
├─ src/glycotwin/twin/           research engine (state, insight, state_view, quality)
├─ scripts/init_db.py            creates tables; --demo adds a SYNTHETIC demo twin
├─ tests/                        Python tests (backend tests use temporary databases)
├─ docs/                         BACKEND.md, ARCHITECTURE.md, BLUEPRINT_CONFORMANCE.md, PROJECT_STATUS.md, model_card.md, this guide
├─ data/                         git-ignored participant data folders. DO NOT open, copy or commit anything here.
└─ frontend/                     <- FRONTEND DIRECTORY (contains package.json)
   ├─ src/App.tsx, main.tsx, pages/Landing.tsx, pages/Auth.tsx (Sign In + Create Account, real), auth/AuthContext.tsx
   ├─ src/dashboard/             Shell, views, forms, panels, ResponseChart, workspace
   ├─ src/api/                   client.ts, types.ts, validate.ts
   └─ src/test/                  frontend tests (37)
```
**Where the database lives by default:** `data/interim/glycotwin_backend.sqlite3` (git-ignored). Twins you create while testing are saved there. They are harmless demo data, but see 4.1 if you want a throw-away database. **[Code]**

### 1.5 Required software
| Software | Why | Notes |
|---|---|---|
| Python ≥ 3.10 | Backend and Python tests | `pyproject.toml` (`requires-python`). **[Code]** |
| Python packages | pandas, numpy, scipy, scikit-learn, xgboost, fastapi, pydantic, sqlalchemy, uvicorn; for tests also pytest and httpx | Install with `pip install -e ".[dev]"` **or** `pip install -r requirements.txt` from the project root. **[Code]** |
| Node.js + npm | Frontend | Vite 6 / Vitest 2 need a current Node (18.18+, 20+ or 22+ per the Vite 6 documentation; **[Unverified]** on your machine). Check with `node --version`. |
| A modern browser | Chrome, Edge or Firefox | DevTools used in Section 5. |

### 1.6 Starting everything (Windows PowerShell)
Use **two** PowerShell windows. Replace the path with your own.

**Window 1 – backend** (project root, Python environment active)
```powershell
cd C:\path\to\GlycoTwin
# If you use a virtual environment:  .\.venv\Scripts\Activate.ps1
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000
```
The module is `glycotwin.backend.app:app` (verified in `docs/BACKEND.md` and by running it). **[Code][Run]** The older text `glycotwin.api.app:app` does **not** exist. If PowerShell blocks `Activate.ps1`, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first (affects only that window).

**Window 2 – frontend** (frontend directory)
```powershell
cd C:\path\to\GlycoTwin\frontend
npm install        # first time only
npm run dev
```
Vite prints a local URL. The configured default is `http://127.0.0.1:5173`. If port 5173 is busy, Vite may choose another port and print it; **use the URL Vite prints**. (`strictPort` is not set in `vite.config.ts`.) **[Code]**

### 1.6b Accounts, your real database, and a throw-away test database
* **Every dashboard test needs a signed-in account.** Use fake demonstration details only: for example name `Test Person`, email `test.person@example.com` (use a different email for a second account), password `windows-test-pass-1` (at least 10 characters). Never use a real password or personal data.
* **Back up your real database before the first run with the account-enabled backend.** In PowerShell: `Copy-Item data\interim\glycotwin_backend.sqlite3 data\interim\glycotwin_backend.backup.sqlite3` (adjust the path if you changed `GLYCOTWIN_DATABASE_URL`). The new code only **adds** three tables (`users`, `sessions`, `twin_owners`) and never changes existing rows, but a copy is your rollback.
* **Twins that already exist in your real database have no owner and are hidden** from every account until you claim them with `scripts\claim_twin.py` (case CL-01). That is intentional: nothing is given to the first person who registers.
* **To test without touching your real database,** set a throw-away database in Window 1 before starting the backend (Section 4.1): `$env:GLYCOTWIN_DATABASE_URL = "sqlite:///" + ($env:TEMP -replace '\\','/') + "/glycotwin_test.sqlite3"`. Use a different file name for each fresh start.
* Keep the backend on `127.0.0.1` (the default in the commands above). It has no TLS and has not been security-audited; do not expose it to a network.

### 1.7 Confirm both services are running
| Check | Open this | Expected |
|---|---|---|
| Backend alive | `http://127.0.0.1:8000/health` | JSON with `"status": "ok"`, `"database": "ok"`, a list of 11 `tables` (8 research tables + `users`, `sessions`, `twin_owners`), an `engine` block. **[Run]** |
| Backend docs | `http://127.0.0.1:8000/docs` | Swagger page listing the routes in Section 7. **[Run]** |
| Frontend | `http://127.0.0.1:5173/` | Dark landing page "Your metabolism has a story. Let's model it." with both buttons visible on the first screen |
| Sign in / Create account pages | `http://127.0.0.1:5173/#/login` and `#/register` | The real forms (Section 3, AU cases). Direct address entry and **F5** must keep you on the same page. |
| Account endpoints | `http://127.0.0.1:8000/auth/me` | `{"detail":"not signed in",...}` (401) when nobody is signed in. **[Run]** |
| Proxy works | `http://127.0.0.1:5173/api/health` | The same JSON as the first row. **[Run]** |
| Landing page sees the backend | Landing hero, "Backend" line | `online · database ok` (offline shows `not running`). **[Code][Run]** |

### 1.8 Stop and restart
* Stop a server: click its PowerShell window and press **Ctrl + C**.
* Restart: run the same command again. The database persists between restarts (initialisation only creates missing tables and never drops or deletes; this is tested), so accounts, twins and history survive. Browser sessions also survive a backend restart (they are stored in the database), until they expire. **[Code]**
* After restarting the backend, **refresh the browser page** so the frontend reloads its data.

### 1.9 Common startup errors
See Section 9 for the full table. The three most common: `ModuleNotFoundError: glycotwin` (run from the project root and install the package), `address already in use` for port 8000 (another backend is running), and `'vite' is not recognized` (run `npm install` inside `frontend`).

---

## 2. Complete website inventory

Navigation uses *hash routes*: the part after `#` in the address bar. Landing = `#/`; the app = `#/app/<view>`. **[Code]**

### 2.0 Visual design in one paragraph
The **landing page and the Sign In / Create Account pages** use a dark editorial theme: near-black olive and chocolate surfaces (about `#1a170f`), warm ivory text, coral (red-orange) primary buttons and accent text, an elegant serif for headlines with a clean sans-serif for body text, thin contour lines and an organic, translucent "cellular" artwork. **The dashboard (`#/app/...`) keeps its earlier light ivory theme** with a dark sidebar; it was not redesigned. A visual reference mockup exists outside the repository; this guide does not claim a pixel-level match with it. **[Code][Run]**

### 2.1 Landing page (`http://127.0.0.1:5173/#/`)
| # | Section / element | Purpose | How to reach |
|---|---|---|---|
| L1 | Compact top navigation (about 58 px high): brand "GlycoTwin", **Product**, **Research**, **How it works**, **Documentation**, **Sign in** (goes to `#/login`; when you are signed in it reads "Hi, <first name>" and goes to the workspace), coral **Launch App** (goes to `#/app/home`; signed-out visitors are then redirected to `#/login`) | Navigation | Top of page (sticky). On narrow screens the links hide behind a **Menu** button. |
| L2 | Compact two-column hero. Left: eyebrow "LIVING INTELLIGENCE · RESEARCH PROTOTYPE", three-line headline "Your metabolism / has a *story.* / Let's model it." (*story.* in italic coral), short paragraph, coral **Open the application** button and outlined **Explore the research** button | Introduction and calls to action. Both buttons should be visible **without scrolling** on a 1440 × 900 or 1280 × 800 screen | First screen |
| L3 | Hero status strip: **Model family**, **Engine**, **Backend** (with a green/amber/red status dot **and** words) | Shows live data from `/health` (engine version, short commit, backend status) | Under the buttons; fits inside the first screen on desktop |
| L4 | Organic artwork on the right with three callout boxes: *01 Forecast*, *02 Observe*, *03 Update* | Visual summary of the loop; hidden from screen readers (`aria-hidden`) | Right of hero (below the text on tablet and mobile) |
| L5 | **Product** section: "A twin that keeps its history." – three cards (Personal, not population-average / Honest about what it does not know / Auditable) | Product claims | Nav → Product |
| L6 | **How it works** dark section: "From real data to a living model." – 5 steps (Real data, Model, Forecast, Observation, Update), the equation, animated particle wave | Explains the loop; a slightly darker, immersive band inside the dark landing page | Nav → How it works |
| L7 | **Research** section: "What is established, and what is not." – Hypothesis, Evidence so far, Limitations | Research honesty; states the B-vs-C comparison was **inconclusive** | Nav → Research |
| L8 | **Documentation** section: 4 links (Model B vs Model C report, Backend architecture, Real-data runbook, Blueprint conformance) | Links to the repository docs on GitHub (new tab) | Nav → Documentation |
| L9 | Footer: brand, **Source repository** link, verbatim disclaimer | Disclaimer and source | Bottom |

### 2.2 Dashboard shell (every `#/app/...` page)
| # | Element | Purpose |
|---|---|---|
| S1 | "Skip to content" link | Keyboard shortcut past the sidebar (appears on first Tab) |
| S2 | Left sidebar: brand (back to landing), nav **Home, My Twin, Forecast, Observations, History, Insights, Settings** | Navigation; current page marked `aria-current` |
| S3 | Sidebar footer: **Backend** status pill (OK / degraded / Unreachable / Checking); **Signed in** box with your name, a **Guest** badge for guest accounts, a guest-mode note, and a **Log out** button; **Open twin** name | Quick status and sign-out |
| S4 | Persistent disclaimer bar at the top of the main column (label "RESEARCH PROTOTYPE" + verbatim text) | Always visible disclaimer |
| S5 | Red "Backend not reachable" banner | Shown when the health check fails |
| S6 | Hidden live-region (screen-reader announcements) | Announces action results such as "Twin updated: version 0 → 1." Visible only in DevTools; `data-testid="announcer"` |
| S7 | **Menu / Close** button (below 960 px width) | Collapses the sidebar navigation on narrow screens |

### 2.3 Dashboard pages
| Page (address) | Panels, controls and states |
|---|---|
| **Home** (`#/app/home`) | Twin header + pills; four stat cards (**Twin version, Meals observed, Awaiting outcome, Last forecast**); **Glucose response** chart with **Both models / Model C / Model B** buttons; **Recent activity** list; **Next step** panel. Empty state for an account with no twins: "You don't have a twin yet" with a **Create your first twin** button. |
| **My Twin** (`#/app/twin`) | Twin header; **Personalised parameters** table (Model B β; Model C β + γ·a at reference activity; Model C β; Model C γ) with mean and SD; **Version history**; **Provenance** (prior source, scheme, participant-level data flag, reference activity); an info box "Not available from this backend" listing state parts the backend does not provide. |
| **Forecast** (`#/app/forecast`) | **Meal** form (Carbohydrate (g), Pre-meal activity, Pre-meal glucose (mg/dL), Meal time (UTC), **Request forecast**); **Glucose response** chart; **Numbers behind the chart** table + data-quality notice; **Why this forecast?** (Model C / Model B toggle; plain-language lines; term table); **Compare scenarios** (what-if). |
| **Observations** (`#/app/observations`) | **Record an outcome** form (Forecast selector, Observed through (UTC), checkbox **Exclude this meal (data unusable)**, Observed maximum glucose in the window (mg/dL), Window completeness (0 to 1), **Record outcome**); **Apply to the twin** panel (list of recorded outcomes with **Apply** buttons). |
| **History** (`#/app/history`) | **Forecasts** table (Meal (UTC), Carbs g, P(max ≥ 180) C / B, Status, **Show**); **How the twin's parameters changed** chart; **Hit rate so far** (+ excluded meals list). |
| **Insights** (`#/app/insights`) | **How activity changes this twin's carbohydrate sensitivity** (Activity values field + **Update**, sensitivity chart); **Forecast versus outcome** table. |
| **Settings** (`#/app/settings`) | **Account** (name, email or "Temporary guest account", **Log out**); **Create a twin** form (Twin label, Prior source, Prior scheme, **Create twin**); **My twins** (your own twins from the backend, each with an **Open** button; empty and error states with **Try again**); **Backend** (API base URL, Status, Engine); verbatim disclaimer block. |

**Guest-mode note (S8):** for a guest account the sidebar says "Guest mode: a temporary account for demonstration. Its twins belong only to this guest and are lost to you when it ends." and shows a Guest badge. Registered accounts show their name and no guest note. **[Code][Run]**

### 2.3b Sign In and Create Account pages (real)
| Page | Elements |
|---|---|
| **Sign In** (`#/login`) | Brand link (top left), **← Back to home** (top right); left side: "Welcome back" + "Continue your research journey with GlycoTwin." + organic artwork; right panel: heading **Sign in**, "Access your GlycoTwin account", an optional notice (for example "Your session has ended. Please sign in again."), fields **Email address** and **Password** (with a **Show password** eye button), a form-level error area, button **Sign in →** (shows "Signing in…" while the request runs), a divider "or", button **Continue as demo** with an explanation of guest accounts, link "Don't have an account? **Create one**"; footer disclaimer bar. |
| **Create Account** (`#/register`) | Same frame; left: "Create your account" + "Start exploring personalised glucose responses with GlycoTwin."; panel: **Create account**, "Join GlycoTwin and start modelling.", fields **Full name**, **Email address**, **Password** (placeholder "At least 10 characters"), **Confirm password** (each password field has an eye button), a checkbox "I understand GlycoTwin is an investigational research prototype, not a medical device.", button **Create account →** (shows "Creating account…"), **Continue as demo**, link "Already have an account? **Sign in**". |
| **Deliberately absent** | Remember me, Forgot password (no recovery flow exists), social sign-in, terms/privacy links (no such pages exist), email verification, account deletion. |

**What these pages do:** they check the input in your browser, then call `POST /auth/register` or `POST /auth/login`. Success is shown only after the backend confirms it; the session is an **HttpOnly cookie** (page scripts cannot read it) and the passwords are never stored in the browser. **Continue as demo** calls `POST /auth/guest` and creates a temporary guest account. **[Code][Run]**

### 2.4 API-backed features
Every dashboard page except Settings' static text calls the backend. Mapping to endpoints is in Section 7. On start-up the app calls `GET /auth/me` (restore the session) and `GET /twins` (your twins); on every twin switch it calls `GET /twins/{id}`, `/forecasts`, `/history`, `/reconciliations`. All of these (except `/health` and the sign-in calls) need your session cookie. **[Code]**

### 2.5 State catalogue (what you should be able to see)
| State | Where it appears |
|---|---|
| Loading | "Loading twin" (spinner), "Loading explanation", "Requesting a forecast…", button labels like "Creating…", "Forecasting…", "Recording…", "Applying…", "Comparing…", "Loading…" |
| Empty | Home/My Twin etc.: "No twin selected"; chart: "No forecast to draw yet"; Observations: "No forecast is waiting for an outcome."; History: "No forecasts yet."; Insights: "No reconciled meals yet…" |
| Success | Green notices: "Twin “…” created at version 0.", "Forecast stored from twin version N.", "Observation recorded. The twin has not been updated yet.", "Twin updated: version A → B." |
| Error | Red notices/inline field errors (client-side range checks) and backend messages (404 "twin not found", 409 conflicts, 422 validation, 401 → back to Sign In with "Your session has ended…", 429 "Too many attempts…", network error with the uvicorn start command, "Cannot reach the backend" with **Try again**) |

### 2.6 Implemented vs not implemented
**Implemented:** account registration, sign in, sign out, temporary guest accounts, HttpOnly session cookies, scrypt password hashing, session restore after reload, protected dashboard pages, backend-enforced twin ownership (another account gets the same 404 as for a twin that does not exist), `GET /twins` (your own twins only), a one-way claim script for old unowned twins.

**Not implemented (do not look for them):** password recovery ("Forgot password"), email verification, account deletion, "remember me", cleanup of old guest accounts, persistent login rate limits (the counters reset when the backend restarts), per-user twin labels (labels are globally unique), editing or deleting a twin/forecast/observation, importing glucose files or CGMacros data, exporting CSV, a real glucose-over-time trace, notifications, dosing/diet advice (intentionally excluded), a "13-screen" blueprint dashboard (only the 7 pages above), meal-photo features, heart-rate features (the backend lists HR deviation as "not built"), an administrator role, any external security audit. **[Code]**

**Exposed by the API but with no UI control:** `reference_activity` and `glycaemic_group` on twin creation; optional forecast fields `activity_coverage`, `baseline_age_minutes`, `trend_slope_30min`, `time_since_last_meal_min`; `limit`/`offset` on the forecast list (UI loads up to 100); `reference_activity` query on `GET /twins/{id}` and `/history`; gamma width for the blueprint prior. Use `/docs` to try them. **[Code]**

---

## 3. Step-by-step manual test cases

**Conventions**
* "Open …" means type the address in the browser. "App" = `http://127.0.0.1:5173/` (use your printed port).
* Each case lists: **ID · Purpose · Start · Steps · Data · Expected · Pass/Fail rule · If it fails · State effect · Prerequisites/limits**.
* **State effect:** *None* = nothing stored; *Browser only* = changes your browser's local storage; *DB write* = writes to the backend database (new rows; nothing is ever deleted by the app).
* Before the first case, read Section 4.1 and decide whether to use a throw-away database.
* Unless stated, test on a desktop-width window (~1440 px).

### A. Landing page

**LP-01 · Hero and calls to action**
* Start: `#/`. Steps: 1) Read the hero. 2) Click **Open the application**. 3) Press Back. 4) Click **Explore the research**.
* Expected: hero text as in L2; step 2 opens the Home dashboard (`#/app/home`); step 4 scrolls to the Research section (address becomes `#/research`). **[Code][Run]**
* Pass: both buttons navigate; no blank page; no red errors in the Console. Fail rule: a blank or unstyled page or a console error. If it fails: Section 9 ("Browser console errors").
* State effect: None. Prerequisite: frontend running (backend not required).

**LP-01b · First screen fits (no scrolling needed for the main actions)**
* Start: `#/` in a fresh tab at **1440 × 900** (DevTools device toolbar, Section 5), then repeat at **1280 × 800**. Do not scroll.
* Expected **[Run, Linux Chromium]**: the dark navigation (about 58 px) is compact; the three-line headline is readable and not oversized; **both** buttons **Open the application** and **Explore the research** are fully visible; the status strip (Model family / Engine / Backend) is also visible; the artwork is on the right and its three callouts (01 Forecast, 02 Observe, 03 Update) are readable and do not overlap the headline. In the author's run the buttons ended at about 650 px (1440 × 900) and 570 px (1280 × 800) from the top and the strip at about 750 px and 685 px. Fonts differ by operating system, so your pixel values may differ; the criterion is "visible without scrolling".
* Pass: both buttons and the strip visible at both sizes; nothing clipped or overlapping; no horizontal scrollbar. Fail rule: you must scroll to see either button, text overlaps the artwork, or content is cut off. Smaller windows (for example 1280 × 600) are *expected* to need scrolling (the hero grows rather than clipping).
* State effect: None.

**LP-02 · Live backend metadata**
* Start: `#/` with the backend running. Steps: read **Model family / Engine / Backend** under the hero buttons.
* Expected: Engine like `v0.0.1 · <7-character commit>`; Backend `online · database ok`. **[Run]**
* Then stop the backend (Ctrl+C), refresh. Expected: Engine `backend offline`, Backend `not running`. Restart the backend afterwards.
* Pass: both states display and the page does not crash. State effect: None.

**LP-03 · Navigation anchors**
* Steps: click **Product**, **Research**, **How it works**, **Documentation** in the top bar.
* Expected: page scrolls (smoothly) to the matching section; the address shows `#/product`, `#/research`, `#/how`, `#/docs`. **[Code]**
* Pass: each lands on the right section. Note: after clicking, check the heading you landed on is not hidden under the sticky top bar. Record in notes if it is.

**LP-04 · Product section**
* Steps: scroll to "A twin that keeps its history." Read the three cards.
* Expected: *Personal, not population-average*; *Honest about what it does not know*; *Auditable*. Cards are readable and none overflow the screen.
* Pass/fail: text matches and is legible. Cross-check claims later with RI-04 (they must stay true).

**LP-05 · "How it works" (dark section, particle wave)**
* Steps: scroll to the dark section. 1) Read all five steps. 2) Look at the equation line. 3) Watch the dotted wave at the bottom for ~5 seconds. 4) Scroll it off-screen and back.
* Expected: five numbered steps 01–05; equation `rise = (βi + γi·ai) · ci + εi`; slow-moving particles. **[Code]** Particles pause when off-screen. **[Code, Unverified visually]**
* Pass: text is readable on the dark background; the page stays smooth. Reduced motion: see VR-08.
* Content check: step 01 says the CGMacros data **stays on the researcher's machine** and the app never loads it. Confirm you did not see any dataset values anywhere.

**LP-06 · Research claims**
* Steps: read "Evidence so far" and "Limitations".
* Expected: states a first matched comparison on 963 meals from 34 participants was **inconclusive**, "No claim of superiority is made", and the limitations list ends with "Not clinically validated. Not a diagnostic or dosing tool." The 963 / 34 figures are sourced from `docs/model_card.md` (not re-verified against the real data by this guide). **[Code]**
* Pass: wording is "inconclusive"; there is no sentence claiming Model C is better. Fail: any "outperforms", "improves accuracy", "validated". (Also covered by an automated test.)

**LP-07 · Documentation links**
* Steps: click each of the four links.
* Expected: each opens a new tab on GitHub (`.../tree/claude/glycotwin-initial-scaffold-gegpzd/docs/...`). **[Code]** These work only if that branch is pushed and the repository is visible to you; a 404 means the branch name or repository visibility changed, not a bug in the app. **[Unverified]**

**LP-08 · Footer and disclaimer**
* Steps: scroll to the bottom. Compare the boxed text with the disclaimer at the top of this guide.
* Pass: identical, word for word. Also **Source repository** opens the GitHub repository.

**LP-09 · Responsive menu (landing)**
* Start: `#/`, device width 390 px (Section 5). Steps: 1) Confirm the top links are hidden and a **Menu** button is shown. 2) Click **Menu** – the links (**Product, Research, How it works, Documentation, Sign in**) and **Launch App** appear and the button reads **Close**. 3) Click **Research**. 4) Reopen, click **Sign in** (expect `#/login`), press the browser Back button, reopen and click **Close**.
* Expected: menu closes after choosing a link; page scrolls to Research; no sideways scrolling. **[Run]** (a bug where the Menu button was invisible on the landing page was found and fixed before this guide.)
* Pass: all six items reachable by touch/click. State effect: None.

**LP-10 · Keyboard on landing**
* Steps: refresh, press **Tab** repeatedly. Expected: first stop is "Skip to content"; every link/button gets a visible outline. Press **Enter** on "Skip to content": focus jumps to the main content.
* Note: this is a keyboard check only; it does not prove accessibility compliance.

### A2. Accounts: Create Account, Sign In, sessions, guest mode, ownership (real)

> **Read this first.** These pages now use the **real** backend. Use fake details only (name `Test Person`, email `test.person@example.com`, password `windows-test-pass-1`). Use the throw-away database from Section 1.6b/4.1 so your real database is untouched. A test passes when the page does what the backend confirms and never claims more than that.

**AU-01 · Open the pages and move between them**
* Start: `#/`. Steps: 1) Click **Sign in** in the top navigation. 2) Click **Create one**. 3) Click **Sign in** (bottom link). 4) Click **← Back to home**. 5) Type `http://127.0.0.1:5173/#/register` into the address bar and press **F5**. 6) Repeat for `#/login`.
* Expected **[Run]**: `#/login` shows "Welcome back" and the **Sign in** panel; `#/register` shows "Create your account" and the **Create account** panel; Back to home returns to `#/`; refresh keeps you on the same page; the tab title reads "Sign in · GlycoTwin (research prototype)" or "Create account · GlycoTwin (research prototype)". `#/forgot-password` shows the landing page (no such page exists).
* Pass: all links work; no console errors; no horizontal scrollbar. State effect: None.

**AU-02 · Visual consistency with the landing page**
* Compare `#/`, `#/login`, `#/register`: the same dark olive/chocolate background, ivory type, serif headings, coral primary button, organic artwork, thin contour lines, translucent bordered panel. At 1440 × 900 the Sign In panel fits on screen; the Create Account panel may need a small scroll. **[Run]**
* Pass/fail: judge by eye; record a screenshot of anything inconsistent (light text on a light background would be a bug).

**AU-03 · Create an account (success)**
* Start: `#/register`. Steps: **Full name** `Test Person`; **Email address** `test.person@example.com`; **Password** and **Confirm password** `windows-test-pass-1`; tick the acknowledgement; click **Create account →**.
* Expected **[Run]**: the button shows "Creating account…" for a moment, then the dashboard opens at `#/app/home`; the sidebar shows **Signed in — Test Person** and a **Log out** button; Settings → **Account** shows your name and email.
* Pass: you land on the dashboard **and** the name is shown. Fail (serious): the dashboard opens but the name is missing, or you reach the dashboard without the backend having confirmed (check Network: `POST /api/auth/register` must show **201**).
* State effect: **DB write** (one `users` row with a password hash, one `sessions` row) and a browser cookie. The password is not stored anywhere in plain text.

**AU-04 · Create Account validation (checked in the browser, nothing is sent)**
* Click **Create account →** with everything empty. Expected messages **[Run]**: "Enter your name.", "Enter your email address.", "Choose a password.", "Confirm your password.", "Please acknowledge that GlycoTwin is a research prototype." Focus moves to the first invalid field.
* Then: password `short` (confirm `short`) → "Use at least 10 characters."; a 129-character password → "Use at most 128 characters."; password `windows-test-pass-1` with confirm `different` → "The two passwords do not match."; email `not-an-email` → "Enter a valid email address, such as name@example.com."
* Pass: each message appears next to its field and the Network tab shows **no** `/auth/register` request while any message is showing. State effect: None.

**AU-05 · Duplicate email**
* Register again with the same email (any case, e.g. `TEST.PERSON@example.com`). Expected **[Run]**: "An account with this email already exists. Try signing in instead." under the email field; you stay on `#/register`; nothing is signed in. (Network: `POST /api/auth/register` → **409**.) State effect: None.

**AU-06 · Password rule enforced by the backend**
* A password that is the same as the email (`test.person@example.com` is long enough) should be refused with a message under the Password field such as "password must not be the same as the email address". **[Code, Unverified in the UI]** Record what you see. The backend also refuses a very repetitive password such as `aaaaaaaaaaaa` ("password is too repetitive"). State effect: None.

**AU-07 · Sign in (success)**
* Log out first (AU-12) or open a private window. Start: `#/login`. Email `Test.Person@Example.com` (capitals do not matter) and password `windows-test-pass-1` → **Sign in →**.
* Expected **[Run]**: "Signing in…", then the dashboard; sidebar shows **Test Person**. Network: `POST /api/auth/login` → **200**. State effect: **DB write** (a new session row; the old sessions are unaffected).

**AU-08 · Wrong password and unknown email**
* Wrong password for the real email, then a made-up email with any password. Expected **[Run]** both times: the **same** message "Incorrect email or password." (the page must not say which part was wrong, so nobody can discover which emails have accounts). The password box is cleared; you stay on `#/login`. Network: **401**.

**AU-09 · Too many wrong attempts (rate limit)**
* **Use a throw-away account and database only.** Enter a wrong password 5 times for the same email, then a 6th time (even with the right password). Expected **[Run, via the API]**: the backend answers **429** and the page shows "Too many attempts. Please wait about 15 minute(s) and try again." Another email is not affected. The counter is in memory: **stopping and restarting the backend clears it**. This locks that email for 15 minutes, which is why you must not do this to a real account.

**AU-10 · Password visibility toggle**
* Type a password; click the eye button (**Show password**). The text becomes visible, the button name changes to **Hide password** (pressed state); click again to hide. On Create Account the confirm field's button is **Show confirm password**. Pass: both directions work and the toggle is reachable with Tab/Enter. **[Run]**

**AU-11 · The session survives a reload**
* Signed in on any dashboard page, press **F5**. Expected **[Run]**: a brief "Checking your session…" screen, then the **same page** and your name — you do not have to sign in again. (The browser sent the cookie; the app asked `GET /auth/me`.) Network: `GET /api/auth/me` → **200**.
* Also: close the tab, open `http://127.0.0.1:5173/#/app/home` in a new tab: still signed in (until the session expires, 7 days by default).

**AU-12 · Log out**
* Click **Log out** (sidebar, or Settings → Account). Expected **[Run]**: you land on `#/login`; Network shows `POST /api/auth/logout` → **200**. Then go to `#/app/history`: you are sent back to `#/login`. Pressing the browser Back button does not show your data. State effect: the session is **revoked on the server** (the old cookie value no longer works).

**AU-13 · Signed-out visitors cannot open the dashboard**
* In a private window (or after logging out) open `http://127.0.0.1:5173/#/app/forecast`. Expected **[Run]**: you end on `#/login`; no twin data is shown. Repeat for each `#/app/...` page. A signed-in user who opens `#/login` or `#/register` is sent to `#/app/home`.

**AU-14 · Expired or revoked session**
* Sign in, open Forecast, fill the form. Now remove the session in **another way**: (a) open a second tab on the same site and **Log out** there, or (b) DevTools → Application/Storage → Cookies → delete `glycotwin_session`. Back in the first tab click **Request forecast**.
* Expected **[Run, equivalent server-side expiry]**: you are sent to `#/login` and the page says "Your session has ended. Please sign in again." Nothing was saved. State effect: None.

**AU-15 · Cookie and storage inspection (security check)**
* DevTools → Application → Cookies: `glycotwin_session` must show **HttpOnly** ✓, **SameSite Lax**, Path `/`; **Secure** is unticked on `http://127.0.0.1` (correct for local use). **[Run]** In the Console type `document.cookie` → it must **not** contain `glycotwin_session` (scripts cannot read it). Local Storage should contain at most `glycotwin.active.<your user id>.v2` (the last-open twin id) — **no password, no token, no glucose values**. Search the Network request payloads: the password appears only in the `register`/`login` request body, once.

**AU-16 · Things that must NOT be there**
* No "Remember me", no "Forgot password?", no social sign-in, no terms/privacy links, no way to delete your account, no administrator pages. Pass: none present. (A "Forgot password?" link without a real recovery flow would be misleading.)

**AU-17 · Keyboard and focus**
* On `#/login` press Tab repeatedly. Expected order **[Run]**: Skip to content → GlycoTwin (brand) → ← Back to home → Email address → Password → Show password → Sign in → Continue as demo → Create one; every stop has a visible outline. Repeat on `#/register`. **Enter** inside a field submits. Keyboard spot-check only, not an accessibility audit.

**AU-18 · Responsive auth pages**
* At **1440 × 900, 1280 × 800, 768 × 1024 and 390 × 844**: no horizontal page scrolling; the panel is fully reachable; the artwork stays decorative (faint on narrow screens); inputs are comfortably tappable. **[Run]** (no overflow at those sizes). State effect: None.

**DM-01 · "Continue as demo" (temporary guest account)**
* Start: `#/login` or `#/register`. Read the note under the button: "Demo mode creates a **temporary guest account**. Its twins belong only to that guest and are never visible to any other account, but you cannot sign back in to it later. Do not enter personal health data."
* Click **Continue as demo**. Expected **[Run]**: the dashboard opens; the sidebar shows **Signed in — Guest** with a **GUEST** badge and the note "Guest mode: a temporary account for demonstration…"; Settings → Account shows **Temporary guest account**; Network: `POST /api/auth/guest` → **201**.
* Pass: it is clearly labelled as a temporary guest account and you can create and use your own twin. State effect: **DB write** (a guest `users` row with no email and no password, plus a session lasting 24 hours by default).

**DM-02 · What guest mode does and does not do**
* A guest **cannot** sign in again: after **Log out**, or after you clear cookies or the 24 hours pass, that guest account and its twins can no longer be reached by anyone through the website. Registering a real account later does **not** move guest data. Expired guest accounts are not cleaned up (they stay in the database).
* Known quirk **[Code, Unverified]**: Settings → Account shows a "Create a real account" link, but while you are signed in as a guest, opening `#/register` redirects you to the workspace. To register, click **Log out** first, then **Create account**. Record what you see.

**OW-01 · Two accounts cannot see each other's twins (UI)**
* Browser window 1: register `Test Person` and create twin `ownership-a1` (Settings). Window 2 (a **private/incognito** window, so it has its own cookies): register `Second Person` (`second.person@example.com`). Settings → **My twins** in window 2 must say "You have no twins yet." and must **not** list `ownership-a1`. Create `ownership-b1` in window 2; window 1's list must not show it.
* Pass: each account lists only its own twin. **[Run]** (verified with two accounts and a guest). State effect: DB writes (two twins, each with one owner row).

**OW-02 · Probing another account's twin directly (API through the browser)**
* In window 1 (Test Person) open DevTools → Network → click any request to `/api/twins/<id>/...` and copy the 36-character twin id of `ownership-a1`. In window 2's Console run (replace `<ID>`): `fetch('/api/twins/<ID>/history').then(r => r.json().then(j => console.log(r.status, j.detail)))`.
* Expected **[Run]**: `404 twin not found` — **identical** to what you get for a made-up id such as `123e4567-e89b-12d3-a456-426614174000`. The website never says "this twin belongs to someone else". Repeat with `/forecasts`, `/reconciliations` and with `POST .../forecast` if you like: always 404.

**OW-03 · Not signed in at all**
* In a private window with no sign-in, open `http://127.0.0.1:5173/api/twins` (or `http://127.0.0.1:8000/twins`). Expected **[Run]**: `{"detail":"not signed in", ...}` (HTTP 401). The same for `.../api/twins/<ID>` — the answer is 401 whether or not the id is real.

**OW-04 · The twin list is owner-scoped**
* In window 1 Console: `fetch('/api/twins').then(r => r.json()).then(j => console.log(j.data.twins.map(t => t.label)))`. Expected **[Run]**: only that account's twins (for example `["ownership-a1"]`), never another account's or old unowned twins.

**OW-05 · Labels are globally unique (known limitation)**
* In window 2 try to create a twin named `ownership-a1`. Expected **[Run, via the API]**: red "a twin with this label already exists" (409). This reveals only that the label is taken — never the id or any data — and is an accepted limitation: labels stay globally unique for now.

**CL-01 · Claiming an old (unowned) twin with `scripts\claim_twin.py`**
* Why: twins created before accounts existed (and the demo twin from `scripts\init_db.py --demo`) have **no owner and are hidden from everyone**. Use a throw-away database. Stop the backend (Ctrl+C) first so nothing writes while you claim. Project root, same `$env:GLYCOTWIN_DATABASE_URL` as the backend:
  1. `python scripts\init_db.py --demo` → prints JSON with `"demo_twin_id"` (a **synthetic** twin, label `demo-synthetic-001`).
  2. `python scripts\claim_twin.py --list-unowned` → lists it (id, label, number of forecasts). The first output line is the database path it is using — check it is your **test** file.
  3. Register an account in the browser first (needed: the person must already exist). Then dry run: `python scripts\claim_twin.py --twin-id <id> --email test.person@example.com` → ends with "DRY RUN: nothing was changed". Refresh Settings: still hidden.
  4. Claim: add `--apply` → JSON with `"applied": true`. Start the backend again, sign in, Settings → **My twins** now lists `demo-synthetic-001`; History shows its saved forecasts.
  5. A second account does **not** see it. Run step 4's command again with another email (and `--apply`): expected `REFUSED: this twin already has an owner; ownership is never transferred or overwritten` and exit code 2 (`$LASTEXITCODE` in PowerShell).
* Pass: the twin appears only for the claimant, and an owned twin can never be re-claimed. The script only **adds** one `twin_owners` row; it never edits twins, forecasts or history. Never run it on your real database before taking the backup in 1.6b.

**DM-03 · The existing workflow still works**
* Run the full walkthrough in Section 6 as a registered account and again as a guest. Pass: every step behaves the same (forecast, observation, apply, history, insights, explanation, what-if, sensitivity, reconciliation view).

### B. Dashboard shell and navigation

**SH-01 · Sidebar navigation**
* Start: `#/app/home`. Steps: click each sidebar item in turn.
* Expected: title (big heading) changes to Home, My Twin, Forecast, Observations, History, Insights, Settings; the current item is highlighted with a gold left bar; the address changes to `#/app/<view>`.
* Pass: 7 pages load without errors. Also type `#/app/bogus` manually: expected to show Home (unknown view falls back to Home). **[Code]**

**SH-02 · Persistent disclaimer**
* Steps: open every dashboard page and scroll down.
* Expected: the disclaimer bar is visible at the top of every page on desktop (sticky); on narrow screens (< 960 px) it stays at the top of the page but scrolls away. **[Code]** Text is identical to the required wording.
* Pass: present on all 7 pages. Settings additionally shows the disclaimer as a block at the bottom. The landing page footer and both auth pages also show the disclaimer.
* Also check the sidebar footer (desktop) or the opened Menu (mobile): your name under **Signed in**, a **Log out** button, and for a guest account a **GUEST** badge plus the guest-mode note (S8).

**SH-03 · Backend status pill and offline banner**
* Steps: with the backend running look at the sidebar footer ("Backend": **✓ OK**). Stop the backend, refresh the page.
* Expected: pill **✕ Unreachable**; red banner "Backend not reachable. Cannot reach the GlycoTwin backend. Start it with: python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000". **[Run]** Restart the backend and refresh to recover.
* State effect: None.

**SH-04 · Mobile menu (dashboard)**
* Start: `#/app/home` at 390 px. Steps: 1) Only the brand and a **Menu** button show. 2) Click **Menu** – nav list and backend status appear; button reads **Close**. 3) Click **Forecast** – menu closes and Forecast opens.
* Pass: all seven pages reachable; no horizontal scroll.

**SH-05 · Keyboard order and skip link**
* Steps: on a dashboard page press Tab. Expected order: Skip to content → GlycoTwin (brand) → Home … Settings → page content. **[Run]** Each stop shows a visible outline. Press Enter on "Skip to content": focus moves to the main area.

**SH-06 · Screen-reader announcements (developer check)**
* Steps: in DevTools Elements panel find `data-testid="announcer"`. Create a twin (TW-01). Watch its text.
* Expected: it contains the success message (for example "Twin “…” created at version 0."). **[Code]** A real screen reader test is outside this guide (Section 5.6).

**SH-07 · Signed-in box and Log out in the sidebar**
* Expected: **Signed in** with your name; on a phone-width screen it is inside the **Menu**. **Log out** works as in AU-12. The text is readable (an earlier version used a dark grey on the near-black sidebar; confirm it is now light). **[Run]**

### C. Home dashboard

**HM-01 · Empty state (no twin)**
* Prerequisite: a **new account** that has no twins (register a fresh test account, or use a guest). Clearing site data no longer matters for this: your twins are saved in your account, not in the browser.
* Steps: open `#/app/home`.
* Expected **[Run]**: heading **Home**; "You don't have a twin yet" panel explaining what a twin is, with the button **Create your first twin** which goes to Settings. Only you can see the twins you create.
* Pass: no errors, no fake numbers. State effect: None.

**HM-02 · Summary cards with a fresh twin**
* Prerequisite: TW-01 done (new twin, version 0). Open Home.
* Expected **[Run]**: header with twin label, short id, "version 0", created time (UTC); pills **SYNTHETIC DEMONSTRATION PRIOR** and **SCHEME: EMPIRICAL_BAYES**; stats: Twin version **0**, Meals observed **0**, Awaiting outcome **0**, Last forecast **n/a** ("no forecast yet"); chart panel shows "No forecast to draw yet"; Recent activity "Nothing yet…"; Next step "Request the first forecast. Go to Forecast".
* Pass: all of the above and the link goes to Forecast.

**HM-03 · Home after a forecast and an applied outcome**
* Prerequisite: complete the workflow in Section 6 up to step 7. Open Home.
* Expected: Twin version and Meals observed increase after applying; **Last forecast** shows the latest forecast's Model C probability; the chart shows the selected forecast, with an observed marker only if that forecast has a real observation; **Recent activity** lists forecasts and "Twin updated to version N"; **Next step** text changes between "Request the first forecast", "A forecast is waiting for its real outcome", and "Everything recorded has been applied". **[Code]**
* **Known behaviour to record, not a test failure:** see HM-04.

**HM-04 · "Awaiting outcome" card meaning (known caveat)**
* Observation **[Run]:** the card showed **0** while forecasts were still pending. The number comes from the backend's `meal_state.forecasts_awaiting_reconciliation`, which counts forecasts whose 120-minute window had already closed *relative to the twin's latest event time*; the most recent forecast is counted as an "open meal window" instead. **[Code]** So the card can understate pending forecasts.
* Steps: after creating two forecasts, compare the card with the **History** page status pills and the **Observations** forecast selector.
* Pass: you understand the difference. Record the card's value in your notes. **Source of truth for pending forecasts = History and Observations**, not this card.

### D. My Twin

**TW-01 · Create a demonstration twin (valid)**
* Start: `#/app/settings`. Steps: 1) In **Twin label** type `demo-twin-1` (use a unique label each time). 2) Leave **Prior source** = "Synthetic demonstration prior (no real participants)". 3) Leave **Prior scheme** = "Empirical Bayes (default)". 4) Click **Create twin**.
* Expected **[Run]**: button shows "Creating…" briefly; green notice "Twin “demo-twin-1” created at version 0."; the twin appears under **My twins** marked **Open** with a shortened id like `1bf22e03…e561` and `v0`; the sidebar shows it as **Open twin**.
* Pass: notice + list entry + sidebar. State effect: **DB write** (one twin, version 0, **and one `twin_owners` row linking it to your account**) and **Browser only** (local storage key `glycotwin.active.<your user id>.v2`, which holds just the twin id).

**TW-02 · Label validation (client-side)**
* Start: Settings → Create a twin. For each input click **Create twin** and read the red text under the field:

| Input | Expected message |
|---|---|
| (empty) | "Use 1 to 64 letters, digits, dots, dashes, colons or underscores, starting with a letter or digit (no spaces)." |
| `bad label!` | same message |
| `-abc` | same message |
| `my-cgmacros-test` | "Labels that look like research participant ids are not accepted." |
| 65 characters | the field stops at 64 characters (maximum length) |

* Pass: no request is sent (Network tab shows no `POST /api/twins`) and no twin is created. **[Code][Run]** State effect: None.

**TW-03 · Duplicate label (409)**
* Steps: create `demo-twin-1` again with the same label. Expected: red notice "a twin with this label already exists". **[Run]** No second twin is created. State effect: None (rejected).
* Note: labels are unique across **all** accounts. If another account (or an old unowned twin) already uses the label you get the same message, even though you cannot see that twin; pick a new label (OW-05).

**TW-04 · Prior options**
* **Synthetic demonstration prior** is the tested path (TW-01).
* **Blueprint prior (opt-in)** as *Prior scheme*: create `demo-blueprint-1`. Expected: twin is created; the My Twin page shows scheme `blueprint`. **[Unverified in the UI]** (the backend supports it; record what you see).
* **Prior file already on the backend host** + a file name: the file must exist in the backend's prior directory (`data/interim/priors` by default, or `GLYCOTWIN_PRIOR_DIR`). With a name such as `missing.json` expect a red error "prior file not found in the configured prior directory"; a name that is not a plain `*.json` should say "prior file name must be a plain *.json file name inside the configured prior directory". **[Code, Unverified in the UI]** Leaving the file name empty shows "Name the prior file the backend should load." **[Code]**
* Do **not** create real prior files from participant data for testing.

**TW-05 · My Twin page content**
* Prerequisite: active twin. Open `#/app/twin`.
* Expected **[Run]** for a fresh demo twin (illustrative, depends on the engine): header; **Personalised parameters** caption "Posterior of the carbohydrate sensitivity (mg/dL rise per g)… n = 0 meals observed"; table with Model B β, Model C β + γ·a at reference activity 1.00, Model C β, Model C γ, each with Mean and SD; a "Posterior band width (90%)" line; **Version history** with "Version 0 … 0 observed meals · initial prior"; **Provenance** with Prior source `synthetic_demo`, Prior scheme, "Participant-level data in prior: no", Reference activity `1`; info box "Not available from this backend" listing items the backend does not compute.
* Pass: values are numbers (not `NaN`), SDs are positive, and nothing claims data the backend lacks. Compare any value with `GET /twins/{id}` (Section 7).
* After applying an outcome (OB-05): **n = 1 meals observed**, a new "Version 1" row "from v0", and parameter SDs smaller than before. **[Run]**

**TW-06 · My twins list and switching**
* Prerequisite: two twins in the same account (create `demo-twin-1` and `demo-twin-2`). Settings → **My twins**: both are listed with their version and short id; the active one shows **Open** (pill) and its button is disabled. Click **Open** on the other twin.
* Expected **[Run]**: the sidebar "Open twin" name changes and Home/History show the other twin's data. The list comes from the backend (`GET /api/twins`), so it is the same on any browser where you sign in. State effect: Browser only (last-open twin id).

**TW-07 · A twin list that cannot load**
* Stop the backend after signing in, then press F5 on `#/app/settings`. Expected **[Run]**: "Cannot reach the backend" with **Try again** (you are **not** signed out). Start the backend and click **Try again**: the app recovers. If the backend returns an error only for the list, Settings shows "Could not load your twins" with **Try again**. **[Run via automated test]**

**TW-08 · There is no "open by id" any more**
* The earlier "Open an existing twin" form and "Forget" button were removed: you can only open **your own** twins from the list. To check an id directly use OW-02. An id that is not yours behaves exactly like an id that does not exist (404 "twin not found").

**TW-09 · Refresh persistence**
* Steps: signed in, with an open twin on Forecast or History, press **F5**. Expected: you stay signed in (AU-11), the same twin reloads and its forecasts reappear (they come from the database); the **selected forecast** resets to the most recent one. **[Code][Run]**
* Not persisted after refresh: values you typed into forms; the *session-only* observed value of a recorded-but-not-applied outcome (see OB-09).

**TW-10 · Everything is still there after logging out and in (persistence of saved history)**
* Sign out (AU-12), sign in again (AU-07). Expected **[Run]**: **My twins** lists the same twins; History, Insights and Forecast show the same forecasts, observations, versions and parameter chart as before. Restarting the backend in between changes nothing. State effect: None.

### E. Forecast

> Use fixed illustrative dates so tests are repeatable. All dates below are **made-up demonstration times**, not real meals. Time zone is UTC.

**FC-01 · Valid forecast**
* Start: `#/app/forecast` with an active **version 0** demo twin. Steps: 1) **Carbohydrate (g)** `60`. 2) **Pre-meal activity** `0.3`. 3) **Pre-meal glucose** `110`. 4) **Meal time (UTC)** `2026-01-01 08:00` (type or pick). 5) Click **Request forecast**.
* Expected: button "Forecasting…" briefly; green notice "Forecast stored from twin version 0."; chart appears; **Numbers behind the chart** table appears; "Why this forecast?" loads; status pill **FORECAST · AWAITING OUTCOME**; a **Limited personal history** pill. **[Run]**
* Pass: all panels appear and show finite numbers. Compare the numbers to the backend response (FC-03). State effect: **DB write** (one forecast; the twin's state/version does **not** change).

**FC-02 · Read the chart correctly**
* Expected labels **[Run]**: y-axis "glucose (mg/dL)"; x-axis "minutes after the meal (t0) · outcome window (t0, t0 + 120 min]"; marker "meal · t0"; "pre-meal 110" at your input; dashed line "180 mg/dL outcome threshold"; two bands labelled "B · expected max … · 90% …–…" and "C · expected max … · 90% …–…"; right panel "DISTRIBUTION OF THE MAX" with "P(max ≥ 180) = …%" for each model; caption "…the model does not predict when it occurs, so no time course is drawn."
* **How to interpret:** each hatched band is the model's 90 % interval for the **highest** glucose in the window; the horizontal line is the expected highest value. They are drawn flat across the window *because the model does not say when* the maximum happens. **There is no glucose curve.**
* Pass: units mg/dL and minutes are present; window is 0–120 min; no smooth glucose curve is drawn.

**FC-03 · Chart equals table equals backend**
* Steps: 1) Read the numbers in **Numbers behind the chart** (columns: Model, P(max ≥ 180 mg/dL), Rise mean ± SD (mg/dL), 90% interval of the maximum (mg/dL)). 2) Compare with the chart labels. 3) DevTools → Network → find the `forecast` request (path `/api/twins/<id>/forecast`) → Response tab → compare `model_c.p_peak_at_least_180`, `mean_rise_mg_dl`, `sd_mg_dl`, `interval90_rise_mg_dl`.
* Expected: the table interval equals **pre-meal glucose + the interval of rise** (the API returns *rise above baseline*, the UI adds your baseline); the probability is shown as a percentage. **[Code]**
* Pass: chart = table = API within rounding. If the three disagree it is a bug: record screenshots.

**FC-04 · Model buttons**
* Steps: click **Model C**, then **Model B**, then **Both models**. Expected: only the chosen model's band/line/density is drawn; the pressed button is dark. **[Run]**

**FC-05 · Input validation (client-side)**

| Field | Input | Expected red message |
|---|---|---|
| Carbohydrate | empty / `abc` / `-1` / `501` | "Carbohydrate is required." / "…must be a number." / "…must be between 0 and 500." |
| Pre-meal activity | `5` (demo twin) | "Activity level must be between 0 and 1." |
| Pre-meal activity | `-0.1` or `abc` | between-range / number message |
| Pre-meal glucose | empty / `19` / `601` | "Pre-meal glucose is required." / "…must be between 20 and 600." |
| Meal time | cleared | "Meal time is required." |

* Boundary values that must be **accepted** (no red text): carbohydrate `0` and `500`; glucose `20` and `600`; activity `0` and `1` (demo twin). Expected backend behaviour for `0` g: accepted by the schema; **[Unverified]** result, compare with the API.
* Pass: no request is sent for invalid values (Network tab). State effect: None for rejected input.

**FC-06 · Backend rejection the form cannot pre-empt**
* Back-dated forecast: see FC-07. Unknown twin: TW-08, then open Forecast → expected "No twin selected" (form hidden).

**FC-07 · Back-dated forecast refused (409)**
* Prerequisite: forecast **FC-01** has been recorded **and applied** (OB-05). Steps: request a new forecast with **Meal time (UTC)** `2026-01-01 09:00` (only 60 minutes after the first meal), glucose `105`.
* Expected **[Run]**: red notice "the twin already learned from an outcome window that closes after this meal time; a back-dated forecast is refused". Nothing stored.
* Then use `2026-01-01 12:00`: expected "Forecast stored from twin version 1." **[Run]** (Rule **[Code]**: the new meal time must be at least 120 minutes after the latest *applied* meal.)

**FC-08 · Repeated forecasts**
* Steps: with the form filled, click **Request forecast** twice in a row.
* Expected **[Run]**: **two separate forecasts** are stored, because the form creates a new internal meal identifier after every successful request. The History table then lists two rows with the same meal time. (Re-sending the *same* meal identifier is idempotent at the API level, status 200 `created:false`, but the UI cannot do that.) **[Code]**
* Pass: you can see the duplicate in History. Note it as a usability limitation (Section 12).

**FC-09 · Data-quality notice**
* With 0 observed meals expect an amber notice "Data-quality flags (from the backend)" containing "Insufficient personal history: 0 observed meals so far." and the backend's statement that "The predictive probability and interval are NOT changed for data quality…". **[Run]** With 3 or more applied meals the "insufficient history" flag should disappear. **[Code, Unverified]**
* Pass: the notice does not claim the interval was widened unless the backend says `interval_adjusted`.

**FC-10 · Explanation panel ("Why this forecast?")**
* Steps: read the plain-language lines; click **Model B**, then **Model C**.
* Expected **[Run]**: sentences such as "model_c expects a peak rise of … for 60 g carbohydrate at activity 0.3."; a table "Contribution of each term to the predicted rise (mg/dL)" with rows `carbs_g` and `carbs_x_activity` (Model C) or only `carbs_g` (Model B); "Share of predictive variance due to parameter uncertainty: …%". The explanation is computed on the twin **as it was when the forecast was made**. **[Code]**
* State effect: None (read-only).

**FC-11 · Selecting an older forecast**
* History → **Show** on another row → the chart on Home/Forecast switches to that forecast. Expected: the status pill and (if observed) the teal observed marker match that forecast.

### F. Observations and applying them

> **Key rule [Code][Run]:** the app does **not** wait two real hours. The only requirement is that **Observed through (UTC)** is at least 120 minutes after the **meal time you entered**. The form pre-fills exactly `meal time + 120 minutes`. For a demonstration you can record an outcome immediately. In real use the number you enter must be a real measurement.

**OB-01 · Empty state**
* Prerequisite: twin with no pending forecast. Open Observations. Expected: "No forecast is waiting for an outcome." and under **Apply to the twin**: "No recorded outcome is waiting to be applied." **[Run]**

**OB-02 · Record an outcome (valid)**
* Prerequisite: pending forecast from FC-01. Steps: 1) Observations. 2) **Forecast** shows `2026-01-01 08:00 UTC · 60 g`. 3) **Observed through (UTC)** is pre-filled `2026-01-01 10:00`. 4) **Observed maximum glucose in the window (mg/dL)** `185` (illustrative). 5) **Window completeness (0 to 1)** `1`. 6) **Record outcome**.
* Expected **[Run]**: green "Observation recorded. The twin has not been updated yet."; the right panel lists "2026-01-01 08:00 UTC · 60 g · observed max 185 mg/dL" with an **Apply** button; the forecast's status becomes **OBSERVED · NOT YET APPLIED**; the Twin version and Meals observed on Home are **unchanged**; the chart on Home/Forecast now shows a teal "observed max 185" marker.
* Pass: observation visible but twin version unchanged. State effect: **DB write** (one observation); twin state not changed.

**OB-03 · Incomplete outcome window (422)**
* Prerequisite: another pending forecast (create one at least 120 min after the last applied meal, e.g. `2026-01-01 12:00`). Steps: set **Observed through (UTC)** to `2026-01-01 13:59` (119 min) and a glucose of `150`, **Record outcome**.
* Expected: red "the outcome window is not complete: observed_through must be at or after meal_time + 120 minutes". **[Run]** Nothing stored; the forecast stays pending.
* Boundary: `2026-01-01 14:00` (exactly 120 min) must be accepted. **[Code]**

**OB-04 · Input validation (client-side)**

| Field | Input | Expected |
|---|---|---|
| Observed maximum glucose | empty / `abc` / `19` / `601` | "…is required." / "…must be a number." / "…must be between 20 and 600." |
| Window completeness | `1.5` or `abc` | "…must be between 0 and 1." / number message; empty is allowed (not sent) |
| Exclude + reason | reason empty or 2 characters / over 200 | "Give a reason of 3 to 200 characters." |

* Accepted: glucose `20` and `600`; completeness `0` and `1`. Backend would accept a peak below the pre-meal glucose; **[Unverified]** what it shows, compare with the API.

**OB-05 · Apply the observation (state-changing)**
* Prerequisite: OB-02 done. Steps: in **Apply to the twin** click **Apply**.
* Expected **[Run]**: button "Applying…"; green "Twin updated: version 0 → 1."; a line like "Model C β: 0.863 → 1.047; its SD ratio 0.76." (illustrative; the SD ratio is below 1 when the observation narrowed the estimate); the Apply row disappears; Home shows Twin version 1, Meals observed 1; the forecast is **RECONCILED · TWIN UPDATED**; My Twin shows Version 1 "from v0" and n = 1; History parameter chart now has v0 and v1.
* Pass: version increased by exactly one and the old version still appears in Version history (nothing overwritten). State effect: **DB write** (new twin version, parameter snapshots, reconciliation row).
* Repeat check: reload the page and open Observations again: the Apply row must not return. A repeated reconcile API call returns the stored result (HTTP 200, `created:false`) and does **not** update twice. **[Code]**

**OB-06 · Exclude a meal (no update)**
* Prerequisite: a pending forecast. Steps: tick **Exclude this meal (data unusable)**; the glucose fields are replaced by **Reason**; type `sensor gap over 30 minutes`; **Record outcome**; then **Apply**.
* Expected: notice "Exclusion recorded. Applying it will leave the twin unchanged." then "Excluded: the twin was not changed."; Twin version **does not change**; the forecast becomes **EXCLUDED · NO UPDATE**; History → "Excluded meals" lists it. **[Code]** (UI path **[Unverified]**; backend behaviour is covered by backend tests.)
* State effect: **DB write** (observation + exclusion record), twin version unchanged.

**OB-07 · Second outcome for the same forecast**
* After OB-02, the forecast no longer appears in the **Forecast** drop-down (only pending forecasts are listed), so the UI cannot attempt a replacement. At API level a different second observation returns 409 "an observation was already recorded for this forecast; it cannot be replaced". **[Code]** Try it in `/docs` if you want to see the message.

**OB-08 · Apply without an observation (API only)**
* The UI never shows **Apply** for a forecast without an observation. In `/docs`, `POST /twins/{id}/reconcile` with a pending forecast id returns 409 "no observation has been submitted for this forecast yet". **[Run]**

**OB-09 · Refresh between record and apply**
* Steps: record an outcome (OB-02) but **do not** apply; press **F5**; open Observations.
* Expected: the **Apply** row still exists (status comes from the database), but the row shows only the date and carbohydrate amount, **not** the observed value, and the Home chart no longer shows the teal marker. The observed value of an unapplied outcome is held only in the page's memory and is lost on refresh. **[Code]** (Observed values reappear after applying, taken from the reconciliation record.)
* Pass: you can still apply it. Record as a known limitation (Section 12).

### G. History

**HI-01 · Empty history**
* New twin → History. Expected **[Run]**: "No forecasts yet."; "Only one twin version exists. The parameter trajectory appears after the first reconciliation."; "Hit rate so far: Reconciled meals: 0. Model C n/a · Model B n/a" and the note "Descriptive only…".

**HI-02 · Forecast table**
* After several forecasts: columns Meal (UTC), Carbs g, P(max ≥ 180) C / B, Status, **Show**. Newest meal listed first; statuses use label **and** symbol (◆ forecast, ● observed, ✓ reconciled, ▲ excluded). **[Run]** The table scrolls sideways *inside its own box* on small screens (focusable region "Forecast history").
* Pass: values match the API (`GET /twins/{id}/forecasts`) — percentages are the API's probabilities times 100.

**HI-03 · Parameter chart and hit rate**
* After one applied outcome: chart "How the twin's parameters changed" shows v0 and v1 with bands (±1.645 SD). Caption: "Narrowing bands mean the model is becoming more certain, not necessarily more accurate." Hit-rate line shows percentages of **reconciled** meals only.
* Pass: only real versions are plotted (as many points as twin versions). With one applied meal the hit-rate is a single-sample number; it must not be presented as validation.

**HI-04 · Refresh behaviour**
* F5 on History: everything reloads from the database. Pass.

### H. Insights

**IN-01 · Sensitivity chart (demo twin)**
* Open Insights with a demo twin. Expected **[Run]**: the **Activity values** field is pre-filled `0, 0.25, 0.5, 0.75, 1`, hint "Demonstration twin range 0 to 1."; chart shows sensitivity (mg/dL per g) against "activity level (units of this twin's prior)" with Model C line + 90 % band and a dashed Model B line; caption states values are as reported by the backend.
* Change the field to `0, 0.5, 1` and click **Update**. Expected: chart redraws with 3 points.

**IN-02 · Invalid activity inputs**

| Input | Expected |
|---|---|
| empty | "Enter between 1 and 25 numeric activity values from 0 to 25, separated by commas." |
| `0, abc` | same |
| `-1` or `26` | same (client-side) |
| 26 values | same |
| `5` (valid for the schema but outside the demo scale 0–1) | red "Sensitivity unavailable" with the backend text "activity_level 5 is outside the range [0, 1] supported by this synthetic demo twin…" **[Run]** |

* Boundary: `0` and `25` pass the client and route checks (for a demo twin `25` is then refused by the demo-scale rule).

**IN-03 · Forecast versus outcome table**
* After an applied outcome: columns Meal (UTC), Observed rise, P given C / B, Inside 90% C / B. Expected **[Run]**: one row; Observed rise is the observed max minus the pre-meal glucose (for 185 and 110: `75.0 mg/dL`).
* Before any applied outcome: "No reconciled meals yet. Few meals per person cannot establish calibration, and none of this has been clinically validated."

**IN-04 · Read-only check**
* Insights loads `GET /sensitivity` and `/reconciliations` only. Before and after visiting Insights, note Twin version and Meals observed on My Twin. Expected: unchanged. **[Code]**

### I. What-if ("Compare scenarios")

**WI-01 · Run a comparison**
* Start: Forecast page, panel **Compare scenarios**. Steps: 1) **Pre-meal glucose** `110` (it pre-fills from the selected forecast only if one existed when the page opened; otherwise type it). 2) Scenario 1: carbohydrate `60`, activity `0.3`. 3) Scenario 2: carbohydrate `90`, activity `0.3`. 4) **Compare**.
* Expected **[Run]**: a table "Scenario | Carbs g | Activity | P(max ≥ 180) C | P B" with Scenario 1 marked "(reference)"; Scenario 2 shows Model C probability with "(+N pts)" relative to the reference; caption "Deltas compare hypothetical inputs on one posterior; they describe the model, not a causal effect on the person." More carbohydrate must not produce a *lower* probability. **[Code]**
* Compare the numbers with the Network response for `what-if` (`comparison.rows`).
* State effect: the **twin is unchanged**, but the backend **stores a record of the run** in its `what_if_runs` table (so it is read-only with respect to the twin, not a "no write at all"). **[Code][Run]**

**WI-02 · Scenario controls and validation**
* **Add scenario** adds up to 10 scenarios. Invalid inputs show the first error under the panel ("Cannot compare"): carbohydrate outside 0–500; activity outside 0–1 on a demo twin; glucose outside 20–600; empty glucose.
* Backend rule reproduced via `/docs`: activity `5` on a demo twin returns 422 with the demo-scale message. **[Run]**

**WI-03 · Warning display**
* If the twin comes from a prior file and an activity lies outside the prior's range, an amber notice appears with the backend's warning. **[Code, Unverified]** (needs a prior file; skip with demo twins).

### J. Settings, persistence and errors

**ST-01 · Backend section**
* Settings → **Backend**: "API base URL: /api"; **Status** pill OK; **Engine** `0.0.1 · <commit>` (plus "(uncommitted changes)" if the backend's working tree is dirty). **[Run]** If the backend is down: pill "unreachable" and the red "Backend not reachable" notice.

**ST-02 · Browser storage inspection**
* DevTools → Application (Chrome/Edge) or Storage (Firefox). **Local Storage** for your site: expected at most the key `glycotwin.active.<your user id>.v2` (a twin id). **Cookies**: `glycotwin_session` (HttpOnly, SameSite Lax). **[Code][Run]** Confirm there is **no password, no session token, no glucose values and no twin list** in Local/Session Storage. (The old keys `glycotwin.twins.v1` and `glycotwin.active.v1` are no longer used; they may linger from older versions and are harmless.)

**ST-03 · Persistence matrix**

| What | After browser refresh | After closing and reopening the browser | After backend restart | If browser data/cookies are cleared | After Log out |
|---|---|---|---|---|---|
| Accounts, twins, forecasts, observations, versions | kept (database) | kept | kept | kept (database) | kept |
| Your sign-in (session) | kept (cookie) | kept until it expires (7 days; guests 24 h) | kept (sessions are in the database) | **lost** (sign in again; a **guest** cannot) | ended |
| Your list of twins | loaded from your account | loaded | loaded | loaded after sign-in | after signing in again |
| Last-open twin | kept (local storage) | kept | kept | resets to your first twin | kept |
| Typed form values | lost | lost | lost | lost | lost |
| Observed value of an unapplied outcome (display) | lost | lost | lost | lost | lost |
| Chart selection (which forecast) | resets to latest | resets | resets | resets | resets |

**[Code]**; verify the rows you care about.

**ER-01 · Backend unavailable during an action**
* Open Forecast with a twin loaded, stop the backend, click **Request forecast** with valid values. Expected: red notice "Cannot reach the GlycoTwin backend. Start it with: python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000". The page does not crash. **[Code]** (the load-time version of this was **[Run]**: SH-03). Restart the backend and retry.

**ER-02 · Error taxonomy (what you should see)**

| Situation | Where to trigger | Message source |
|---|---|---|
| Network / backend down | stop backend | frontend ("Cannot reach the GlycoTwin backend…"; on a reload "Cannot reach the backend" + Try again). The dev proxy answers an empty HTTP 500 when nothing listens on port 8000; the app treats that as "cannot reach", not as "signed out" |
| 401 | session cookie removed or revoked (AU-14); wrong password (AU-08) | backend "not signed in" / "incorrect email or password"; the app returns to Sign In with "Your session has ended…" or shows "Incorrect email or password." |
| 403 | registration or guest access switched off on the server; a browser POST whose Origin differs | backend ("registration is disabled on this server", "guest access is disabled…", "cross-origin request refused") |
| 404 | an id that is not yours or does not exist (OW-02) | backend "twin not found" (identical in both cases) |
| 409 | duplicate email (AU-05), duplicate label (TW-03), back-dated forecast (FC-07) | backend |
| 422 | early observation (OB-03), out-of-scale activity (IN-02, WI-02), unacceptable password (AU-06) | backend |
| 429 | too many wrong sign-ins for one email (AU-09) | backend; the page says "Too many attempts. Please wait…" |
| Client validation | any out-of-range field | frontend text under the field |
| Unexpected reply shape | not user-triggerable | frontend: "Unexpected response from the backend (…)". Covered by an automated test. |
| 5xx | not user-triggerable | "The backend failed to process the request; nothing was changed." **[Code]** |

---

## 4. Exact test data and safe testing scenarios

### 4.1 Use a throw-away database (recommended, and non-destructive)
By default the backend writes to `data/interim/glycotwin_backend.sqlite3`. Testing only **adds** rows, and nothing in the app deletes anything, but you may prefer a separate file. In Window 1, **before** starting the backend:
```powershell
$env:GLYCOTWIN_DATABASE_URL = "sqlite:///C:/Users/<you>/Documents/glycotwin_test.sqlite3"
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000
```
The variable name is `GLYCOTWIN_DATABASE_URL` **[Code]**; the `sqlite:///C:/...` form is the standard SQLAlchemy form and was **not** tested on Windows by this guide **[Unverified]**. The variable only lasts for that PowerShell window. **The account tables are created in the same file**, so a fresh test file also means fresh (empty) accounts: register again after each reset. To "reset", stop the backend and start it with a **different file name**; do **not** delete files in the repository. Twins in your browser's list that belong to another database will show "Twin not found"; use **Forget** to tidy the list.

Never type your own health data. All values below are **made-up demonstration numbers**.

### 4.2 Repeatable scenarios
Prerequisite for S1–S8: **signed in** (register a test account, or use a guest) and a **new** twin, e.g. label `demo-twin-<number>`, synthetic demonstration prior, Empirical Bayes. All values are within the schema (carbohydrate 0–500 g, activity 0–25 (demo twin: 0–1), glucose 20–600 mg/dL).

| ID | Scenario | Data | Expected qualitative behaviour | Illustrative? |
|---|---|---|---|---|
| S1 | **Valid forecast** (FC-01) | 60 g, activity 0.3, glucose 110, meal `2026-01-01 08:00` | Success notice; chart + table; Model B and C probabilities are numbers between 0 % and 100 %. **[Run]** on engine `5ab05a4`: C 8.4 %, B 7.7 %, expected max ≈157 / 155, 90 % intervals ≈130–184 / 126–184. **Do not treat as a target;** compare with the backend response. | Values are invented; the prior is a *simulation*. |
| S2 | **Higher carbohydrate** (compare scenarios) | 60 g vs 90 g at activity 0.3, glucose 110 | The 90 g scenario has a higher expected rise and a higher probability than the 60 g reference . | Illustrative |
| S3 | **Record + apply** | outcome 185 mg/dL, completeness 1, observed through meal + 120 min | Version 0 → 1; Meals observed 0 → 1; SD of β falls. | 185 is invented |
| S4 | **Second forecast after update** | meal `2026-01-01 12:00`, 60 g, 0.3, glucose 105 | Forecast says "from twin version 1"; numbers differ from S1 because the posterior changed. | Illustrative |
| S5 | **Boundaries (accepted)** | carbs 0 and 500; glucose 20 and 600; activity 0 and 1; observed 20 and 600; completeness 0 and 1; `observed through` = meal + exactly 120 min | No client error. The backend result for extreme values is **[Unverified]**: record what you see; do not interpret it clinically. | Extreme values are not realistic |
| S6 | **Boundaries (rejected)** | carbs −1/501; glucose 19/601; activity 1.01; observed 19/601; reason of 2 characters; `observed through` = meal + 119 min | Red message, nothing stored. | – |
| S7 | **Empty states** | brand-new twin; and cleared browser data | See HM-01, OB-01, HI-01. | – |
| S8 | **Duplicate label** | create `demo-twin-1` twice (or the same label from two accounts) | 409 "a twin with this label already exists". | – |
| S9 | **Unknown ID / someone else's ID** | `123e4567-e89b-12d3-a456-426614174000`, or another account's twin id (OW-02) | 404 "twin not found" in both cases. | – |
| S10 | **Incomplete window** | OB-03 | 422 message. | – |
| S11 | **Backend unavailable** | stop Window 1 | Banner + pill (SH-03, ER-01). | – |
| S12 | **Back-dated forecast** | FC-07 | 409; rule: next meal ≥ last applied meal + 120 min. | – |
| S13 | **Excluded meal** | OB-06 | Version unchanged. | – |
| S14 | **Optional synthetic demo twin** | `python scripts\init_db.py --demo` (project root, throw-away database) prints a JSON with `demo_twin_id`; it has **no owner and is hidden** until claimed with `scripts\claim_twin.py` (CL-01) | A twin `demo-synthetic-001` created by 8 simulated forecast-observe-apply cycles (so its version is above 0). It reads **no** CGMacros data. | Fully simulated |
| S15 | **Accounts** | AU-03 to AU-15 | Register, sign in, reload, log out, wrong password, expiry. | fake details only |
| S16 | **Two accounts and a guest** | OW-01 to OW-05, DM-01 | Each sees only its own twins; other ids give 404. | fake details only |

Do not use any participant identifier as a label (the app rejects labels containing "cgmacros"). Do not use a real email address or a password you use elsewhere.

---

## 5. Visual design and responsive testing

### 5.1 Opening DevTools and device emulation
* **Chrome / Edge:** press **F12** (or **Ctrl+Shift+I**). Click the device icon (**Toggle device toolbar**, or **Ctrl+Shift+M**). Choose **Responsive** and type the width × height, e.g. `1440 × 900` or `390 × 844`.
* **Firefox:** **Ctrl+Shift+M** (Responsive Design Mode).
* **Console tab:** red lines are JavaScript errors. A healthy page shows none (extension-related lines can be ignored).
* **Network tab:** tick **Fetch/XHR**; each call shows a *Status* column (200/201 success; 404/409/422 errors). Click a call → **Headers** (URL, method), **Payload** (request), **Response** (JSON).
* Hard refresh: **Ctrl+Shift+R**.

### 5.2 Viewport checklist
Test at **1440 × 900**, **1024 × 768** (tablet-ish), and **390 × 844** (phone). **[Run]** at 1440 and 390: no horizontal page scrolling and no console errors on the landing page, Forecast, Home, My Twin, History and Insights pages with demo data.

| ID | What to inspect | Pass looks like |
|---|---|---|
| VR-01 | **Desktop landing** | **Dark** olive/chocolate background; ivory serif headline (three lines, *story.* in coral); coral **Open the application** button; organic artwork on the right with three readable callouts; the whole first screen (nav, headline, paragraph, both buttons, status strip) visible at 1440 × 900 and 1280 × 800 without scrolling; the "How it works" band is a slightly darker section with the particle wave; every heading and paragraph in that band is readable (an earlier version had dark-on-dark headings; confirm they are fixed); content fills the width. |
| VR-02 | **Mobile landing** | Single column; Menu button works (LP-09); the page does not scroll sideways (drag with the mouse or use two-finger scroll: the page must not move horizontally). |
| VR-03 | **Dashboard desktop** | Light ivory workspace with a dark sidebar on the left, disclaimer bar on top, panels aligned in a grid (the dashboard intentionally keeps the light theme). |
| VR-03b | **Auth pages desktop and mobile** | See AU-02 and AU-10. |
| VR-03c | **Tablet 768 × 1024** | Landing hero stacks into one column (text first, artwork below); nav shows the Menu button; auth pages stack with the panel below the heading; no horizontal scroll. |
| VR-04 | **Dashboard mobile** | Sidebar collapsed to Menu (SH-04); panels stack in one column; forms are full width. |
| VR-05 | **Typography and spacing** | Headings in a serif face, body in a sans face, numbers/labels in a monospace face; consistent gaps; no text clipped. (Fonts are system fallbacks; **no external fonts or trackers are loaded** — check Network for non-localhost requests: expected none except the optional GitHub links you click.) |
| VR-06 | **Chart readability and scrolling** | At 390 px the response chart keeps a minimum width of 700 px and scrolls **inside its own panel** (swipe/drag inside the chart). Labels (model names, threshold, pre-meal) do not overlap each other; text sits on a light halo so hatching does not hide it. At 1440 px the chart fits without scrolling. |
| VR-07 | **Panel/table overflow** | The forecast-history table scrolls inside its own box; no panel pushes the page wider. |
| VR-08 | **Particle effects and reduced motion** | Enable the OS or DevTools setting "prefers-reduced-motion: reduce" (Chrome DevTools → three dots → More tools → Rendering → *Emulate CSS media feature prefers-reduced-motion*). Expected: the landing particle wave is a still frame; chart reveal animations are off. **[Code, Unverified visually]** |
| VR-09 | **Focus visibility** | Tab through the sidebar, forms, buttons and the chart's focusable groups: a 2 px outline is always visible (gold on dark areas). **[Run]** reports an outline on every tab stop of the Forecast page. |
| VR-10 | **Contrast** | Chrome DevTools → Elements → click a text element → the colour picker shows a contrast ratio. The author calculated the main text/background pairs by hand (all at or above 4.5:1 after one fix to the disclaimer label colour); this is **not** a certified audit and you have not verified it yet **[Unverified by you]**. Do not claim WCAG compliance from this alone. |
| VR-11 | **State styling** | Empty, loading, success and error states each show a symbol **and** words (✓ ✕ ▲ ◆ ● ▒ ○), not colour alone. |
| VR-12 | **Zoom** | Zoom the browser to 200 %: content reflows without loss of function. |

### 5.3 What this section cannot prove
Keyboard and contrast spot checks are **not** an accessibility audit. Screen-reader testing (NVDA, VoiceOver), real phones/tablets and an automated tool such as Lighthouse or axe were **not** performed by the author of this guide; if you run them, record results in Section 11.

---

## 6. End-to-end digital twin workflow

Estimated time: 20–25 minutes. Use a fresh test account and the label `e2e-twin-1`. **S** = state-changing, **R** = read-only.

| Step | Do this | Expect | Type |
|---|---|---|---|
| 1 | Open `http://127.0.0.1:5173/`, check the backend line says `online · database ok`; click **Open the application**. | You are sent to `#/login` (signed out). | R |
| 2 | **Create account** (AU-03): `Test Person`, `test.person@example.com`, `windows-test-pass-1`. | Dashboard; your name in the sidebar; Home says "You don't have a twin yet". | **S** (DB: user + session) |
| 3 | Settings → label `e2e-twin-1` → **Create twin**. | "Twin “e2e-twin-1” created at version 0." and it appears in **My twins**. | **S** (DB: twin v0 + owner row) |
| 4 | My Twin: note β/γ means and SDs; Version history has only Version 0. | Numbers finite. Write them down. | R |
| 5 | Forecast: 60 g, activity 0.3, glucose 110, meal `2026-01-01 08:00` → **Request forecast**. | Success; chart; "Limited personal history". | **S** (DB: forecast; twin version stays 0) |
| 6 | Inspect: chart vs "Numbers behind the chart" vs Network `forecast` response (FC-03); read the data-quality notice and the explanation. | All three agree; interval = baseline + rise interval; window 0–120 min. | R |
| 7 | Observations: try **Observed through** `2026-01-01 09:59` with glucose `185`. | Red "outcome window is not complete…". | rejected |
| 8 | Set **Observed through** `2026-01-01 10:00`, glucose `185`, completeness `1` → **Record outcome**. | "Observation recorded. The twin has not been updated yet." My Twin still version 0. | **S** (DB: observation) |
| 9 | **Apply**. | "Twin updated: version 0 → 1." with a parameter-change line. | **S** (DB: version 1) |
| 10 | Forecast again with meal `2026-01-01 09:00` (expect refusal, FC-07), then `2026-01-01 12:00`, glucose 105. | Refusal, then "Forecast stored from twin version 1." Numbers differ from step 5. | rejected / **S** |
| 11 | **Press F5**, then **Log out**, then **Sign in** again (AU-11, AU-12, AU-07). | Still signed in after F5; logout returns to `#/login`; after signing in **My twins** lists `e2e-twin-1`. | **S** (sessions) |
| 12 | My Twin → n = 1 meals observed, versions 0 and 1; History → forecasts table (reconciled + awaiting), parameter chart with v0 and v1, hit rate; Insights → Forecast versus outcome row (observed rise 75.0 mg/dL). | **Everything saved before logout is back**; consistent with steps 5–9. | R |
| 13 | Forecast page → **Compare scenarios** (WI-01); Insights → **Update** with `0, 0.5, 1` (IN-01). | Tables/charts appear. | R for the twin (what-if stores a run record) |
| 14 | Before step 13 note Twin version and Meals observed; after step 13 compare. | Unchanged. For an API-level confirmation, `GET /twins/{id}/history` before and after returns identical `versions` (Section 7). | R |
| 15 | Open a private window, register a second account, check Settings → My twins (OW-01) and probe the first account's twin id (OW-02). | Empty list; 404 "twin not found". | R |

**State-changing operations (UI):** Create account, Sign in, Log out, Continue as demo, Create twin, Request forecast, Record outcome, Apply. **Read-only with respect to the twin:** opening any page, switching twins (browser only), explanations, sensitivity, reconciliation view, what-if (stores a what-if run record only).

---

## 7. API integration testing

### 7.1 Where to look
* **Interactive docs:** `http://127.0.0.1:8000/docs` → click an endpoint → **Try it out** → **Execute**. Paths here have **no** `/api` prefix. Every twin endpoint needs a session: first run `POST /auth/login` in `/docs` (the browser then keeps the `glycotwin_session` cookie for `127.0.0.1:8000`; it is separate from the cookie of the website on port 5173). Without it you get 401 "not signed in".
* **Browser Network tab:** requests go to `/api/...` on the frontend port; the proxy strips `/api`.
* Machine-readable schema: `http://127.0.0.1:8000/openapi.json`.
* Twin ids are 36-character UUIDs (pattern `^[0-9a-f-]{36}$`); shorter ids give a 422 validation error. **[Run]**

### 7.2 Endpoints (verified against `routers/twins.py`, `schemas.py` and the OpenAPI document) **[Code]**

| Method & backend path | UI path (frontend) | Purpose | Changes twin state? | Success status |
|---|---|---|---|---|
| `GET /health` | `/api/health` (landing, shell, Settings) | Liveness, tables, engine version | No | 200 (not wrapped in `data`) **[Run]** |
| `POST /auth/register` | Create Account page | Create an account and sign in (sets the cookie) | Creates a user and a session | 201 |
| `POST /auth/login` | Sign In page | Sign in (sets the cookie) | Creates a session | 200 |
| `POST /auth/guest` | "Continue as demo" | Temporary guest account (24 h) | Creates a guest user and session | 201 |
| `POST /auth/logout` | Log out | Revoke this session, clear the cookie | Deletes the session | 200 |
| `GET /auth/me` | on every page load | Who am I (401 when signed out) | No | 200 |
| `GET /twins` | Settings → Your twins; Home | List **your own** twins only | No | 200 |
| `POST /twins` | Settings → Create twin | Create twin (you become its owner) | **Creates** a twin (version 0) and an ownership row | 201 |
| `GET /twins/{twin_id}` (query `reference_activity` 0–25, optional) | loaded on every twin switch | Twin + state view | No | 200 |
| `GET /twins/{twin_id}/history` (same query) | loaded with twin | Versions, parameter history, convergence, hit-rate trend, exclusions | No | 200 |
| `POST /twins/{twin_id}/forecast` | Forecast → Request forecast | Forecast one meal | Stores a forecast; twin **version unchanged** | 201 new; 200 with `created:false` for an identical repeat |
| `GET /twins/{twin_id}/forecasts` (query `limit` 1–500 (UI uses 100), `offset`) | loaded with twin | List forecasts with status | No | 200 |
| `POST /twins/{twin_id}/observe` | Observations → Record outcome | Record outcome (peak or exclusion) | Stores observation; twin **unchanged** | 201 new; 200 identical repeat |
| `POST /twins/{twin_id}/reconcile` | Observations → Apply | Apply the observation | **New twin version** (not for excluded) | 201 new; 200 repeat |
| `POST /twins/{twin_id}/what-if` | Forecast → Compare scenarios | Scenario comparison | Twin unchanged; stores a what-if run | 200 |
| `GET /twins/{twin_id}/forecasts/{forecast_id}/explanation?model=model_b\|model_c` | Forecast → Why this forecast? | Explanation as of the forecast's twin version | No | 200 |
| `GET /twins/{twin_id}/sensitivity?activities=0,0.5,1` | Insights | Sensitivity vs activity | No | 200 |
| `GET /twins/{twin_id}/reconciliations` | loaded with twin; Insights | Forecast vs observed list + hit-rate trend + calibration | No | 200 |

`GET /twins` lists only the signed-in account's own twins; there is no endpoint that lists other accounts' twins or any participant. **Every** `/twins/{twin_id}…` endpoint answers 401 "not signed in" without a session and an identical 404 "twin not found" when the twin is not yours (or has no owner yet). `/health` and the `/auth/*` routes other than `/auth/me` and `/auth/logout` need no session. **[Code][Run]**

### 7.3 Request fields and limits
(Request bodies reject unknown fields with 422 `extra_forbidden`. **[Run]**)

| Endpoint | Fields (type; limits) |
|---|---|
| `POST /auth/register` | `name` (1–80 chars), `email` (valid address), `password` (10–128 chars; not equal to the email or name; not a single repeated character). Requires a same-origin `Origin`/`Host` (the proxy provides it). |
| `POST /auth/login` | `email`, `password`. |
| `POST /auth/guest`, `/auth/logout` | no body. |
| `POST /twins` | `label` (string; pattern `^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`, must not contain "cgmacros"; **required**); `prior` {`source` `synthetic_demo`\|`prior_file`; `name` (prior_file only, required then); `prior_scheme` `empirical_bayes`\|`blueprint`; `gamma_relative_sd` (blueprint only; one of the allowed widths)}; `glycaemic_group` `healthy`\|`pre-diabetes`\|`t2d` (optional); `reference_activity` (0–25, optional). The UI sends `label` and `prior`. |
| `POST …/forecast` | `event_id` (same pattern as label, **required**; the UI generates one); `meal_time` (datetime, **required**; the UI sends UTC); `carbs_g` (0–500); `activity_level` (0–25; demo twin 0–1); `baseline_glucose` (20–600 mg/dL); optional `activity_coverage` (0–1), `baseline_age_minutes` (0–1440), `trend_slope_30min` (−20…20), `time_since_last_meal_min` (≥ 0). |
| `POST …/observe` | `forecast_id` (8–36 chars); `observed_through` (datetime; ≥ meal time + 120 min); **either** `peak_glucose_mg_dl` (20–600) **or** `excluded_reason` (3–200 chars), never both and not neither; optional `window_completeness` (0–1). |
| `POST …/reconcile` | `forecast_id` |
| `POST …/what-if` | `baseline_glucose` (20–600); `scenarios` (1–10 items of {`label` ≤ 80 chars optional, `carbs_g` 0–500, `activity_level` 0–25}) |

### 7.4 Key response fields (as used by the UI) **[Code][Run]**
* **Forecast:** `forecast_id`, `event_id`, `meal_time`, `twin_version_at_forecast`, `model_version`, `inputs` (`carbs_g`, `activity_level`, `baseline_glucose`, …), for each of `model_b` and `model_c`: `p_peak_at_least_180`, `mean_rise_mg_dl`, `sd_mg_dl`, `interval90_rise_mg_dl` (**rise above baseline**), plus `horizon_minutes` (120), `data_quality`, `engine_provenance`, `status` (`pending` | `observed` | `reconciled` | `excluded`), `created`.
* **Observation:** `observation_id`, `forecast_id`, `observed_through`, `peak_glucose_mg_dl`, `peak_glucose_rise_mg_dl`, `label_peak_at_least_180`, `window_completeness`, `excluded_reason`, `kind` ("OBSERVED outcome (not yet applied to the twin)").
* **Reconciliation:** `reconciliation_id`, `outcome` (`updated`|`excluded`), `twin_version_before`, `twin_version_after`, `metrics`, and (for updates) `parameter_change` for `model_b` and `model_c` (β mean/sd before/after, `beta_sd_ratio`, and for C the γ equivalents).
* **What-if:** `screen_label`, `comparison` {`reference`, `twin_version_used`, `rows[]` with `p_peak_at_least_180`, `mean_rise_mg_dl`, `interval90_rise_mg_dl` and, for non-reference rows, `delta_p_vs_reference` and `delta_rise_mg_dl_vs_reference`, `note`}, `prior_support_warnings`.
* **Sensitivity:** `model_b`, `model_c_curve[]` (`activity_level`, `mean`, `sd`, `interval90`), `gamma_activity_interaction`, `n_meals_observed`, `activity_scale`, `prior_support_warnings`.

### 7.5 Confirmed error responses **[Run]**

| Request | Status | `detail` |
|---|---|---|
| Any twin endpoint without a session | 401 | "not signed in" |
| Twin id that belongs to another account, has no owner, or does not exist | 404 | "twin not found" (identical for all three) |
| Wrong password or unknown email | 401 | "incorrect email or password" (same text for both) |
| Register with an email already in use | 409 | "an account with this email already exists" |
| Register with a weak password | 422 | message naming the password rule |
| Registration or guest mode switched off (`GLYCOTWIN_ALLOW_REGISTRATION=0` / `GLYCOTWIN_ALLOW_GUEST=0`) | 403 | message saying it is disabled |
| Auth POST with a foreign `Origin` | 403 | cross-origin request refused |
| 5 wrong sign-ins for one email within 15 minutes (or too many guest sessions from one address) | 429 | "too many attempts" with a `Retry-After` header |
| Unknown (well-formed) twin id | 404 | "twin not found" |
| Malformed twin id (`abc`) | 422 | list; "String should have at least 36 characters" |
| Duplicate label | 409 | "a twin with this label already exists" |
| Demo twin, activity 5 (forecast, what-if or sensitivity) | 422 | "activity_level 5 is outside the range [0, 1] supported by this synthetic demo twin… (not METs)…" |
| Sensitivity activity 26 | 422 | "each activity value must lie between 0 and 25" |
| Reconcile before observing | 409 | "no observation has been submitted for this forecast yet" |
| Observe before window closes | 422 | "the outcome window is not complete: observed_through must be at or after meal_time + 120 minutes" |
| Back-dated forecast | 409 | "the twin already learned from an outcome window that closes after this meal time; a back-dated forecast is refused" |
| Explanation with `model=zz` | 422 | pattern mismatch `^model_[bc]$` |
| Extra field in body | 422 | `extra_forbidden` |
| Same `event_id` with different inputs | 409 | "this event_id was already forecast with different inputs" **[Code]** |
| Second, different observation for a forecast | 409 | "an observation was already recorded for this forecast; it cannot be replaced" **[Code]** |
| Unknown forecast id | 404 | "forecast not found for this twin" **[Code]** |

Every reply body includes the `disclaimer` text. Error bodies from the application have `detail` (string) and `disclaimer`; framework validation errors (422 from FastAPI) have a list in `detail` and may not carry the disclaimer. **[Code]**

### 7.6 How to test an endpoint through the UI **and** `/docs`
0. Sign in first (website for step 1; `POST /auth/login` in `/docs` for step 3). Use a test account on a temporary database (1.6b).
1. Do the action in the UI with the Network tab open (filter `Fetch/XHR`).
2. Click the request → note the **Status**, copy the **Response** JSON.
3. Open `/docs` and run the same call with the same values (remember: no `/api`). Compare.
4. For read-only claims: call `GET /twins/{id}/history` **before** and **after** you run explanation, sensitivity, reconciliations, and compare; `versions` must be identical. (An automated backend test checks this for those three endpoints.)

Do not paste real twin data, tokens or secrets into any shared place; the twin ids and values created here are demonstration data only.

---

## 8. Research integrity and scientific limitations

Run these checks with the data from Section 6. Each is a *yes/no* question.

| ID | Check | How | Pass |
|---|---|---|---|
| RI-01 | No invented glucose time series | Look at every chart (Home, Forecast, Insights, History). Is there any smooth curve of glucose against time? | None. Only: flat interval bands across the 0–120 min window, an expected-maximum line, a probability density sideways (right panel), the observed maximum marker, and parameter/sensitivity charts. The caption says "no time course is drawn". |
| RI-02 | Window and units | Axis titles and captions. | mg/dL; minutes after the meal; window "(t0, t0 + 120 min]"; threshold 180 mg/dL. |
| RI-03 | Intervals not misrepresented | Compare chart band edges with `pre-meal glucose + interval90_rise_mg_dl`. Read the legend. | Legend says "90% predictive interval of the window maximum". Band is for the **maximum**, not for glucose at every minute. |
| RI-04 | Probability threshold stated accurately | Read "P(max ≥ 180)" labels and the landing "Forecast" step. | It is the probability that the **maximum** glucose within 120 minutes is **≥ 180 mg/dL**, a statement about a *window maximum*, not about a diagnosis. |
| RI-05 | Uncertainty shown only from the backend | Compare SDs/intervals to the API. Is any band drawn when no forecast exists? | None without a forecast. Numbers match the API. |
| RI-06 | Data-quality notes honest | FC-09. | Says probability/interval are **not** adjusted for data quality (unless the backend reports otherwise). |
| RI-07 | B vs C stays inconclusive | Landing Research section; any other page. Search the whole site for "outperform", "better", "superior", "improves". | "inconclusive"; "No claim of superiority is made". Per-meal charts never imply C is better. The History hit-rate caption says a trend is dominated by chance with few meals. |
| RI-08 | Demonstration values identified | Create a demo twin; look at the header and the Forecast form. | Pills "SYNTHETIC DEMONSTRATION PRIOR"; activity label "(SIMULATED SCALE)" with "not METs". |
| RI-09 | Disclaimer visible and verbatim | SH-02, LP-08, ST page. | Exact wording; present on every dashboard page. |
| RI-10 | No diagnosis, treatment, diet or insulin-dosing | Read all text, including the explanation sentences and what-if. | None. What-if text says it describes the model and is "not a causal effect on the person"; the backend label says it is "not a diet prescription, treatment recommendation, or insulin dosing suggestion". (Explanation text is generated by the backend; read it for anything that sounds like advice and report it.) |
| RI-11 | Participant data privacy | Network tab and Local Storage. | No participant-level data; only twin ids/labels in local storage; no requests to third-party domains. |
| RI-12 | "Hit rate" and "Inside 90%" wording | History and Insights. | Presented as descriptive counts of a few meals, with the sentence that a few meals cannot establish calibration. |
| RI-13 | Authentication honesty | AU-03…AU-16, DM-01, DM-02, OW-01…OW-05. | Success is shown only after the backend confirms it; failures show the backend's message; "demo" mode is described as a temporary guest account; nothing on the site claims password recovery, email verification, account deletion, or a security audit exists, and nothing calls accounts "secure" beyond what is implemented (hashed passwords, HttpOnly cookie, ownership checks). |

**What passing these checks does not mean:** it means the interface describes the model honestly. It does not mean the forecasts are accurate, that the demo prior reflects real people, that the B/C comparison is settled, or that the tool is safe to use for any health decision. The synthetic demonstration prior is simulated, the real-data validation is not part of this website, and no clinical validation has been done.

---

## 9. Troubleshooting

> First-line rule: **read the message, check the other window, then retry.** Do not delete files or run destructive Git commands to fix a startup problem.

| Visible symptom | Likely causes | Safe checks | Recommended next action |
|---|---|---|---|
| `'vite' is not recognized…` / `npm run dev` fails | Dependencies not installed; wrong directory | `cd frontend`; `dir node_modules` (should exist); `node --version` | In `frontend`: `npm install`, then `npm run dev`. |
| `Cannot find module …` / missing packages in the frontend | Partial install | `npm ls` | `npm install` again (the lock file `package-lock.json` is committed; do not delete it). |
| Node version error | Node too old | `node --version` | Install a current LTS Node and retry. |
| `ModuleNotFoundError: No module named 'glycotwin'` | Package not installed; wrong directory; wrong Python environment | `python -c "import glycotwin"`; `pip list` | From the project root: `pip install -e ".[dev]"` (or `pip install -r requirements.txt` and run uvicorn from the project root). |
| Other backend import errors (e.g. `fastapi`, `sqlalchemy`, `xgboost` missing) | Dependencies missing | `pip show fastapi` | `pip install -r requirements.txt`. |
| `Address already in use` / `[WinError 10048]` on port 8000 | Another backend (or program) is on 8000 | `netstat -ano \| findstr :8000` | Close the old terminal (Ctrl+C), or start on another port, e.g. `--port 8001`, and start the frontend with `VITE_API_PROXY_TARGET=http://127.0.0.1:8001` (PowerShell: `$env:VITE_API_PROXY_TARGET="http://127.0.0.1:8001"; npm run dev`). |
| Vite starts on a different port (e.g. 5174) | 5173 busy | Read the "Local:" line | Use the printed URL. |
| Red banner "Backend not reachable"; landing says "backend offline" | Backend not running; wrong port; proxy target mismatch | Open `http://127.0.0.1:8000/health`; then `http://127.0.0.1:5173/api/health` | Start the backend; make sure the proxy target equals the backend port; refresh. |
| `/api/health` returns HTML or 404 on port 5173 | You opened a different app on that port, or the dev server was started from the wrong folder | Look at the Vite terminal | Stop it; `cd frontend`; `npm run dev`. |
| Browser shows CORS error | You bypassed the proxy (calling `http://127.0.0.1:8000` directly from the page) | Console message; check `VITE_API_BASE_URL` | Keep the default `/api` (the backend has no CORS settings). |
| **404** "twin not found" | Wrong/unknown id; twin belongs to another account or has no owner (old twins from before accounts are hidden until claimed); backend started with a different `GLYCOTWIN_DATABASE_URL` | `GET /twins` while signed in; check which database you started | Pick a twin from your list (Settings → **Use**), create a new one, or claim an old one with `scripts\claim_twin.py` (CL-01). |
| **401** "not signed in" / sent back to the sign-in page | Session expired (7 days; guest 24 h), logged out in another tab, cookies blocked, or the backend database was replaced | DevTools → Application → Cookies for `127.0.0.1:5173`; `GET /api/auth/me` in the Network tab | Sign in again. Allow cookies for `127.0.0.1`. Use `127.0.0.1` consistently (cookies for `localhost` are separate). |
| Sign-in loops back to the sign-in page | Cookies blocked, or the page was opened on a different host name than the one you signed in on | Cookies panel as above | Open `http://127.0.0.1:5173/` and sign in again. |
| "Too many attempts" (429) on sign-in | 5 wrong passwords for one email in 15 minutes (counter is in backend memory) | Message shows when to retry | Wait, or restart the **test** backend (this resets the counters). Never do that on a backend you rely on. |
| "Cannot reach the backend" on the sign-in page | Backend not running (the proxy then returns an empty 500) | `http://127.0.0.1:8000/health` | Start the backend; reload. |
| `Registration is disabled` (403) | `GLYCOTWIN_ALLOW_REGISTRATION=0` in the backend environment | Backend start-up environment | Unset it or set to `1`, restart the backend. |
| **409** conflict | Duplicate label; back-dated forecast; second observation; reconcile before observe | Read the message | Change the label; set a later meal time (≥ last applied meal + 120 min); see FC-07/OB-07/OB-08. |
| **422** invalid input | Value out of range; demo twin activity outside 0–1; window not complete | Read the message; compare with Section 7.3 | Correct the value. |
| "Forecast not available" / chart says "No forecast to draw yet" | No forecast yet; forecast request failed; wrong twin selected | History page; Network tab | Request a forecast; check for a red notice. |
| "No forecast is waiting for an outcome" | No pending forecast (all observed/reconciled) | History statuses | Request a new forecast. |
| "Outcome window incomplete" | `Observed through` < meal + 120 min | Read the hint under the field | Use the pre-filled value or later. |
| History is empty after refresh | No twin active; signed in as a different account; wrong database | Settings → Your twins | Pick the twin from the list; confirm which account and database file you are using. |
| Twin missing after refresh | Signed in as another account; guest session expired (guest twins are not recoverable by sign-in); wrong database | Settings → Your twins; `GET /api/auth/me` | Sign in with the account that created it. |
| Chart labels overlap | Very small width; browser zoom; custom fonts | Try 100 % zoom and a wider window; chart scrolls inside its panel on phones | Record a screenshot and viewport size as a visual bug; keep testing. |
| Page is blank | JavaScript error | Console (F12) | Copy the first red error; hard refresh (Ctrl+Shift+R); restart `npm run dev`. |
| Console errors "Failed to load resource … 409/404/422" | These are *expected* when you deliberately test error cases | Network tab → the request status | Not a bug unless the page misbehaves. |
| Console error `ERR_CONNECTION_REFUSED` on `/api/...` | Backend stopped | Window 1 | Restart backend. |
| `Set-ExecutionPolicy`/`Activate.ps1` blocked | PowerShell policy | Message text | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (only that window). |

---

## 10. Automated verification

These are **separate from manual tests**. Run them in a terminal. Results below are **not** results from your machine.

| Check | Command (directory) | What it establishes | What it does **not** establish |
|---|---|---|---|
| Frontend typecheck | `npm run typecheck` (`frontend`) | The TypeScript code is type-consistent (strict mode). | Runtime behaviour, layout, API correctness. |
| Frontend tests | `npm test` (`frontend`) | **37 tests across 4 files** (`core`, `landing`, `auth`, `accounts`): disclaimer verbatim; API client envelope/error mapping (401, 404, 409, 422, 429, network, malformed reply); route parsing and route protection; number validation; per-user active-twin storage; chart empty state; landing content; form validation; against an in-memory fake backend (`fakeBackend.ts`): register/login/guest/logout flows, wrong-password and rate-limit messages, expired-session handling, backend-unreachable state, no password or token in storage, per-account isolation of the remembered twin. (A "Not implemented: canvas getContext" message is stubbed in the test setup.) | Real backend behaviour, real browser cookies, visual quality, accessibility compliance. |
| Frontend production build | `npm run build` (`frontend`) | Type check + optimised bundle builds. | That the site works against a backend. |
| Preview of the build | `npm run preview` (`frontend`) then open `http://127.0.0.1:4173/` | The built bundle runs (with the same `/api` proxy). | Same as above. |
| Full Python tests | `python -m pytest -p no:cacheprovider -q` (project root) | Research engine, data layer, backend routes, lifecycle rules, idempotency, docs conformance, etc. on **synthetic** data. Backend tests use temporary databases (`tmp_path`), so they do not touch your real twin store. A full run takes several minutes. | Real-data validity; clinical validity; the browser UI. |
| Backend tests only | `python -m pytest -p no:cacheprovider -q tests/test_backend.py tests/test_auth.py tests/test_ownership.py` | API behaviour (twins, forecast, observe, reconcile, what-if, explanation, sensitivity, reconciliations, never-modify checks) plus accounts: hashing, sessions, cookie flags, throttling, origin check, ownership on every twin route, `GET /twins`, upgrade of an existing database, the claim script. | Same; no external security review. |
| Whitespace check | `git diff --check` (project root) | No whitespace errors in pending changes. | Anything functional. |

* **Python tests, exact command** (project root, environment active): `python -m pytest -p no:cacheprovider -q`. A full run takes roughly 9 minutes on the author's Linux machine. Re-run it after any backend change.
* **Reference results (author's runs on Linux, cloud container, temporary databases; not yours):** after the accounts/ownership work: Python suite **815 passed**; frontend typecheck clean, **37 tests passed**, production build succeeded; an automated Chromium walk-through of both account flows passed 30/30 checks. **Not tested by the author:** Windows, Edge/Firefox/Safari, real phones, screen readers, any external security review. These numbers will change as the project changes.
* **Lint:** no Python or frontend lint command is configured in `pyproject.toml` or `frontend/package.json`. **[Code]** Do not invent one.
* Do **not** point automated tests at your real database; the backend suite already uses temporary ones. Do not run the `scripts/` research runners (e.g. `run_experiment.py`, `check_leakage_on_data.py`) as part of website testing: they read the participant data folders, which this guide never asks you to touch.

---

## 11. Final test report and checklist

### 11.1 Environment record (fill in)
| Item | Value |
|---|---|
| Date / tester | |
| OS and browser + version | |
| Git commit (`git rev-parse --short HEAD`) | |
| Database used (default or temporary file) | |
| Backend and frontend URLs | |

### 11.2 Test checklist
Status values: **Not tested / Pass / Fail / Blocked**. Severity: S1 blocker, S2 major, S3 minor, S4 cosmetic. Reproducibility: Always / Sometimes / Once.

| Area | Feature | Test ID | Status | Notes / evidence (screenshot, response) | Severity | Reproducible |
|---|---|---|---|---|---|---|
| Landing | Hero & CTAs | LP-01 | Not tested | | | |
| Landing | Live backend metadata | LP-02 | Not tested | | | |
| Landing | Anchors | LP-03 | Not tested | | | |
| Landing | Product section | LP-04 | Not tested | | | |
| Landing | How it works / particles | LP-05 | Not tested | | | |
| Landing | Research claims | LP-06 | Not tested | | | |
| Landing | Docs links | LP-07 | Not tested | | | |
| Landing | Footer disclaimer | LP-08 | Not tested | | | |
| Landing | Mobile menu | LP-09 | Not tested | | | |
| Landing | Keyboard | LP-10 | Not tested | | | |
| Landing | First screen fits (1440 × 900, 1280 × 800) | LP-01b | Not tested | | | |
| Auth | Open pages / routes `#/login`, `#/register` | AU-01 | Not tested | | | |
| Auth | Visual consistency | AU-02 | Not tested | | | |
| Auth | Create account (success) | AU-03 | Not tested | | | |
| Auth | Create Account validation | AU-04 | Not tested | | | |
| Auth | Duplicate email | AU-05 | Not tested | | | |
| Auth | Backend password rule | AU-06 | Not tested | | | |
| Auth | Sign in (success) | AU-07 | Not tested | | | |
| Auth | Wrong password / unknown email | AU-08 | Not tested | | | |
| Auth | Rate limit | AU-09 | Not tested | | | |
| Auth | Password toggle | AU-10 | Not tested | | | |
| Auth | Session survives reload | AU-11 | Not tested | | | |
| Auth | Log out | AU-12 | Not tested | | | |
| Auth | Signed-out visitors blocked | AU-13 | Not tested | | | |
| Auth | Expired / revoked session | AU-14 | Not tested | | | |
| Auth | Cookie and storage inspection | AU-15 | Not tested | | | |
| Auth | Things that must not be there | AU-16 | Not tested | | | |
| Auth | Keyboard / focus | AU-17 | Not tested | | | |
| Auth | Responsive auth pages | AU-18 | Not tested | | | |
| Demo mode | Continue as demo (guest account) | DM-01 | Not tested | | | |
| Demo mode | Guest limits understood | DM-02 | Not tested | | | |
| Demo mode | Workflow unchanged | DM-03 | Not tested | | | |
| Ownership | Two accounts cannot see each other's twins | OW-01 | Not tested | | | |
| Ownership | Probing another account's twin (API) | OW-02 | Not tested | | | |
| Ownership | Not signed in | OW-03 | Not tested | | | |
| Ownership | Twin list is owner-scoped | OW-04 | Not tested | | | |
| Ownership | Labels globally unique (known limitation) | OW-05 | Not tested | | | |
| Claiming | Claim an old twin with `claim_twin.py` | CL-01 | Not tested | | | |
| Shell | Sidebar navigation | SH-01 | Not tested | | | |
| Shell | Persistent disclaimer | SH-02 | Not tested | | | |
| Shell | Backend pill/banner | SH-03 | Not tested | | | |
| Shell | Mobile menu | SH-04 | Not tested | | | |
| Shell | Skip link/keyboard order | SH-05 | Not tested | | | |
| Shell | Announcer region | SH-06 | Not tested | | | |
| Home | Empty state | HM-01 | Not tested | | | |
| Home | Summary cards | HM-02 | Not tested | | | |
| Home | After forecast/apply | HM-03 | Not tested | | | |
| Home | "Awaiting outcome" caveat | HM-04 | Not tested | | | |
| My Twin | Create twin | TW-01 | Not tested | | | |
| My Twin | Label validation | TW-02 | Not tested | | | |
| My Twin | Duplicate label | TW-03 | Not tested | | | |
| My Twin | Prior options | TW-04 | Not tested | | | |
| My Twin | Page content | TW-05 | Not tested | | | |
| My Twin | Twins list and switching | TW-06 | Not tested | | | |
| My Twin | List that cannot load | TW-07 | Not tested | | | |
| My Twin | No open-by-id (by design) | TW-08 | Not tested | | | |
| My Twin | Refresh persistence | TW-09 | Not tested | | | |
| My Twin | Persistence after log out / in | TW-10 | Not tested | | | |
| Forecast | Valid forecast | FC-01 | Not tested | | | |
| Forecast | Chart reading | FC-02 | Not tested | | | |
| Forecast | Chart = table = API | FC-03 | Not tested | | | |
| Forecast | Model buttons | FC-04 | Not tested | | | |
| Forecast | Client validation | FC-05 | Not tested | | | |
| Forecast | Rejections | FC-06 | Not tested | | | |
| Forecast | Back-dated (409) | FC-07 | Not tested | | | |
| Forecast | Repeated forecasts | FC-08 | Not tested | | | |
| Forecast | Data-quality notice | FC-09 | Not tested | | | |
| Forecast | Explanation | FC-10 | Not tested | | | |
| Forecast | Select older forecast | FC-11 | Not tested | | | |
| Observations | Empty state | OB-01 | Not tested | | | |
| Observations | Record outcome | OB-02 | Not tested | | | |
| Observations | Incomplete window | OB-03 | Not tested | | | |
| Observations | Validation | OB-04 | Not tested | | | |
| Observations | Apply | OB-05 | Not tested | | | |
| Observations | Exclude | OB-06 | Not tested | | | |
| Observations | Second outcome | OB-07 | Not tested | | | |
| Observations | Apply without observation (API) | OB-08 | Not tested | | | |
| Observations | Refresh before apply | OB-09 | Not tested | | | |
| History | Empty | HI-01 | Not tested | | | |
| History | Forecast table | HI-02 | Not tested | | | |
| History | Parameter chart / hit rate | HI-03 | Not tested | | | |
| History | Refresh | HI-04 | Not tested | | | |
| Insights | Sensitivity | IN-01 | Not tested | | | |
| Insights | Invalid activity | IN-02 | Not tested | | | |
| Insights | Forecast vs outcome | IN-03 | Not tested | | | |
| Insights | Read-only check | IN-04 | Not tested | | | |
| What-if | Run comparison | WI-01 | Not tested | | | |
| What-if | Controls & validation | WI-02 | Not tested | | | |
| What-if | Warnings | WI-03 | Not tested | | | |
| Settings | Backend section | ST-01 | Not tested | | | |
| Settings | Browser storage inspection | ST-02 | Not tested | | | |
| Settings | Persistence matrix | ST-03 | Not tested | | | |
| Errors | Backend unavailable | ER-01 | Not tested | | | |
| Errors | Error taxonomy | ER-02 | Not tested | | | |
| Responsive | Desktop / tablet / mobile layouts | VR-01…VR-04, VR-03b, VR-03c | Not tested | | | |
| Responsive | Typography, chart, overflow | VR-05…VR-07 | Not tested | | | |
| Accessibility | Motion, focus, contrast, states, zoom | VR-08…VR-12 | Not tested | | | |
| Workflow | End-to-end walkthrough | Section 6 | Not tested | | | |
| API | Endpoint checks | Section 7.6 | Not tested | | | |
| Research | Integrity checks | RI-01…RI-13 | Not tested | | | |
| Automated | typecheck / tests / build / pytest | Section 10 | Not tested | | | |

### 11.3 Known limitations (as of this guide)
**Accounts and sessions are implemented** (registration, sign in, sign out, guest mode, HttpOnly session cookie, scrypt password hashing, per-account twin ownership, `GET /twins`). They are a research-prototype implementation and have **not** had an external security review. Known gaps, all deliberate and not hidden by the UI:
* **No password recovery** ("forgot password") and **no email verification**: an email address is not proven to belong to the person.
* **No account deletion** and no way to change the password or email.
* **Guest accounts are never cleaned up**: expired guest sessions stop working, but the guest user and its twins stay in the database.
* **Login and guest rate limits are in memory**: they reset when the backend restarts and are per backend process.
* **Twin labels are globally unique**, not per account, so a label can reveal (by a 409 on create) that another account used it.
* **Not HTTPS by default**: the `Secure` cookie flag is off unless `GLYCOTWIN_COOKIE_SECURE=1`; the backend is meant to stay bound to `127.0.0.1`. Do not expose it to a network as-is.
* **Databases from before accounts** keep their twins, but those twins have no owner and are hidden until claimed with `scripts\claim_twin.py`. The schema has no migration tool; `create_all` only adds the three new tables.
* The guest **"Create a real account"** link in Settings opens `#/register`, which redirects a signed-in user to the workspace; log out first.

Other limitations:
* No twin editing or deleting; the remembered active twin is stored per account in the browser.
* Observed values of unapplied outcomes are not shown after refresh (OB-09).
* "Awaiting outcome" on Home can understate pending forecasts (HM-04).
* Double-clicking **Request forecast** creates two forecasts (FC-08).
* The backend forecasts only the **maximum** over a 120-minute window; no glucose time course exists.
* Demonstration twins use a **simulated** 0–1 activity scale, not METs.
* Not covered by this guide or the author's runs: Windows, screen readers, real devices, automated accessibility tools, human design review, any real participant data.
* Several behaviours are marked **[Unverified]**; fill in what you see.

### 11.4 Readiness summary (complete after testing)
For each row choose **Ready for demo / Ready with known issues / Not ready**, with one-sentence justification. The conclusions below are **templates**; this guide cannot decide them for you.

| Area | Criterion for "Ready for demo" | Your conclusion | Justification |
|---|---|---|---|
| 1. Basic application functionality | LP, AU, DM, OW, SH, HM, TW, FC, OB, HI, IN, WI, ST cases pass; no S1/S2 bugs open | | |
| 2. Frontend/backend integration | FC-03 passes; Section 6 passes; Section 7 comparisons agree; error cases show the backend's messages | | |
| 3. Research integrity | All RI-01…RI-13 pass | | |
| 4. Accessibility and responsive testing | VR and AU-17/AU-18 cases pass at 1440, 1280, 768 and 390 px; focus visible; no horizontal page scroll. **Compliance with accessibility standards is not established** by manual spot checks | | |
| 5. Clinical validation | **Not validated. Always "Not clinically validated."** Passing this guide cannot change this. | **Not clinically validated** | The tool is a research prototype with a synthetic demonstration prior and an inconclusive B-vs-C comparison. |
| 6. Authentication / user accounts | AU-01…AU-18, DM-01…DM-03, OW-01…OW-05 pass; cookie is HttpOnly; no password/token in browser storage; another account's twin is a 404. **No external security review exists**, so this is never "secure", only "behaves as documented" | | Known gaps: see 11.3 (no recovery, no verification, no deletion, in-memory throttle, guest cleanup, global labels). |

---

## 12. Known discrepancies found while writing this guide

These were found by reading the repository and running the app. They are **not** fixed by this guide (documentation-only task). Some may deserve a later fix.

1. **Home "Awaiting outcome" card** counts only forecasts whose window closed relative to the latest event (HM-04).
2. **Double submit creates duplicate forecasts** (FC-08).
3. **Unapplied observed value lost on refresh** (OB-09).
4. **Landing "Documentation" links** point to the GitHub branch tree and need that branch to be reachable (LP-07).
5. **Root `README.md`** was corrected in this revision to describe the backend, dashboard and accounts. Its statements and `docs/PROJECT_STATUS.md` that no experiment result exists still sit beside `docs/model_card.md` and the landing page, which cite 963 meals from 34 participants with an inconclusive B-vs-C result; the project owner should reconcile them.
6. **`requirements.txt`** has a comment saying the React frontend is a "later phase"; the frontend now exists in `frontend/` with its own `package.json`. (Not a documentation file; left unchanged.)
7. **Windows database URL form** `sqlite:///C:/...` is the standard SQLAlchemy form but untested here.
8. **Several UI paths** (Blueprint prior, prior-file twins, exclusion flow, prior-file activity warnings) are implemented and covered by backend tests but were **not** driven through the UI by the author (marked [Unverified]).
9. **Guest "Create a real account" link** (Settings → Account) redirects a signed-in guest to the workspace instead of the registration form; log out first.
10. **The Create Account panel is taller than a 900 px-high screen**, so it may need a small scroll at 1440 × 900 (Sign In fits).
11. **Visual reference mockup** is not stored in the repository, so the visual checks in this guide are descriptive, not a comparison against it.
12. **Scope of the author's own runs:** one Linux machine, Chromium via automation, temporary databases; no Windows, Edge, Firefox or Safari testing; no screen reader; no physical phone; no external security review.

*End of guide.*
