"""Run the SYNTHETIC twin lifecycle demonstration (forecast -> observe -> reconcile -> update) and print a readable summary.

Everything shown is simulated: it is not CGMacos data and not a research result. In-memory only (no database, no web framework).

    python scripts/demo_twin_lifecycle.py [--seed 0] [--events 8] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from glycotwin.twin.demo import run_demo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--events", type=int, default=8)
    ap.add_argument("--json", action="store_true", help="print the full result as JSON instead of the summary")
    args = ap.parse_args(argv)
    res = run_demo(seed=args.seed, n_events=args.events)
    if args.json:
        print(json.dumps(res, indent=2, default=str))
        return 0
    print(res["banner"]); print()
    print("Lifecycle (each forecast is made BEFORE its outcome is known; each outcome then creates a new twin version):")
    for s in res["lifecycle_log"]:
        if s["action"].startswith("forecast"):
            print(f"  [{s['seq']:>2}] forecast  event {s['event_index']}  twin v{s['twin_version_at_forecast']}  "
                  f"P(>=180) B={s['model_b']['p_peak_at_least_180']:.2f} C={s['model_c']['p_peak_at_least_180']:.2f}  "
                  f"rise C={s['model_c']['mean_rise_mg_dl']:.0f} +/- {s['model_c']['sd_mg_dl']:.0f} mg/dL")
        else:
            print(f"  [{s['seq']:>2}] reconcile event {s['event_index']}  observed rise {s['observed_peak_rise']:.0f} mg/dL  "
                  f"twin v{s['twin_version_before']} -> v{s['twin_version_after']}")
    h = res["parameter_history"]
    print(f"\nParameter evolution (Model C sensitivity at activity {h['reference_activity']}; mg/dL per gram):")
    for r in h["versions"]:
        print(f"  v{r['version']}: B {r['b_sensitivity_mean']:.3f}+/-{r['b_sensitivity_sd']:.3f}   C beta {r['c_beta_mean']:.3f}+/-{r['c_beta_sd']:.3f}   "
              f"gamma {r['c_gamma_mean']:.3f}+/-{r['c_gamma_sd']:.3f}   s(a) {r['c_sensitivity_at_reference_mean']:.3f}+/-{r['c_sensitivity_at_reference_sd']:.3f}")
    print("\nWhat-if (HYPOTHETICAL scenarios on the current posterior; not observed):")
    for sc in res["what_if"]["scenarios"]:
        c = sc["model_c"]
        print(f"  {sc['scenario']['label']}: Model C rise {c['distribution']['mean_rise_mg_dl']:.0f} +/- {c['distribution']['sd_mg_dl']:.0f} mg/dL, "
              f"P(>=180) {c['p_peak_at_least_180']:.2f}")
    rc = res["reconciliation"]["summary"]
    print(f"\nReconciliation (forecast vs observed): {rc['n_reconciled']} reconciled; observed inside the 90% interval: "
          f"B {rc['model_b']['share_observed_inside_interval90']:.2f}, C {rc['model_c']['share_observed_inside_interval90']:.2f} (a handful of events cannot assess calibration)")
    cv, ht = res["convergence"], res["hit_rate_trend"]
    print(f"\nPosterior convergence: Model B sensitivity sd {cv['sd']['model_b_sensitivity_sd'][0]:.3f} -> {cv['sd']['model_b_sensitivity_sd'][-1]:.3f} "
          f"(ratio {cv['current_over_prior']['model_b_sensitivity_sd']:.2f}); gamma sd ratio {cv['current_over_prior']['model_c_gamma_sd']:.2f}")
    print(f"Reconciliation hit rate (50% threshold, {ht['n_reconciled']} meals): B {ht['model_b']['overall_hit_rate']:.2f}, C {ht['model_c']['overall_hit_rate']:.2f} (descriptive only)")
    sv = res["state_view"]
    print("Twin state view: unavailable components are listed, not invented:")
    for u in sv["unavailable"]:
        print("  - " + u)
    print("\nExplanation of one forecast (model decomposition, not a causal claim):")
    for line in res["explanation"]["plain_language"]:
        print("  " + line)
    print("\n" + res["banner"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
