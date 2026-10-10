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
Foreign keys are enforced (SQLite `PRAGMA foreign_keys=ON`). Initialisation (`init_db`, application start-up, `scripts/init_db.py`) only creates missing tables; it contains no drop or delete statement (tested), so repeating it never changes existing rows. No raw CGM traces are stored; only per-meal summaries.

## Lifecycle and guarantees
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
`GET /health`, `POST /twins`, `GET /twins/{id}`, `GET /twins/{id}/history`, `POST /twins/{id}/forecast`, `GET /twins/{id}/forecasts`, `POST /twins/{id}/observe`,
`POST /twins/{id}/reconcile`, `POST /twins/{id}/what-if`. There is no endpoint that lists twins or research participants. Interactive docs: `/docs`.

## Not included
Authentication, migrations (tables are created if missing; schema changes would need a migration tool), the React frontend (next phase), and any real-data validation.
