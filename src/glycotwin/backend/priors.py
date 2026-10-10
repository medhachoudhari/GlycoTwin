"""Where a live twin's version-0 prior comes from. Two sources only:

  synthetic_demo  priors fitted on the SIMULATED demo population (twin/demo.py). Clearly labelled synthetic; for trying the API.
  prior_file      an AGGREGATE prior artifact (means, covariances, noise variance and provenance only) written OFFLINE by scripts/export_prior.py
                  from a local event table. The API never reads participant-level research data: it reads only these artifacts, from the configured
                  prior directory, and refuses an artifact that does not declare `contains_participant_level_data: false`.
A live twin is initialised from a population prior only; no held-out research outcome is ever used. If a live twin represents a person who IS in the
research population, the artifact must be exported with that person excluded (export_prior.py refuses to run without an explicit exclusion decision).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from glycotwin.backend.store import dict_to_state, state_to_dict
from glycotwin.models.bayesian import MODEL_B_BLUEPRINT_FEATURES, BayesianLinearState, fit_population_prior
from glycotwin.models.prior_schemes import validate_prior_options

PRIOR_FORMAT = "glycotwin-prior/1"
# The simulated demo population draws activity on a 0-1 scale (NOT METs). Model C uses raw, un-centred activity, so a demo prior is only meaningful on that scale:
# gamma was estimated from [0, 1] and extrapolating it to real METs (typically 1-3 or more) gives misleading forecasts. The demo twin therefore rejects
# activity outside this range instead of extrapolating silently. The research equations and real-data runs are unchanged.
DEMO_ACTIVITY_RANGE = (0.0, 1.0)
MODEL_C_FEATURES = ["carbs_g", "carbs_x_activity"]
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.json$")


class PriorError(ValueError):
    pass


def _check_state(s: BayesianLinearState, features: list, label: str) -> None:
    if list(s.feature_names) != features:
        raise PriorError(f"{label} prior must use features {features}")
    if s.activity_center != 0.0:
        raise PriorError(f"{label} prior must be un-centred (activity_center 0)")
    cov = np.asarray(s.covariance, dtype=float)
    if not (np.isfinite(s.mean).all() and np.isfinite(cov).all() and np.isfinite(s.noise_variance)) or s.noise_variance <= 0:
        raise PriorError(f"{label} prior has non-finite values or a non-positive noise variance")
    if not np.allclose(cov, cov.T) or np.linalg.eigvalsh((cov + cov.T) / 2).min() <= 0:
        raise PriorError(f"{label} prior covariance is not symmetric positive definite")


def demo_prior(prior_scheme: str = "empirical_bayes", gamma_relative_sd: Optional[float] = None) -> Tuple[BayesianLinearState, BayesianLinearState, dict]:
    from glycotwin.twin.demo import demo_population
    scheme_b, _ = validate_prior_options("B", prior_scheme, None)
    scheme_c, width = validate_prior_options("C", prior_scheme, gamma_relative_sd)
    pop = demo_population(0)
    if scheme_c == "blueprint":
        from glycotwin.models.blueprint_prior import fit_blueprint_prior
        prior_b, prior_c, d = fit_blueprint_prior(pop, glycaemic_group=None, gamma_relative_sd=width)
        detail = {"fallback_reason": d["fallback_reason"]}
    else:
        from glycotwin.models.model_c_cv import fit_scale_aware_prior
        prior_b = fit_population_prior(pop, MODEL_B_BLUEPRINT_FEATURES)
        prior_c, _ = fit_scale_aware_prior(pop)
        detail = {}
    prov = {"source": "synthetic_demo", "SYNTHETIC": True, "population": "simulated demo population (twin/demo.py, seed 0)",
            "n_population_participants": int(pop["participant_id"].nunique()), "prior_scheme": scheme_c, "gamma_relative_sd": width,
            "activity_scale": "simulated 0-1 activity (not METs); Model C uses it raw and un-centred", "supported_activity_range": list(DEMO_ACTIVITY_RANGE),
            "activity_range_enforcement": "reject",
            "contains_participant_level_data": False, **detail}
    return prior_b, prior_c, prov


def load_prior_file(prior_dir: Path, name: str) -> Tuple[BayesianLinearState, BayesianLinearState, dict]:
    if not _NAME.match(name or ""):
        raise PriorError("prior file name must be a plain *.json file name inside the configured prior directory")
    path = Path(prior_dir) / name
    if not path.is_file():
        raise PriorError("prior file not found in the configured prior directory")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PriorError("prior file is not valid JSON") from None
    if d.get("format") != PRIOR_FORMAT:
        raise PriorError(f"prior file format must be {PRIOR_FORMAT!r}")
    if d.get("contains_participant_level_data") is not False:
        raise PriorError("prior file must declare contains_participant_level_data: false")
    allowed = {"format", "contains_participant_level_data", "model_b", "model_c", "provenance"}
    if set(d) - allowed:
        raise PriorError("prior file has unexpected keys; only aggregate prior parameters and provenance are accepted")
    try:
        b, c = dict_to_state(d["model_b"]), dict_to_state(d["model_c"])
    except (KeyError, TypeError, ValueError):
        raise PriorError("prior file is missing or has malformed model_b / model_c states") from None
    _check_state(b, list(MODEL_B_BLUEPRINT_FEATURES), "Model B")
    _check_state(c, MODEL_C_FEATURES, "Model C")
    prov = dict(d.get("provenance", {}))
    for k in ("prior_scheme", "fitted_on", "excluded_participants_count"):
        if k not in prov:
            raise PriorError(f"prior file provenance is missing {k!r}")
    prov.update({"source": "prior_file", "file_name": name, "contains_participant_level_data": False})
    return b, c, prov


def make_prior_artifact(prior_b: BayesianLinearState, prior_c: BayesianLinearState, provenance: dict) -> dict:
    return {"format": PRIOR_FORMAT, "contains_participant_level_data": False, "model_b": state_to_dict(prior_b), "model_c": state_to_dict(prior_c),
            "provenance": provenance}
