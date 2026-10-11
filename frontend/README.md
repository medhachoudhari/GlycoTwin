# GlycoTwin frontend (research prototype)

React + Vite + TypeScript. A landing page (`#/`) and a research workspace (`#/app/...`) over the real FastAPI backend.

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
Checks: `npm run typecheck`, `npm test`, `npm run build`.

## Configuration
`VITE_API_BASE_URL` (default `/api`, proxied by Vite to `VITE_API_PROXY_TARGET`, default `http://127.0.0.1:8000`). The backend has no CORS, so keep the proxy.

## Scientific rules
- Only values returned by the backend are drawn; nothing is simulated in the browser and the Bayesian model is not reimplemented.
- The backend forecasts the *maximum* glucose in the 120 min after a meal (probability, mean rise, 90% interval), not a time course; the chart draws exactly that.
- Lifecycle: forecast, record outcome (after the window closes), apply to twin (new version). Excluded meals never update the twin.

## Known limitations
- No twin-list endpoint: this browser remembers twins you created or opened (localStorage). Twin labels must be unique and match `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`.
- A recorded but unapplied outcome's value is shown only for the current session.
- Demonstration twins use a simulated 0 to 1 activity scale, not METs.
- Not clinically validated. The "approved UI concept image" was not available; the design follows the written direction.
