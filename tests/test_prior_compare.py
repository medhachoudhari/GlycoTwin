"""Prior-versus-prior comparison tool (empirical Bayes vs blueprint, Models B and C). SYNTHETIC data only: mechanics, integrity refusals and the
prespecified screen are tested; nothing here says either prior is better on real data."""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.models import prior_schemes as ps
from glycotwin.models.model_bc_compare import paired_report
from glycotwin.models.prior_compare import (ARMS, CONTRASTS, DECISION_RULE_TEXT, METRICS, PriorComparisonError, adoption_screen,
                                            prior_comparison_report, validate_prior_arms)
from test_model_c_cv import cohort, make_events

ROOT = Path(__file__).resolve().parents[1]
GAMMA = 1.0


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Four real runner invocations (synthetic events) on one event table, exactly as the runbook does it."""
    tmp = tmp_path_factory.mktemp("priors")
    root = tmp / "ds"; root.mkdir()
    g = cohort()
    a1c = {"healthy": 5.2, "pre-diabetes": 6.0, "t2d": 7.1}
    pd.DataFrame({"subject": [int(p[-3:]) for p in g], "A1c PDL (Lab)": [a1c[v] for v in g.values()]}).to_csv(root / "bio.csv", index=False)
    table = tmp / "event_table_Libre_GL.csv"
    make_events(per=8, seed=5).to_csv(table, index=False)
    ps.settings_sidecar_path(table).write_text(json.dumps({"channel": "Libre GL", "max_cgm_gap_minutes": 15, "require_isolated": True,
                                                          "outcome_window_minutes": 120.0, "label_threshold_mg_dl": 180.0}))
    out = tmp / "out"
    rmb, rmc = _load("run_model_b"), _load("run_model_c")
    base = ["--data-root", str(root), "--event-table", str(table), "--n-boot", "5", "--out-dir", str(out)]
    for argv in ([rmb, ["--population", "activity-eligible"]], [rmb, ["--population", "activity-eligible", "--prior-scheme", "blueprint"]],
                 [rmc, []], [rmc, ["--prior-scheme", "blueprint", "--gamma-relative-sd", str(GAMMA)]]):
        assert argv[0].main(base + argv[1]) == 0
    paths = {"b_eb": out / "model_b_sequential_forecasts_Libre_GL_activity_eligible.csv",
             "b_bp": out / "model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv",
             "c_eb": out / "model_c_sequential_forecasts_Libre_GL.csv",
             "c_bp": out / f"model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma{GAMMA:g}.csv"}
    reports = {"b_eb": out / "model_b_Libre_GL_activity_eligible.json", "b_bp": out / "model_b_Libre_GL_activity_eligible_prior-blueprint.json",
               "c_eb": out / "model_c_Libre_GL.json", "c_bp": out / f"model_c_Libre_GL_prior-blueprint_gamma{GAMMA:g}.json"}
    return {"tmp": tmp, "out": out, "table": table, "paths": paths, "reports": reports}


def arms(run):
    frames = {a: pd.read_csv(p) for a, p in run["paths"].items()}
    reps = {a: json.loads(p.read_text()) for a, p in run["reports"].items()}
    return frames, reps


def script_args(run, **over):
    a = []
    for arm in ARMS:
        f = arm.replace("_", "-")
        a += [f"--{f}", str(run["paths"][arm]), f"--{f}-report", str(run["reports"][arm])]
    return a


# ------------------------------------------------------------------ the happy path

def test_matched_arms_are_accepted_and_the_report_has_every_contrast_and_metric(run):
    frames, reps = arms(run)
    rep = prior_comparison_report(frames, reps, n_boot=100, seed=0, expected_participants=45, expected_gamma=GAMMA)
    assert set(rep["contrasts"]) == set(CONTRASTS) and len(CONTRASTS) == 5
    for name, c in rep["contrasts"].items():
        assert set(c) == set(METRICS)
        for m, v in c.items():
            lo, hi = v["ci95"]
            assert lo <= hi and v["ci_excludes_zero"] == bool(lo > 0 or hi < 0) and np.isfinite(v["estimate"])
    i = rep["integrity"]
    assert i["n_participants"] == 45 and i["gamma_relative_sd_of_blueprint_model_c"] == GAMMA and i["same_folds"] and i["same_labels"]
    assert i["fold_assignment_sha256"] == reps["c_bp"]["manifest"]["fold_assignment_sha256"] and i["seed_for_folds"] == 0
    assert i["blueprint_pooled_fallbacks"] == {"b_bp": 0, "c_bp": 0}
    assert "second-named minus first-named" in rep["_status"] and "inconclusive" in rep["interpretation_limits"]


def test_point_estimates_are_recomputed_exactly_from_the_forecasts(run):
    frames, reps = arms(run)
    rep = prior_comparison_report(frames, reps, n_boot=30, seed=0)
    f = {a: df.sort_values("event_id").reset_index(drop=True) for a, df in frames.items()}
    brier = {a: float(((f[a]["p"] - f[a]["y"]) ** 2).mean()) for a in ARMS}
    mae = {a: float((f[a]["mean_rise"] - f[a]["rise"]).abs().mean()) for a in ARMS}
    c = rep["contrasts"]
    assert c["model_b_blueprint_minus_empirical_bayes"]["brier"]["estimate"] == pytest.approx(brier["b_bp"] - brier["b_eb"])
    assert c["model_c_blueprint_minus_empirical_bayes"]["rise_mae_mg_dl"]["estimate"] == pytest.approx(mae["c_bp"] - mae["c_eb"])
    assert c["c_minus_b_under_empirical_bayes"]["brier"]["estimate"] == pytest.approx(brier["c_eb"] - brier["b_eb"])
    assert c["c_minus_b_under_blueprint"]["brier"]["estimate"] == pytest.approx(brier["c_bp"] - brier["b_bp"])
    assert c["change_in_c_minus_b_contrast_blueprint_minus_empirical_bayes"]["brier"]["estimate"] == pytest.approx(
        (brier["c_bp"] - brier["b_bp"]) - (brier["c_eb"] - brier["b_eb"]))
    assert c["change_in_c_minus_b_contrast_blueprint_minus_empirical_bayes"]["brier"]["estimate"] == pytest.approx(
        c["model_c_blueprint_minus_empirical_bayes"]["brier"]["estimate"] - c["model_b_blueprint_minus_empirical_bayes"]["brier"]["estimate"])
    # consistent with the existing (unmodified) two-model B-versus-C report under the primary prior
    old = paired_report(frames["b_eb"], frames["c_eb"], n_boot=20)["metrics"]
    assert c["c_minus_b_under_empirical_bayes"]["log_loss"]["estimate"] == pytest.approx(old["log_loss"]["difference_c_minus_b"])
    assert c["c_minus_b_under_empirical_bayes"]["ece10"]["estimate"] == pytest.approx(old["ece10"]["difference_c_minus_b"])


def test_the_two_priors_really_differ_and_the_report_is_reproducible(run):
    frames, reps = arms(run)
    a = prior_comparison_report(frames, reps, n_boot=60, seed=3)
    b = prior_comparison_report(frames, reps, n_boot=60, seed=3)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    assert not np.allclose(frames["c_eb"].sort_values("event_id")["p"], frames["c_bp"].sort_values("event_id")["p"])
    assert a["contrasts"]["model_c_blueprint_minus_empirical_bayes"]["brier"]["estimate"] != 0.0


# ------------------------------------------------------------------ refusals

def _mut_frame(arm, fn):
    def f(frames, reps):
        fn(frames[arm])
    return f


def _mut_manifest(arm, fn):
    def f(frames, reps):
        fn(reps[arm]["manifest"])
    return f


def _split_participant(df):
    pid = df["participant_id"].iloc[0]
    idx = df.index[df["participant_id"] == pid]
    df.loc[idx[:2], "fold"] = (df.loc[idx[0], "fold"] + 1) % 5


def _move_participant(df):
    pid = df["participant_id"].iloc[0]
    df.loc[df["participant_id"] == pid, "fold"] = (df.loc[df["participant_id"] == pid, "fold"] + 1) % 5


REFUSALS = {
    "event_missing": (lambda fr, rp: fr.__setitem__("b_bp", fr["b_bp"].iloc[1:]), "does not hold the same events"),
    "event_renamed": (_mut_frame("c_bp", lambda d: d.__setitem__("event_id", d["event_id"].where(d.index != 0, "zzz"))), "does not hold the same events"),
    "participant_swapped": (_mut_frame("b_eb", lambda d: d.__setitem__("participant_id", d["participant_id"].where(d.index != 0, "CGMacros-999"))), "different participants"),
    "label_changed": (_mut_frame("c_eb", lambda d: d.__setitem__("y", d["y"].where(d.index != 0, 1 - d["y"].iloc[0]))), "labels differ"),
    "rise_changed": (_mut_frame("b_bp", lambda d: d.__setitem__("rise", d["rise"].where(d.index != 0, d["rise"].iloc[0] + 5))), "rises differ"),
    "participant_in_two_folds": (_mut_frame("c_bp", _split_participant), "more than one fold"),
    "participant_moved_fold": (_mut_frame("b_bp", _move_participant), "different folds"),
    "personal_count_changed": (_mut_frame("c_bp", lambda d: d.__setitem__("n_personal_before", d["n_personal_before"].where(d.index != 3, d["n_personal_before"].iloc[3] + 1))),
                               "personal-observation counts differ"),
    "duplicate_event": (_mut_frame("b_eb", lambda d: d.__setitem__("event_id", d["event_id"].where(d.index != 1, d["event_id"].iloc[0]))), "duplicated"),
    "nan_forecast": (_mut_frame("c_eb", lambda d: d.__setitem__("p", d["p"].where(d.index != 0, np.nan))), "non-finite"),
    "probability_out_of_range": (_mut_frame("b_bp", lambda d: d.__setitem__("p", d["p"].where(d.index != 0, 1.4))), "outside"),
    "label_not_binary": (_mut_frame("c_bp", lambda d: d.__setitem__("y", d["y"].where(d.index != 0, 2))), "not 0 or 1"),
    "column_missing": (_mut_frame("c_bp", lambda d: d.drop(columns=["fold"], inplace=True)), "missing columns"),
    "scheme_wrong_b_bp": (_mut_manifest("b_bp", lambda m: m["prior"].__setitem__("scheme", "empirical_bayes")), "prior scheme"),
    "scheme_wrong_c_eb": (_mut_manifest("c_eb", lambda m: m["prior"].__setitem__("scheme", "blueprint")), "prior scheme"),
    "no_prior_metadata": (_mut_manifest("c_bp", lambda m: m.pop("prior")), "no prior metadata"),
    "not_training_only": (_mut_manifest("c_bp", lambda m: m["prior"].__setitem__("fitted_on", "all participants")), "training folds only"),
    "gamma_on_b_arm": (_mut_manifest("b_bp", lambda m: m["prior"].__setitem__("gamma_relative_sd", 0.5)), "has none"),
    "gamma_missing": (_mut_manifest("c_bp", lambda m: m["prior"].__setitem__("gamma_relative_sd", None)), "must be one of"),
    "gamma_off_grid": (_mut_manifest("c_bp", lambda m: m["prior"].__setitem__("gamma_relative_sd", 0.3)), "must be one of"),
    "prior_count_wrong": (_mut_manifest("c_bp", lambda m: m["prior"].__setitem__("n_participant_priors", 44)), "participant priors"),
    "model_swapped": (_mut_manifest("c_eb", lambda m: m.__setitem__("model", "B: personalised")), "not a Model C run"),
    "b_not_activity_eligible": (_mut_manifest("b_eb", lambda m: m.__setitem__("population", "core-eligible events")), "activity-eligible"),
    "fold_hash_differs": (_mut_manifest("b_bp", lambda m: m.__setitem__("fold_assignment_sha256", "0" * 64)), "fold hash"),
    "seed_differs": (_mut_manifest("c_bp", lambda m: m.__setitem__("seed_for_folds", 1)), "fold seed"),
    "channel_differs": (_mut_manifest("c_bp", lambda m: m.__setitem__("cgm_channel", "Dexcom GL")), "CGM channel"),
    "table_hash_differs": (_mut_manifest("b_eb", lambda m: m.__setitem__("event_table_file_sha256", "1" * 64)), "event table file hash"),
    "table_settings_differ": (_mut_manifest("c_eb", lambda m: m.__setitem__("event_table_settings", {"channel": "Libre GL", "max_cgm_gap_minutes": 30})), "event table settings"),
    "table_hash_missing": (_mut_manifest("c_bp", lambda m: m.pop("event_table_file_sha256")), "no event table file hash"),
    "report_event_count_wrong": (lambda fr, rp: rp["b_bp"]["data"].__setitem__("n_events", 5), "counts 5 events"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_mismatched_or_inconsistent_arms_are_refused_with_a_clear_error(run, case):
    mutate, text = REFUSALS[case]
    frames, reps = arms(run)
    frames, reps = {k: v.copy() for k, v in frames.items()}, copy.deepcopy(reps)
    mutate(frames, reps)
    with pytest.raises(PriorComparisonError, match=text):
        validate_prior_arms(frames, reps)
    with pytest.raises(PriorComparisonError):
        prior_comparison_report(frames, reps, n_boot=10)                       # the report itself refuses, not only the validator


def test_expected_counts_and_expected_gamma_are_enforced(run):
    frames, reps = arms(run)
    with pytest.raises(PriorComparisonError, match="expected 963 events"):
        validate_prior_arms(frames, reps, expected_events=963)
    with pytest.raises(PriorComparisonError, match="expected 34 participants"):
        validate_prior_arms(frames, reps, expected_participants=34)
    with pytest.raises(PriorComparisonError, match="expected 0.5"):
        validate_prior_arms(frames, reps, expected_gamma=0.5)
    assert validate_prior_arms(frames, reps, expected_gamma=GAMMA)["n_events"] == len(frames["c_eb"])


def test_missing_arms_are_refused_and_nothing_is_aligned_or_dropped(run):
    frames, reps = arms(run)
    with pytest.raises(PriorComparisonError, match="four arms"):
        validate_prior_arms({k: v for k, v in frames.items() if k != "c_bp"}, reps)
    shuffled = {k: v.sample(frac=1, random_state=1).reset_index(drop=True) for k, v in frames.items()}
    assert validate_prior_arms(shuffled, reps)["n_events"] == len(frames["c_eb"])          # row ORDER does not matter; identity does
    short = {k: v.copy() for k, v in frames.items()}
    short["b_eb"] = short["b_eb"].iloc[:-1]
    with pytest.raises(PriorComparisonError):
        validate_prior_arms(short, reps)                                                      # a missing forecast is an error, not a silent drop


def test_zero_padded_and_integer_participant_ids_are_not_silently_equated(run):
    frames, reps = arms(run)
    frames = {k: v.copy() for k, v in frames.items()}
    frames["b_bp"]["participant_id"] = frames["b_bp"]["participant_id"].str[-3:].astype(int)
    frames["c_bp"]["participant_id"] = frames["c_bp"]["participant_id"].str[-3:].astype(int)
    for k in ("b_eb", "c_eb"):
        frames[k]["participant_id"] = frames[k]["participant_id"].str[-3:]
    with pytest.raises(PriorComparisonError, match="different participants"):                   # "007" vs 7 are NOT silently equated (zero-padding is data)
        validate_prior_arms(frames, reps)


# ------------------------------------------------------------------ the prespecified screen

def _contrasts(b, c):
    def row(brier, ll, ece):
        mk = lambda ci: {"estimate": float(np.mean(ci)), "ci95": list(ci), "ci_excludes_zero": bool(ci[0] > 0 or ci[1] < 0)}
        return {"brier": mk(brier), "log_loss": mk(ll), "ece10": mk(ece), "ece5": mk(ece), "rise_mae_mg_dl": mk((-1, 1))}
    return {"model_b_blueprint_minus_empirical_bayes": row(*b), "model_c_blueprint_minus_empirical_bayes": row(*c)}


def test_the_screen_requires_both_models_and_all_three_criteria():
    good = ((-0.02, -0.001), (-0.05, -0.01), (-0.01, 0.01))
    assert adoption_screen(_contrasts(good, good))["candidate_default_for_human_review"] is True
    straddle = ((-0.02, 0.001), (-0.05, -0.01), (-0.01, 0.01))
    assert adoption_screen(_contrasts(good, straddle))["candidate_default_for_human_review"] is False            # Brier interval contains 0 for C
    worse_cal = ((-0.02, -0.001), (-0.05, -0.01), (0.001, 0.02))
    s = adoption_screen(_contrasts(worse_cal, good))
    assert s["candidate_default_for_human_review"] is False and s["model_b"]["ece10_interval_not_entirely_above_zero"] is False
    assert adoption_screen(_contrasts(good, good))["model_c"]["all_met"] and "does not show" in adoption_screen(_contrasts(straddle, straddle))["meaning"]
    only_ll = ((-0.02, -0.001), (-0.05, 0.01), (-0.01, 0.01))
    assert adoption_screen(_contrasts(only_ll, good))["model_b"]["log_loss_interval_entirely_below_zero"] is False


def test_the_report_screen_follows_the_intervals_and_changes_no_default(run):
    frames, reps = arms(run)
    rep = prior_comparison_report(frames, reps, n_boot=60, seed=0)
    s = rep["adoption_screen"]
    assert s["rule"] == DECISION_RULE_TEXT and "PRESPECIFIED" in s["rule"] and "not establish superiority" in s["rule"] and "not establish equivalence" in s["rule"]
    c = rep["contrasts"]
    assert s["model_c"]["brier_interval_entirely_below_zero"] == bool(c["model_c_blueprint_minus_empirical_bayes"]["brier"]["ci95"][1] < 0)
    assert ps.DEFAULT_SCHEME == "empirical_bayes"
    assert "best-looking width is never selected" in s["rule"]


# ------------------------------------------------------------------ script: exit codes, privacy, no overwrite

def test_script_end_to_end_is_aggregate_only_and_never_touches_the_inputs(run, capsys):
    mod = _load("compare_priors")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in list(run["paths"].values()) + list(run["reports"].values()) + [run["table"]]}
    names_before = sorted(p.name for p in run["out"].iterdir())
    rep = run["tmp"] / "prior_comparison.json"
    assert mod.main(script_args(run) + ["--n-boot", "40", "--expect-participants", "45", "--expect-gamma", "1", "--report-out", str(rep)]) == 0
    shown = capsys.readouterr().out
    assert json.loads(shown)["integrity"]["gamma_relative_sd_of_blueprint_model_c"] == 1.0 and json.loads(rep.read_text()) == json.loads(shown)
    assert "CGMacros-" not in shown and "2000-01-01" not in shown
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before             # every input byte-identical
    assert sorted(p.name for p in run["out"].iterdir()) == names_before                         # nothing new beside the model outputs


def test_script_exit_codes_and_no_report_on_refusal(run, capsys, tmp_path):
    mod = _load("compare_priors")
    rep = tmp_path / "r.json"
    assert mod.main(script_args(run) + ["--report-out", str(run["paths"]["c_eb"])]) == 2         # would overwrite an input
    assert mod.main(script_args(run) + ["--report-out", str(run["reports"]["b_bp"])]) == 2
    args = script_args(run)
    args[args.index("--b-eb") + 1] = str(tmp_path / "missing.csv")
    assert mod.main(args + ["--report-out", str(rep)]) == 2
    assert mod.main(script_args(run) + ["--expect-gamma", "0.5", "--report-out", str(rep)]) == 3   # wrong gamma
    assert not rep.exists()
    bad = tmp_path / "bad_c_bp.csv"
    df = pd.read_csv(run["paths"]["c_bp"]); df.loc[0, "y"] = 1 - df.loc[0, "y"]; df.to_csv(bad, index=False)
    args = script_args(run); args[args.index("--c-bp") + 1] = str(bad)
    assert mod.main(args + ["--report-out", str(rep)]) == 3 and not rep.exists()
    assert "REFUSED" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        mod.main(["--b-eb", "x"])                                                                  # all eight inputs are required


# ------------------------------------------------------------------ training-only priors and the primary protocol

def test_prior_only_forecasts_of_a_participant_do_not_depend_on_their_own_outcomes_under_either_scheme():
    from glycotwin.models import model_a_cv as ma, model_b_cv as mb, model_c_cv as mc
    groups, ev = cohort(), make_events(per=8, seed=2)
    folds = ma.make_participant_folds(groups, seed=0)
    victim = "CGMacros-030"
    changed = ev.copy()
    m = changed["participant_id"] == victim
    changed.loc[m, "peak_glucose_rise"] = changed.loc[m, "peak_glucose_rise"] * 8 + 500
    changed.loc[m, "label_exceeds_180"] = (changed.loc[m, "baseline_glucose"] + changed.loc[m, "peak_glucose_rise"] >= 180).astype(int)
    for mod in (mb, mc):
        for kw in ({}, {"prior_scheme": "blueprint", "group_of": groups}):
            a, _, _ = mod.cross_validated_sequential(ev, folds, **kw)
            b, _, _ = mod.cross_validated_sequential(changed, folds, **kw)
            va, vb = a[a["participant_id"] == victim].sort_values("order"), b[b["participant_id"] == victim].sort_values("order")
            assert np.array_equal(va["p_frozen_prior"].to_numpy(), vb["p_frozen_prior"].to_numpy())      # the prior itself
            assert va["p"].iloc[0] == vb["p"].iloc[0]                                                    # first forecast = prior only


def test_the_primary_empirical_bayes_arms_are_exactly_what_the_default_runners_produce(run):
    frames, reps = arms(run)
    for arm, model in (("b_eb", "B"), ("c_eb", "C")):
        assert reps[arm]["manifest"]["prior"]["scheme"] == "empirical_bayes" and reps[arm]["manifest"]["protocol_arguments"]["prior_scheme"] == "empirical_bayes"
        assert reps[arm]["manifest"]["event_table_file_sha256"] == hashlib.sha256(run["table"].read_bytes()).hexdigest()


# ------------------------------------------------------------------ documentation

def test_the_decision_rule_is_documented_as_a_prespecified_screen_not_proof():
    doc = (ROOT / "docs" / "prior_comparison.md").read_text(encoding="utf-8")
    assert DECISION_RULE_TEXT in doc or "PRESPECIFIED SCREEN" in doc
    for needle in ("not proof", "opt-in", "empirical-Bayes", "gamma", "second-named minus first-named", "training fold"):
        assert needle.lower() in doc.lower(), needle


def test_the_intervals_come_from_resampling_participants_and_depend_on_the_seed(run):
    frames, reps = arms(run)
    a = prior_comparison_report(frames, reps, n_boot=200, seed=0)
    b = prior_comparison_report(frames, reps, n_boot=200, seed=1)
    for name in CONTRASTS:
        for m in METRICS:
            lo, hi = a["contrasts"][name][m]["ci95"]
            assert hi > lo, (name, m)                                            # a real resampling distribution, not a point
    assert a["contrasts"]["c_minus_b_under_blueprint"]["brier"]["ci95"] != b["contrasts"]["c_minus_b_under_blueprint"]["brier"]["ci95"]
    assert a["bootstrap"]["n_participants_resampled"] == 45 and a["bootstrap"]["n_boot"] == 200
    # every bootstrap draw keeps a participant's events together: the interval of a participant-level quantity is wider than an event-level resampling would give
    y = frames["c_eb"].sort_values("event_id")
    d = ((frames["c_bp"].sort_values("event_id")["p"] - y["y"]) ** 2).to_numpy() - ((y["p"] - y["y"]) ** 2).to_numpy()
    rng = np.random.default_rng(0)
    event_level = np.quantile([d[rng.integers(0, len(d), len(d))].mean() for _ in range(300)], [0.025, 0.975])
    lo, hi = a["contrasts"]["model_c_blueprint_minus_empirical_bayes"]["brier"]["ci95"]
    assert (hi - lo) >= 0.5 * (event_level[1] - event_level[0])
