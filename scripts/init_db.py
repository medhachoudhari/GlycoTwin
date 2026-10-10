"""Create the GlycoTwin backend database (missing tables only; never drops or alters data) and optionally add a SYNTHETIC demo twin.

The demo twin uses the simulated demo population and simulated meals from glycotwin.twin.demo; no CGMacros data is read.

Usage (PowerShell):
    python scripts\\init_db.py                     # tables only (default database: data\\interim\\glycotwin_backend.sqlite3)
    python scripts\\init_db.py --demo              # plus a labelled synthetic demo twin with 8 forecast-observe-reconcile cycles
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from glycotwin.backend.config import Settings, get_settings
from glycotwin.backend.db import init_db, make_engine, session_factory
from glycotwin.backend.models import Twin
from glycotwin.backend.schemas import ForecastRequest, ObserveRequest, ReconcileRequest, TwinCreate
from glycotwin.backend import services

DEMO_LABEL = "demo-synthetic-001"


def add_demo(session, settings, n_events: int = 8) -> dict:
    from sqlalchemy import select
    from glycotwin.twin.demo import demo_events
    if session.scalars(select(Twin).where(Twin.label == DEMO_LABEL)).first() is not None:
        return {"demo": "already present; nothing changed"}
    twin = services.create_twin(session, settings, TwinCreate(label=DEMO_LABEL, reference_activity=0.5))
    tid = twin["twin_id"]
    for _, e in demo_events(0, n_events).iterrows():
        f, _ = services.forecast(session, tid, ForecastRequest(event_id=str(e["event_id"]).replace("DEMO-SYNTHETIC-001-", "synthetic-"),
                                                               meal_time=e["meal_time"].to_pydatetime(), carbs_g=float(e["carbs_g"]),
                                                               activity_level=float(e["activity_level"]), baseline_glucose=float(e["baseline_glucose"])))
        services.observe(session, tid, ObserveRequest(forecast_id=f["forecast_id"], observed_through=e["meal_time"].to_pydatetime() + timedelta(minutes=120),
                                                      peak_glucose_mg_dl=min(600.0, max(20.0, float(e["baseline_glucose"] + e["peak_glucose_rise"])))))
        services.reconcile(session, tid, ReconcileRequest(forecast_id=f["forecast_id"]))
    return {"demo_twin_id": tid, "label": DEMO_LABEL, "events": n_events, "note": "SYNTHETIC demonstration data; not CGMacros"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--database-url", default=None, help="Overrides GLYCOTWIN_DATABASE_URL (default: SQLite file under data/interim).")
    ap.add_argument("--demo", action="store_true", help="Add the labelled synthetic demo twin (skipped if it already exists).")
    args = ap.parse_args(argv)
    s = get_settings()
    settings = Settings(database_url=args.database_url or s.database_url, prior_dir=s.prior_dir, default_reference_activity=s.default_reference_activity)
    engine = make_engine(settings.database_url)
    init_db(engine)
    out = {"database": "initialised (missing tables created; nothing dropped)"}
    if args.demo:
        session = session_factory(engine)()
        try:
            out.update(add_demo(session, settings))
        finally:
            session.close()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
