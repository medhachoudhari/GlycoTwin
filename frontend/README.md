# GlycoTwin frontend (research prototype)

React + Vite + TypeScript. A dark-themed landing page, real **Sign In** and **Create Account** pages, and a research workspace over the real FastAPI backend.
**The frontend and the backend must run together**: the website calls the backend through the Vite proxy (`/api/...` goes to `http://127.0.0.1:8000`), and every twin screen needs a signed-in account.

GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.

## Pages (hash routes)
The app uses one hash router, so refresh and direct links work without server configuration.

| Address | Page | Access |
|---|---|---|
| `#/` | Landing page (anchors `#/product`, `#/research`, `#/how`, `#/docs`) | public |
| `#/login` | Sign In | public (a signed-in user is sent to the workspace) |
| `#/register` | Create Account | public (a signed-in user is sent to the workspace) |
| `#/app/home`, `#/app/twin`, `#/app/forecast`, `#/app/observations`, `#/app/history`, `#/app/insights`, `#/app/settings` | Research workspace | **signed-in users only**; signed-out visitors are sent to `#/login` |

There is no `#/forgot-password` page: password recovery is not implemented.

## Accounts and sessions (implemented)
- **Create Account** (`POST /auth/register`) takes a name, email and a password of 10 to 128 characters. **Sign In** (`POST /auth/login`) takes email and password. Success is shown only after the backend confirms it; errors appear next to the field ("An account with this email already exists", "Incorrect email or password.", rate-limit and server messages).
- The session is an **HttpOnly cookie** set by the backend and sent through the Vite proxy. The page cannot read it; passwords and session tokens are never written to `localStorage` or `sessionStorage`, and the typed password is cleared after every attempt.
- After a reload the app asks the backend who you are (`GET /auth/me`) and restores your session. If the session has expired or was revoked, you are sent to Sign In with "Your session has ended. Please sign in again." If the backend cannot be reached you see "Cannot reach the backend" with Try again (you are not silently signed out).
- **Log out** (sidebar and Settings, `POST /auth/logout`) ends the session on the server and returns to `#/login`.
- **Continue as demo** (`POST /auth/guest`) creates a **temporary guest account**: it has the same ownership protection as a registered account (it sees only its own twins), is labelled Guest in the sidebar, cannot be signed in to again, and expires after 24 hours by default. Do not enter personal health data.
- **My twins** (Settings) comes from `GET /twins`, which lists only your own twins. Creating a twin adds it to the list. The only thing kept in the browser is which of your twins was last open, keyed by your user id.

## Limitations of the account system
Not implemented: password recovery (no "Forgot password"), email verification, account deletion, cleanup of expired guest accounts, "remember me", and per-user twin labels (labels are globally unique, so a label already used by another account is refused). The backend's sign-in rate limits are in memory and reset when it restarts. Old twins created before accounts existed are hidden until claimed with `scripts/claim_twin.py` (see `docs/BACKEND.md`). Run the backend only on `127.0.0.1`: it has no TLS and has not been security-audited. Not tested on Windows by the authors.

## Run (Windows PowerShell)
```powershell
# terminal 1, repo root, Python venv active
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000

# terminal 2
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```
Use a throw-away database for testing by setting `$env:GLYCOTWIN_DATABASE_URL` before starting the backend (see the root `README.md`); back up your real database file before the first run with the account-enabled backend.
Checks: `npm run typecheck`, `npm test` (37 tests), `npm run build`. Manual test plan: `docs/WEBSITE_TESTING_GUIDE.md`.

## Configuration
`VITE_API_BASE_URL` (default `/api`, proxied by Vite to `VITE_API_PROXY_TARGET`, default `http://127.0.0.1:8000`). The backend has no CORS, so keep the proxy.

## Scientific rules
- Only values returned by the backend are drawn; nothing is simulated in the browser and the Bayesian model is not reimplemented.
- The backend forecasts the *maximum* glucose in the 120 min after a meal (probability, mean rise, 90% interval), not a time course; the chart draws exactly that.
- Lifecycle: forecast, record outcome (after the window closes), apply to twin (new version). Excluded meals never update the twin.

## Known limitations
- Twin labels must be unique across all accounts and match `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` (no spaces).
- A recorded but unapplied outcome's value is shown only for the current page session.
- Demonstration twins use a simulated 0 to 1 activity scale, not METs.
- Double-clicking **Request forecast** stores two forecasts; the Home "Awaiting outcome" card can understate pending forecasts (see `docs/GLYCOTWIN_COMPLETE_TEST_REPORT.md`).
- Not clinically validated. The "approved UI concept image" is not stored in the repository; the design follows the written direction.
