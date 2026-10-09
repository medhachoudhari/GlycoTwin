"""Leakage-safe forecast -> observe -> reconcile -> update replay on the existing in-memory twin.

For a time-ordered event sequence of ONE participant: before every forecast, the outcomes of earlier meals whose window
(t0, t0 + 120 min] has closed are reconciled (one new twin version each); the forecast is then made from the current
posterior and stored; its own outcome is reconciled only once its window closes. A forecast therefore never sees its own
outcome or any later one. Uses `forecast_meal` / `reconcile_forecast` unchanged (their guards still apply).

Input safety (audit fix F1): every required value is validated BEFORE the store is touched (finite numbers, parseable times,
0/1 labels that agree with baseline + rise >= 180), so bad data is refused up front instead of producing NaN forecasts or a
half-advanced twin. As a second line of defence the replay is ATOMIC by default: if anything still fails midway, the store is
restored to exactly the state it had before the call and the error is re-raised.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from glycotwin.features import GLUCOSE_THRESHOLD_MG_DL, LABEL_TOLERANCE_MG_DL, OUTCOME_WINDOW
from glycotwin.twin.state import TwinStore, exclude_forecast, forecast_meal, reconcile_forecast

REQUIRED = ["meal_time", "carbs_g", "baseline_glucose", "activity_level", "peak_glucose_rise", "label_exceeds_180"]
NUMERIC = ["carbs_g", "baseline_glucose", "activity_level", "peak_glucose_rise"]
EXCLUDE_COLUMN = "excluded_reason"       # optional: a non-empty value marks the event's outcome as untrustworthy (e.g. a sensor gap); no update happens
PASSTHROUGH = ("event_id", "data_quality_flag", "activity_coverage", "window_completeness")


OUTCOME_ONLY = ("peak_glucose_rise",)


def _excluded_mask(ev: pd.DataFrame) -> np.ndarray:
    if EXCLUDE_COLUMN not in ev.columns:
        return np.zeros(len(ev), dtype=bool)
    col = ev[EXCLUDE_COLUMN]
    return (col.notna() & (col.astype(str).str.strip() != "")).to_numpy()


def validate_replay_events(events: pd.DataFrame) -> pd.DataFrame:
    """Return a validated, time-sorted copy of `events`, or raise ValueError naming the problem (counts and column names only)."""
    missing = [c for c in REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"events are missing columns: {missing}")
    if len(events) == 0:
        raise ValueError("no events to replay")
    ev = events.copy()
    ev["meal_time"] = pd.to_datetime(ev["meal_time"], errors="coerce")
    if ev["meal_time"].isna().any():
        raise ValueError(f"{int(ev['meal_time'].isna().sum())} events have a missing or unparseable meal_time")
    num = ev[NUMERIC].apply(pd.to_numeric, errors="coerce")
    excluded = _excluded_mask(ev)
    for c in NUMERIC:
        needed = ~excluded if c in OUTCOME_ONLY else np.ones(len(ev), dtype=bool)         # an excluded event has no trustworthy outcome
        bad = int((~np.isfinite(num[c].to_numpy(dtype=float)) & needed).sum())
        if bad:
            raise ValueError(f"{bad} events have a missing or non-finite {c}; nothing was replayed and the twin is unchanged")
    if (num["carbs_g"] < 0).any():
        raise ValueError(f"{int((num['carbs_g'] < 0).sum())} events have negative carbs_g")
    lab = pd.to_numeric(ev["label_exceeds_180"], errors="coerce")
    keep = ~excluded
    if (lab[keep].isna().any()) or not lab[keep].isin([0, 1]).all():
        raise ValueError("label_exceeds_180 must be 0 or 1 for every event")
    expected = (num["baseline_glucose"] + num["peak_glucose_rise"] >= GLUCOSE_THRESHOLD_MG_DL - LABEL_TOLERANCE_MG_DL).astype(int)
    mismatch = (expected != lab.fillna(-1).astype(int)) & keep
    if mismatch.any():
        raise ValueError(f"{int(mismatch.sum())} events have a label_exceeds_180 that disagrees with baseline_glucose + peak_glucose_rise >= 180")
    for c in NUMERIC:
        ev[c] = num[c]
    ev["label_exceeds_180"] = lab.fillna(0).astype(int)
    return ev.sort_values("meal_time", kind="stable").reset_index(drop=True)


class ReplaySession:
    """Step-by-step version of the replay (blueprint Part 15 `/replay/{id}/start` and `/step`, without a web layer). `step()` consumes ONE
    event: first the outcomes of earlier meals whose window has closed before this meal are reconciled (or excluded), then this meal is
    forecast. `finish()` resolves the outcomes still pending after the last meal. Each call is atomic: if anything fails the store and the
    session are restored to what they were before the call and the error is re-raised. Events are validated once, at construction."""

    def __init__(self, store: TwinStore, participant_id: str, events: pd.DataFrame, window: pd.Timedelta = OUTCOME_WINDOW):
        self.store, self.participant_id, self.window = store, participant_id, window
        self.events = validate_replay_events(events)
        self._excluded = _excluded_mask(self.events)
        store.current_twin(participant_id)                  # KeyError if the twin does not exist
        self._next = 0
        self._pending: List[tuple] = []                     # (window close, forecast_id, event index)
        self.log: List[dict] = []
        self.finished = False

    @property
    def n_events(self) -> int:
        return len(self.events)

    @property
    def n_remaining(self) -> int:
        return self.n_events - self._next

    @property
    def done(self) -> bool:
        return self.finished

    def _resolve(self, close, fid, i) -> None:
        pid, store, ev = self.participant_id, self.store, self.events
        before = store.current_twin(pid).version
        row = ev.iloc[i]
        if self._excluded[i]:
            exclude_forecast(store, fid, str(row[EXCLUDE_COLUMN]), observed_through=close)
            self.log.append({"seq": len(self.log), "action": "exclude (outcome untrustworthy; no update)", "event_index": int(i), "meal_time": str(row["meal_time"]),
                             "twin_version_before": before, "twin_version_after": before, "forecast_id": fid, "reason": str(row[EXCLUDE_COLUMN]).strip(),
                             "kind": "EXCLUDED (not used as evidence)"})
            return
        new = reconcile_forecast(store, fid, float(row["peak_glucose_rise"]), bool(row["label_exceeds_180"]), observed_through=close)
        self.log.append({"seq": len(self.log), "action": "reconcile (observe + update)", "event_index": int(i), "meal_time": str(row["meal_time"]),
                         "twin_version_before": before, "twin_version_after": new.version, "forecast_id": fid,
                         "observed_peak_rise": float(row["peak_glucose_rise"]), "observed_exceeds_180": bool(row["label_exceeds_180"]),
                         "kind": "OBSERVED (outcome window closed)"})

    def _atomic(self, fn):
        snap, pending, nlog, nxt, fin = self.store._snapshot(), list(self._pending), len(self.log), self._next, self.finished
        try:
            return fn()
        except Exception:
            self.store._restore(snap)
            self._pending, self._next, self.finished = pending, nxt, fin
            del self.log[nlog:]
            raise

    def step(self) -> List[dict]:
        """Process the next event. Returns the log entries this call added."""
        if self.finished or self._next >= self.n_events:
            raise StopIteration("the replay has no more events; call finish()" if not self.finished else "the replay is finished")
        return self._atomic(self._step)

    def _step(self) -> List[dict]:
        start = len(self.log)
        i = self._next
        row = self.events.iloc[i]
        due = sorted([p for p in self._pending if p[0] <= row["meal_time"]], key=lambda p: p[0])
        self._pending = [p for p in self._pending if p[0] > row["meal_time"]]
        for close, fid, j in due:
            self._resolve(close, fid, j)
        before = self.store.current_twin(self.participant_id).version
        rec = forecast_meal(self.store, self.participant_id, row)
        entry = {"seq": len(self.log), "action": "forecast (before outcome known)", "event_index": int(i), "meal_time": str(row["meal_time"]),
                 "twin_version_before": before, "twin_version_after": before, "forecast_id": rec.forecast_id,
                 "twin_version_at_forecast": rec.twin_version_at_forecast,
                 "model_b": {"p_peak_at_least_180": rec.model_b_forecast.probability_exceeds_180, "mean_rise_mg_dl": rec.model_b_forecast.mean_rise,
                             "sd_mg_dl": rec.model_b_forecast.predictive_std, "interval90_mg_dl": list(rec.model_b_forecast.interval_90)},
                 "model_c": {"p_peak_at_least_180": rec.model_c_forecast.probability_exceeds_180, "mean_rise_mg_dl": rec.model_c_forecast.mean_rise,
                             "sd_mg_dl": rec.model_c_forecast.predictive_std, "interval90_mg_dl": list(rec.model_c_forecast.interval_90)},
                 "quality_assessment": rec.data_quality, "quality_warning": rec.data_quality.get("warning"),
                 "data_quality": {c: (row[c].item() if hasattr(row[c], "item") else row[c]) for c in PASSTHROUGH if c in self.events.columns and c != "event_id"}}
        if not (np.isfinite(entry["model_b"]["p_peak_at_least_180"]) and np.isfinite(entry["model_c"]["p_peak_at_least_180"])):
            raise ValueError("a forecast was not finite; the replay was stopped")
        self.log.append(entry)
        self._pending.append((row["meal_time"] + self.window, rec.forecast_id, int(i)))
        self._next += 1
        return self.log[start:]

    def finish(self) -> List[dict]:
        """Resolve every outcome still pending (all remaining events must have been stepped first)."""
        if self._next < self.n_events:
            raise ValueError(f"{self.n_remaining} events have not been stepped yet")
        if self.finished:
            return []
        return self._atomic(self._finish)

    def _finish(self) -> List[dict]:
        start = len(self.log)
        for close, fid, j in sorted(self._pending, key=lambda p: p[0]):
            self._resolve(close, fid, j)
        self._pending = []
        self.finished = True
        return self.log[start:]


def replay_lifecycle(store: TwinStore, participant_id: str, events: pd.DataFrame, window: pd.Timedelta = OUTCOME_WINDOW,
                     atomic: bool = True) -> List[dict]:
    """Replay a whole event sequence. With atomic=True (default) a failure anywhere restores the store to exactly its state before the call."""
    session = ReplaySession(store, participant_id, events, window)         # validates first; KeyError if the twin does not exist
    snapshot = store._snapshot() if atomic else None
    try:
        while session.n_remaining:
            session._step()
        session._finish()
    except Exception:
        if snapshot is not None:
            store._restore(snapshot)
        raise
    return session.log
