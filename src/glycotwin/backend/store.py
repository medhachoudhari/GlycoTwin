"""SqlTwinStore: the existing TwinStore interface backed by the database, scoped to ONE twin.

The engine functions are reused unchanged: `forecast_meal`, `reconcile_forecast` and `exclude_forecast` (twin/state.py) call the same store methods they
call on the in-memory TwinStore, so the Bayesian update, its guards (once only, window closed, label consistent, finite) and the forecast arithmetic exist in
exactly one place. Atomicity comes from the database transaction opened by the service layer (rollback on any error), which replaces the in-memory
snapshot/restore used by the research replay. Writes that need API context (client event id, observation id) read it from `context`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from glycotwin.backend.models import ForecastRow, ObservationRow, ParameterSnapshot, ReconciliationRow, Twin, TwinStateRow
from glycotwin.models.bayesian import BayesianLinearState, ForecastDistribution
from glycotwin.twin.state import ExclusionRecord, ForecastRecord, ObservationRecord, TwinState, TwinStore


# ----------------------------------------------------------------------------- (de)serialisation of the engine's objects

def state_to_dict(s: BayesianLinearState) -> dict:
    return {"feature_names": list(s.feature_names), "mean": [float(x) for x in np.asarray(s.mean).ravel()],
            "covariance": [[float(x) for x in row] for row in np.asarray(s.covariance)], "noise_variance": float(s.noise_variance),
            "version": int(s.version), "n_observations_used": int(s.n_observations_used), "activity_center": float(s.activity_center),
            "prior_source": str(s.prior_source)}


def dict_to_state(d: dict) -> BayesianLinearState:
    return BayesianLinearState(feature_names=list(d["feature_names"]), mean=np.asarray(d["mean"], dtype=float),
                               covariance=np.asarray(d["covariance"], dtype=float), noise_variance=float(d["noise_variance"]),
                               version=int(d.get("version", 0)), n_observations_used=int(d.get("n_observations_used", 0)),
                               activity_center=float(d.get("activity_center", 0.0)), prior_source=str(d.get("prior_source", "unspecified")))


def _snapshot_row(model: str, s: BayesianLinearState) -> ParameterSnapshot:
    names = list(s.feature_names)
    cov = np.asarray(s.covariance, dtype=float)
    ib = names.index("carbs_g")
    ig = names.index("carbs_x_activity") if "carbs_x_activity" in names else None
    return ParameterSnapshot(model=model, feature_names=names, mean=[float(x) for x in np.asarray(s.mean).ravel()],
                             covariance=[[float(x) for x in r] for r in cov], noise_variance=float(s.noise_variance),
                             activity_center=float(s.activity_center), n_observations_used=int(s.n_observations_used), prior_source=str(s.prior_source),
                             beta_mean=float(np.asarray(s.mean)[ib]), beta_var=float(cov[ib, ib]),
                             gamma_mean=None if ig is None else float(np.asarray(s.mean)[ig]), gamma_var=None if ig is None else float(cov[ig, ig]),
                             beta_gamma_cov=None if ig is None else float(cov[ib, ig]))


def _snapshot_to_state(p: ParameterSnapshot, version: int) -> BayesianLinearState:
    return BayesianLinearState(feature_names=list(p.feature_names), mean=np.asarray(p.mean, dtype=float), covariance=np.asarray(p.covariance, dtype=float),
                               noise_variance=float(p.noise_variance), version=version, n_observations_used=int(p.n_observations_used),
                               activity_center=float(p.activity_center), prior_source=p.prior_source)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo is not None else dt


def meal_row_from_inputs(inputs: dict) -> pd.Series:
    row = {k: v for k, v in inputs.items() if k not in ("event_id", "meal_time") and v is not None}
    row["meal_time"] = pd.Timestamp(inputs["meal_time"])
    return pd.Series(row)


def forecast_row_to_record(r: ForecastRow) -> ForecastRecord:
    return ForecastRecord(forecast_id=r.id, participant_id=r.twin_id, meal_time=pd.Timestamp(r.meal_time), twin_version_at_forecast=r.twin_version_at_forecast,
                          model_b_forecast=ForecastDistribution(r.b_mean_rise, r.b_sd, r.b_probability, (r.b_interval_low, r.b_interval_high)),
                          model_c_forecast=ForecastDistribution(r.c_mean_rise, r.c_sd, r.c_probability, (r.c_interval_low, r.c_interval_high)),
                          meal_row=meal_row_from_inputs(r.inputs), created_at=_aware(r.created_at), data_quality=dict(r.data_quality or {}))


# ----------------------------------------------------------------------------- the store

class SqlTwinStore(TwinStore):
    def __init__(self, session: Session, twin_id: str) -> None:              # noqa: D107 - deliberately not calling TwinStore.__init__
        self.session, self.twin_id = session, twin_id
        self.context: Dict[str, object] = {}

    # --- scope
    def _check(self, participant_id: str) -> Twin:
        if participant_id != self.twin_id:
            raise KeyError(f"no twin state for participant {participant_id!r}")
        twin = self.session.get(Twin, self.twin_id)
        if twin is None:
            raise KeyError(f"no twin state for participant {participant_id!r}; call initialize_twin() first")
        return twin

    def participants(self) -> list[str]:
        return [self.twin_id] if self.session.get(Twin, self.twin_id) is not None else []

    # --- versions
    def _rows(self) -> List[TwinStateRow]:
        return list(self.session.scalars(select(TwinStateRow).where(TwinStateRow.twin_id == self.twin_id).order_by(TwinStateRow.version)))

    def _to_state(self, twin: Twin, row: TwinStateRow) -> TwinState:
        p = {s.model: s for s in row.parameters}
        return TwinState(participant_id=twin.id, model_b=_snapshot_to_state(p["B"], row.version), model_c=_snapshot_to_state(p["C"], row.version),
                         version=row.version, created_at=_aware(row.created_at), profile=dict(twin.profile or {}), parent_version=row.parent_version)

    def current_twin(self, participant_id: str) -> TwinState:
        twin = self._check(participant_id)
        row = self.session.scalars(select(TwinStateRow).where(TwinStateRow.twin_id == self.twin_id).order_by(TwinStateRow.version.desc()).limit(1)).first()
        if row is None:
            raise KeyError(f"no twin state for participant {participant_id!r}; call initialize_twin() first")
        return self._to_state(twin, row)

    def twin_history(self, participant_id: str) -> list[TwinState]:
        try:
            twin = self._check(participant_id)
        except KeyError:
            return []
        return [self._to_state(twin, r) for r in self._rows()]

    def initialize_twin(self, participant_id, model_b_prior, model_c_prior, profile=None) -> TwinState:
        twin = self._check(participant_id)
        if self._rows():
            raise ValueError(f"twin already initialized for participant {participant_id!r}")
        state = TwinState(participant_id=participant_id, model_b=model_b_prior, model_c=model_c_prior, version=0, profile=dict(profile or {}))
        self._save_new_version(state)
        return self._to_state(twin, self._rows()[-1])

    def _save_new_version(self, state: TwinState) -> None:
        self._check(state.participant_id)
        row = TwinStateRow(twin_id=self.twin_id, version=int(state.version), parent_version=state.parent_version, created_at=_naive(state.created_at),
                           n_observations=int(state.model_c.n_observations_used))
        row.parameters = [_snapshot_row("B", state.model_b), _snapshot_row("C", state.model_c)]
        self.session.add(row)
        self.session.flush()                                        # unique (twin_id, version) is enforced here

    # --- forecasts
    def save_forecast(self, record: ForecastRecord) -> None:
        ctx = self.context
        for k in ("event_id", "inputs", "input_sha256", "model_version", "engine_provenance"):
            if k not in ctx:
                raise RuntimeError(f"forecast context is missing {k!r}")
        b, c = record.model_b_forecast, record.model_c_forecast
        dq = dict(record.data_quality or {})
        extra = list(ctx.get("extra_quality_reasons") or [])
        if extra:                                                # support warnings from the service layer (information only; never changes the forecast)
            dq["reasons"] = list(dq.get("reasons", [])) + extra
            dq["low_data_quality"] = True
            dq["warnings"] = list(dq.get("warnings", [])) + ["OUTSIDE PRIOR RANGE: " + "; ".join(extra)]
            dq["warning"] = " ".join(dq["warnings"])
        self.session.add(ForecastRow(
            id=record.forecast_id, twin_id=self.twin_id, event_id=ctx["event_id"], meal_time=pd.Timestamp(record.meal_time).to_pydatetime(),
            inputs=ctx["inputs"], input_sha256=ctx["input_sha256"], twin_version_at_forecast=record.twin_version_at_forecast,
            created_at=_naive(record.created_at), model_version=ctx["model_version"], engine_provenance=ctx["engine_provenance"],
            data_quality=dq,
            b_probability=float(b.probability_exceeds_180), b_mean_rise=float(b.mean_rise), b_sd=float(b.predictive_std),
            b_interval_low=float(b.interval_90[0]), b_interval_high=float(b.interval_90[1]),
            c_probability=float(c.probability_exceeds_180), c_mean_rise=float(c.mean_rise), c_sd=float(c.predictive_std),
            c_interval_low=float(c.interval_90[0]), c_interval_high=float(c.interval_90[1])))
        self.session.flush()                                        # unique (twin_id, event_id) is enforced here

    def get_forecast(self, forecast_id: str) -> ForecastRecord:
        r = self.session.get(ForecastRow, forecast_id)
        if r is None or r.twin_id != self.twin_id:
            raise KeyError(forecast_id)
        return forecast_row_to_record(r)

    @property
    def _forecasts(self) -> Dict[str, ForecastRecord]:            # read by twin/state_view.py
        rows = self.session.scalars(select(ForecastRow).where(ForecastRow.twin_id == self.twin_id))
        return {r.id: forecast_row_to_record(r) for r in rows}

    def _recon(self, forecast_id: str) -> Optional[ReconciliationRow]:
        return self.session.scalars(select(ReconciliationRow).where(ReconciliationRow.forecast_id == forecast_id)).first()

    def is_reconciled(self, forecast_id: str) -> bool:
        r = self._recon(forecast_id)
        return r is not None and r.outcome == "updated"

    def is_excluded(self, forecast_id: str) -> bool:
        r = self._recon(forecast_id)
        return r is not None and r.outcome == "excluded"

    def save_observation(self, record: ObservationRecord) -> None:
        """Called by reconcile_forecast AFTER the new version was written: records the reconciliation and links the version to it."""
        rid, oid = self.context.get("reconciliation_id"), self.context.get("observation_id")
        if rid is None or oid is None:
            raise RuntimeError("reconciliation context is missing")
        after = int(record.twin_version_after_update)
        self.session.add(ReconciliationRow(id=rid, forecast_id=record.forecast_id, observation_id=oid, outcome="updated",
                                           twin_version_before=after - 1, twin_version_after=after, reconciled_at=_naive(record.reconciled_at)))
        self.session.flush()
        st = self.session.scalars(select(TwinStateRow).where(TwinStateRow.twin_id == self.twin_id, TwinStateRow.version == after)).one()
        st.reconciliation_id = rid
        self.session.flush()

    def save_exclusion(self, record: ExclusionRecord) -> None:
        rid, oid = self.context.get("reconciliation_id"), self.context.get("observation_id")
        if rid is None or oid is None:
            raise RuntimeError("reconciliation context is missing")
        v = self.current_twin(self.twin_id).version
        self.session.add(ReconciliationRow(id=rid, forecast_id=record.forecast_id, observation_id=oid, outcome="excluded",
                                           twin_version_before=v, twin_version_after=v, reconciled_at=_naive(record.recorded_at),
                                           metrics={"reason": record.reason}))
        self.session.flush()

    # --- read-only views used by twin/insight.py and twin/state_view.py
    def reconciliation_log(self, participant_id: str) -> list[ObservationRecord]:
        self._check(participant_id)
        q = (select(ReconciliationRow, ObservationRow).join(ObservationRow, ObservationRow.id == ReconciliationRow.observation_id)
             .join(ForecastRow, ForecastRow.id == ReconciliationRow.forecast_id)
             .where(ForecastRow.twin_id == self.twin_id, ReconciliationRow.outcome == "updated").order_by(ReconciliationRow.twin_version_after))
        return [ObservationRecord(forecast_id=r.forecast_id, observed_peak_rise=float(o.peak_glucose_rise), observed_exceeds_180=bool(o.label_exceeds_180),
                                  reconciled_at=_aware(r.reconciled_at), twin_version_after_update=r.twin_version_after) for r, o in self.session.execute(q)]

    def exclusions(self, participant_id: str) -> list[ExclusionRecord]:
        self._check(participant_id)
        q = (select(ReconciliationRow).join(ForecastRow, ForecastRow.id == ReconciliationRow.forecast_id)
             .where(ForecastRow.twin_id == self.twin_id, ReconciliationRow.outcome == "excluded"))
        return [ExclusionRecord(forecast_id=r.forecast_id, reason=str((r.metrics or {}).get("reason", "")), recorded_at=_aware(r.reconciled_at))
                for r in self.session.scalars(q)]

    def pending_forecasts(self, participant_id: str) -> list[ForecastRecord]:
        self._check(participant_id)
        done = set(self.session.scalars(select(ReconciliationRow.forecast_id).join(ForecastRow, ForecastRow.id == ReconciliationRow.forecast_id)
                                        .where(ForecastRow.twin_id == self.twin_id)))
        rows = self.session.scalars(select(ForecastRow).where(ForecastRow.twin_id == self.twin_id).order_by(ForecastRow.meal_time))
        return [forecast_row_to_record(r) for r in rows if r.id not in done]

    # --- the in-memory snapshot mechanism is replaced by database transactions
    def _snapshot(self):
        raise NotImplementedError("SqlTwinStore is atomic through database transactions; use the service layer")

    def _restore(self, snapshot) -> None:
        raise NotImplementedError("SqlTwinStore is atomic through database transactions; use the service layer")
