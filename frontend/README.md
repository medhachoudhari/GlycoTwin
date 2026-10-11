# GlycoTwin frontend (research prototype)

React + Vite + TypeScript. A dark-themed landing page, **preview-only** Sign In and Create Account pages, and a research workspace over the real FastAPI backend.

## Pages (hash routes)
The app uses one hash router, so refresh and direct links work without server configuration.

| Address | Page |
|---|---|
| `#/` | Landing page (anchors `#/product`, `#/research`, `#/how`, `#/docs`) |
| `#/login` | Sign In (**preview only**) |
| `#/register` | Create Account (**preview only**) |
| `#/app/home`, `#/app/twin`, `#/app/forecast`, `#/app/observations`, `#/app/history`, `#/app/insights`, `#/app/settings` | Research workspace |

There is no `#/forgot-password` page: there is no password-recovery flow.

## Authentication is preview-only
The Sign In and Create Account pages are a visual design preview. **There is no real authentication.** The forms check the input in the browser, then say that sign-in or account creation is not available. They send nothing to the backend, store nothing, never show a signed-in or account-created state, and clear the typed password after submitting.

Not implemented: real user accounts, sessions, password recovery, logout, and per-user twin ownership. The backend has no users or ownership, so any twin can be opened by anyone who can reach the backend and knows its id.

**Continue as demo** opens the existing research workspace without an account. It is labelled as demonstration mode (the workspace sidebar says "Demonstration mode: no account. Twins are not private to a user.") and does not pretend to authenticate anyone. Do not enter personal health data. Adding real authentication would need a users table with hashed passwords, secure sessions, twin ownership and protection of every twin route; that is a separate design decision.

GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.

## Run (Windows PowerShell)
```powershell
# terminal 1, repo root, Python venv active
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000

# terminal 2
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```
Checks: `npm run typecheck`, `npm test`, `npm run build`. Manual test plan: `docs/WEBSITE_TESTING_GUIDE.md`.

## Configuration
`VITE_API_BASE_URL` (default `/api`, proxied by Vite to `VITE_API_PROXY_TARGET`, default `http://127.0.0.1:8000`). The backend has no CORS, so keep the proxy.

## Scientific rules
- Only values returned by the backend are drawn; nothing is simulated in the browser and the Bayesian model is not reimplemented.
- The backend forecasts the *maximum* glucose in the 120 min after a meal (probability, mean rise, 90% interval), not a time course; the chart draws exactly that.
- Lifecycle: forecast, record outcome (after the window closes), apply to twin (new version). Excluded meals never update the twin.

## Known limitations
- No real accounts, authentication, sessions, password recovery or per-user twin ownership (Sign In / Create Account are preview-only).
- No twin-list endpoint: this browser remembers twins you created or opened (localStorage). Twin labels must be unique and match `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`.
- A recorded but unapplied outcome's value is shown only for the current session.
- Demonstration twins use a simulated 0 to 1 activity scale, not METs.
- Not clinically validated. The "approved UI concept image" was not available; the design follows the written direction.
