"""Write an AGGREGATE prior artifact for live twins from a LOCAL event table (offline; the API never reads participant-level data).

The artifact holds only prior means, covariances, noise variances and provenance counts. It is fitted on core- and activity-eligible events (Model C's
population). If the live twin is for a person who is IN this research population, that person MUST be excluded with --exclude-participant (their
outcomes may never enter their own prior); otherwise state explicitly that the live person is not in the population with --live-person-not-in-population.

Usage (PowerShell):
    python scripts\\export_prior.py --event-table data\\interim\\runs\\primary_Libre_gap15\\event_table_Libre_GL.csv --live-person-not-in-population --name libre_eb.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from glycotwin.backend.config import get_settings
from glycotwin.backend.priors import make_prior_artifact
from glycotwin.models.bayesian import MODEL_B_BLUEPRINT_FEATURES, fit_population_prior
from glycotwin.models.prior_schemes import GAMMA_WIDTHS, PRIOR_SCHEMES, event_table_info, git_state, validate_prior_options
from glycotwin.twin.adapter import canonical_ids, canonical_participant_id


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--event-table", required=True)
    ap.add_argument("--name", required=True, help="Output file name (*.json) inside the prior directory (GLYCOTWIN_PRIOR_DIR).")
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--exclude-participant", action="append", default=None, help="Research participant id to exclude (repeatable).")
    who.add_argument("--live-person-not-in-population", action="store_true", help="Declare that the live person is not in this research population.")
    ap.add_argument("--prior-scheme", default="empirical_bayes", choices=list(PRIOR_SCHEMES))
    ap.add_argument("--gamma-relative-sd", type=float, default=None, choices=list(GAMMA_WIDTHS))
    ap.add_argument("--groups-file", default=None, help="Blueprint prior: CSV participant_id,group for the stratified beta prior.")
    ap.add_argument("--glycaemic-group", default=None, help="Blueprint prior: the live person's group (selects the stratum).")
    args = ap.parse_args(argv)
    try:
        validate_prior_options("C", args.prior_scheme, args.gamma_relative_sd)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    table_path = Path(args.event_table)
    if not table_path.exists():
        print("error: the event table was not found.", file=sys.stderr)
        return 2
    out = get_settings().prior_dir / args.name
    if not args.name.endswith(".json") or "/" in args.name or "\\" in args.name:
        print("error: --name must be a plain *.json file name.", file=sys.stderr)
        return 2
    if out.exists():
        print("error: a prior artifact with this name already exists; choose a new name (artifacts are never overwritten).", file=sys.stderr)
        return 2
    table = pd.read_csv(table_path)
    pop = table[table["eligible_core"].astype(bool) & table["eligible_activity"].astype(bool)].copy()
    ids = canonical_ids(pop["participant_id"])
    excluded = 0
    if args.exclude_participant:
        targets = {canonical_participant_id(p) for p in args.exclude_participant}
        mask = ids.isin(targets)
        missing = targets - set(ids[mask])
        if missing:
            print(f"error: {len(missing)} participant(s) to exclude were not found in the population; nothing was written.", file=sys.stderr)
            return 2
        excluded = len(targets)
        pop = pop[~mask.to_numpy()]
    if args.prior_scheme == "blueprint":
        from glycotwin.models.blueprint_prior import fit_blueprint_prior
        if args.groups_file:
            g = pd.read_csv(args.groups_file)
            gm = dict(zip(g["participant_id"].map(canonical_participant_id), g["group"]))
            pop["glycaemic_group"] = canonical_ids(pop["participant_id"]).map(gm)
        prior_b, prior_c, d = fit_blueprint_prior(pop, glycaemic_group=args.glycaemic_group, gamma_relative_sd=args.gamma_relative_sd or 0.5)
        width, detail = args.gamma_relative_sd or 0.5, {"group_used": d["group_used"], "fallback_reason": d["fallback_reason"]}
    else:
        from glycotwin.models.model_c_cv import fit_scale_aware_prior
        prior_b, prior_c = fit_population_prior(pop, MODEL_B_BLUEPRINT_FEATURES), fit_scale_aware_prior(pop)[0]
        width, detail = None, {}
    info = event_table_info(table_path)
    prov = {"prior_scheme": args.prior_scheme, "gamma_relative_sd": width, "fitted_on": "core- and activity-eligible events of the event table, excluded participants removed",
            "n_participants": int(pop["participant_id"].nunique()), "n_events": int(len(pop)),
            "activity_range": [float(pop["activity_level"].min()), float(pop["activity_level"].max())],   # aggregate; used to FLAG extrapolation
            "excluded_participants_count": excluded,
            "live_person_declared_not_in_population": bool(args.live_person_not_in_population), "event_table_file_sha256": info["event_table_file_sha256"],
            "event_table_settings": info["event_table_settings"], "code": git_state(), **detail}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(make_prior_artifact(prior_b, prior_c, prov), indent=2), encoding="utf-8")
    print(json.dumps({"written": out.name, "n_participants": prov["n_participants"], "n_events": prov["n_events"], "excluded_participants": excluded,
                      "prior_scheme": args.prior_scheme, "gamma_relative_sd": width}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
