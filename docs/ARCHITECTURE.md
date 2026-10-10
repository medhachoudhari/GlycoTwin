# Architecture (as implemented)

Research prototype: in-memory research engine plus a FastAPI + SQLite backend (`docs/BACKEND.md`); no frontend yet. Not clinically validated; no medical advice.

```
raw CSVs (local, never in Git)
   -> src/glycotwin/data/        loading, meal events, outcomes (locked event definition)
   -> event table (local, git-ignored)
        -> src/glycotwin/models/ model_a_cv / model_b_cv / model_c_cv   (participant-level folds, seed 0)
             -> sequential forecast CSVs (local, git-ignored)
                  -> model_bc_compare.py + reliability_svg.py          (matched paired comparison, aggregate output;
                     cold-start/experienced and per-participant active/sedentary splits via activity_strata.py)
        -> src/glycotwin/twin/adapter.py        (prior fitted without the participant; validated event feed)
             -> twin/state.py     TwinStore: versioned TwinState, forecasts, observations
             -> twin/replay.py    validate, forecast, reconcile once the 120-minute window closes (atomic)
             -> twin/quality.py   forecast-time data-quality and insufficient-history warnings (information only)
             -> twin/insight.py   read-only views: insight, history, convergence, hit-rate trend, reconciliation, explanation, what-if, overview
             -> twin/state_view.py  the blueprint's TwinState composed on demand from the store
             -> twin/demo.py      synthetic participant for demonstrations
```

Key invariants (each has tests): a forecast never sees its own outcome; a reconcile creates a new version and keeps the old one;
replay input is validated before the store is touched and rolled back on failure; the population prior excludes the participant;
the comparison refuses to run unless events, participants, folds and labels match; outputs for the repository are aggregate only.
Entry points: `scripts/run_model_{a,b,c}.py`, `scripts/compare_models_b_c.py`, `scripts/replay_participant.py`, `scripts/demo_twin_lifecycle.py`.

The blueprint-form prior (`models/blueprint_prior.py`) is an opt-in alternative to the empirical-Bayes priors; the research runs do not use it.
