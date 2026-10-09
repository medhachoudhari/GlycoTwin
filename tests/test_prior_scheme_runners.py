"""Prior-scheme option of the Model B / Model C research runners (sensitivity analyses S2/S3). SYNTHETIC data only: these tests check the
mechanics, leakage safeguards and preservation of the primary (empirical-Bayes) results, not that either prior is better on real data."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.models import model_a_cv as ma
from glycotwin.models import model_b_cv as mb
from glycotwin.models import model_c_cv as mc
from glycotwin.models import prior_schemes as ps
from glycotwin.models.blueprint_prior import fit_blueprint_prior
from test_model_c_cv import cohort, make_events

ROOT = Path(__file__).resolve().parents[1]
GROUPS = cohort()


def sha(df):
    return hashlib.sha256(df.sort_values("event_id").round(12).to_csv(index=False).encode()).hexdigest()


def jhash(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()


@pytest.fixture(scope="module")
def ev():
    return make_events(per=12, seed=4)


@pytest.fixture(scope="module")
def folds():
    return ma.make_participant_folds(GROUPS, seed=0)


# ------------------------------------------------------------------ the primary protocol is preserved exactly

# Hashes of the PRE-CHANGE code's outputs on this seeded synthetic dataset (recorded before the option was added).
GOLDEN = {"B_oof": "fcf9c331bfd7fa2605394ba55d436567753d2d2ac1bc943f4b483796e66fe36c", "C_oof": "5e752323ca64253fe113f394a2cbcc5ff6647bd9c73980943db18df16752edc1",
          "B_overall": "73f4a1cc561f6b48e75717cf0691d90fa2c50811c6d6fca50e9521babfeaa3b3", "C_overall": "c3abd916d549c541328c57fbed1a487b065aee80055cf27c7e10f91a0dd2d8f4",
          "B_pers": "ef21df62519f4018aa2b89a5627c5dea01d4fd6c00639f19628c1ac41338bb28", "C_pers": "dec04bdb0ff6920d2b97dee26bf3ddb6a76e839b2109a17cd480a9e80ef367a2"}


def test_default_runs_reproduce_the_results_recorded_before_the_option_existed(ev, folds):
    ob, _, _ = mb.cross_validated_sequential(ev, folds)
    oc, _, _ = mc.cross_validated_sequential(ev, folds)
    assert sha(ob) == GOLDEN["B_oof"] and sha(oc) == GOLDEN["C_oof"]
    rb, *_ = mb.run_model_b(ev, GROUPS, seed=0, n_boot=20)
    rc, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=20)
    assert jhash(rb["model_b_overall"]) == GOLDEN["B_overall"] and jhash(rc["model_c_overall"]) == GOLDEN["C_overall"]
    assert jhash(rb["personalization"]) == GOLDEN["B_pers"] and jhash(rc["personalization"]) == GOLDEN["C_pers"]


def test_explicit_empirical_bayes_equals_the_default(ev, folds):
    d, _, _ = mc.cross_validated_sequential(ev, folds)
    e, _, _ = mc.cross_validated_sequential(ev, folds, prior_scheme="empirical_bayes")
    assert sha(d) == sha(e)
    d, _, _ = mb.cross_validated_sequential(ev, folds)
    e, _, _ = mb.cross_validated_sequential(ev, folds, prior_scheme="empirical_bayes")
    assert sha(d) == sha(e)


def test_the_blueprint_scheme_changes_the_prior_but_not_the_events_folds_or_columns(ev, folds):
    base, _, _ = mc.cross_validated_sequential(ev, folds)
    bp, _, _ = mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    assert list(base.columns) == list(bp.columns) and set(base["event_id"]) == set(bp["event_id"])
    m = base.set_index("event_id").join(bp.set_index("event_id"), rsuffix="_bp")
    assert (m["fold"] == m["fold_bp"]).all() and (m["y"] == m["y_bp"]).all() and (m["rise"] == m["rise_bp"]).all()
    assert not np.allclose(m["p"], m["p_bp"])                                              # the prior really differs


# ------------------------------------------------------------------ option validation

@pytest.mark.parametrize("model, scheme, width, ok", [
    ("B", "empirical_bayes", None, ("empirical_bayes", None)), ("B", "blueprint", None, ("blueprint", None)),
    ("C", "empirical_bayes", None, ("empirical_bayes", None)), ("C", "blueprint", None, ("blueprint", 0.5)),
    ("C", "blueprint", 0.25, ("blueprint", 0.25)), ("C", "blueprint", 1, ("blueprint", 1.0)), ("C", "blueprint", 2.0, ("blueprint", 2.0))])
def test_valid_option_combinations(model, scheme, width, ok):
    assert ps.validate_prior_options(model, scheme, width) == ok


@pytest.mark.parametrize("model, scheme, width", [("B", "blueprint", 0.5), ("B", "empirical_bayes", 1.0), ("C", "empirical_bayes", 0.5),
                                                  ("C", "blueprint", 0.3), ("C", "blueprint", 0), ("C", "blueprint", -1), ("C", "stratified", None),
                                                  ("B", "", None), ("D", "blueprint", None)])
def test_invalid_option_combinations_are_refused_not_ignored(model, scheme, width):
    with pytest.raises(ValueError):
        ps.validate_prior_options(model, scheme, width)


def test_runners_refuse_bad_options_and_a_missing_group_map(ev, folds):
    with pytest.raises(ValueError):
        mc.run_model_c(ev, GROUPS, prior_scheme="empirical_bayes", gamma_relative_sd=0.5, n_boot=5)
    with pytest.raises(ValueError):
        mc.run_model_c(ev, GROUPS, prior_scheme="blueprint", gamma_relative_sd=0.7, n_boot=5)
    with pytest.raises(ValueError):
        mb.run_model_b(ev, GROUPS, prior_scheme="nope", n_boot=5)
    with pytest.raises(ValueError, match="group_of"):
        mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint")
    with pytest.raises(ValueError, match="group_of"):
        mb.cross_validated_sequential(ev, folds, prior_scheme="blueprint")
    partial = {k: v for k, v in GROUPS.items() if k != "CGMacros-010"}
    with pytest.raises(ValueError, match="no glycaemic group"):
        mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=partial)


# ------------------------------------------------------------------ leakage

def _first_prior_beta(trajs, pid, model):
    t = trajs[pid]["trajectory"][0]
    return (t["sens_mean"], t["sens_sd"]) if model == "B" else (t["beta_mean"], t["beta_sd"], t["gamma_mean"], t["gamma_sd"])


@pytest.mark.parametrize("model", ["B", "C"])
def test_held_out_outcomes_never_reach_their_own_or_their_foldmates_priors(ev, folds, model):
    mod = mb if model == "B" else mc
    kw = {"prior_scheme": "blueprint", "group_of": GROUPS}
    base, trajs, _ = mod.cross_validated_sequential(ev, folds, **kw)
    victim = "CGMacros-020"
    fold = folds[victim]
    changed = ev.copy()
    m = changed["participant_id"] == victim
    changed.loc[m, "peak_glucose_rise"] = changed.loc[m, "peak_glucose_rise"] * 6 + 400
    changed.loc[m, "label_exceeds_180"] = (changed.loc[m, "baseline_glucose"] + changed.loc[m, "peak_glucose_rise"] >= 180).astype(int)
    pert, trajs2, _ = mod.cross_validated_sequential(changed, folds, **kw)
    b, p = base.set_index("event_id"), pert.set_index("event_id")
    mates = [q for q in ev["participant_id"].unique() if folds[q] == fold and q != victim]
    assert mates
    mate_ids = ev.loc[ev["participant_id"].isin(mates), "event_id"]
    for col in ("p", "mean_rise", "p_frozen_prior", "mean_rise_frozen_prior", "interval90_low", "interval90_high"):
        assert np.array_equal(b.loc[mate_ids, col].to_numpy(), p.loc[mate_ids, col].to_numpy()), col       # same-fold participants: untouched
    v_ids = ev.loc[ev["participant_id"] == victim, "event_id"]
    assert np.array_equal(b.loc[v_ids, "p_frozen_prior"].to_numpy(), p.loc[v_ids, "p_frozen_prior"].to_numpy())   # the victim's own prior: untouched
    assert _first_prior_beta(trajs, victim, model) == _first_prior_beta(trajs2, victim, model)
    first = b.loc[v_ids].sort_values("order").index[0]
    assert b.loc[first, "p"] == p.loc[first, "p"]                                                                  # first forecast uses the prior only
    later = b.loc[v_ids].sort_values("order").index[-1]
    assert b.loc[later, "p"] != p.loc[later, "p"]                                                                  # later forecasts do learn from the person's own outcomes


@pytest.mark.parametrize("model", ["B", "C"])
def test_the_stratum_prior_equals_the_prior_fitted_on_that_groups_training_participants_only(ev, folds, model):
    mod = mb if model == "B" else mc
    _, trajs, _ = mod.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    for victim in ("CGMacros-003", "CGMacros-020", "CGMacros-040"):                                              # one per glycaemic group
        train = ev[ev["participant_id"].map(folds) != folds[victim]]
        tg = ps.with_group(train, GROUPS)
        _, _, d = fit_blueprint_prior(tg, glycaemic_group=GROUPS[victim])
        assert d["group_used"] == GROUPS[victim]
        ref = _first_prior_beta(trajs, victim, model)
        assert ref[0] == pytest.approx(d["beta_prior_mean"], abs=1e-12) and ref[1] == pytest.approx(d["beta_prior_sd"], abs=1e-12)
        sub = tg[tg["glycaemic_group"] == GROUPS[victim]]
        assert d["n_stratum_participants"] == sub["participant_id"].nunique() and victim not in set(sub["participant_id"])


def test_outcomes_of_other_groups_do_not_move_the_stratified_beta_prior(ev, folds):
    victim = "CGMacros-003"                                                  # healthy
    _, t1, _ = mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    changed = ev.copy()
    other = changed["participant_id"].map(GROUPS) == "t2d"
    changed.loc[other, "peak_glucose_rise"] = changed.loc[other, "peak_glucose_rise"] * 3 + 100
    _, t2, _ = mc.cross_validated_sequential(changed, folds, prior_scheme="blueprint", group_of=GROUPS)
    a, b = _first_prior_beta(t1, victim, "C"), _first_prior_beta(t2, victim, "C")
    assert a[0] == b[0] and a[1] == b[1]                                      # beta prior mean and sd come from the healthy stratum only
    assert a[2] == b[2] == 0.0                                                # gamma prior mean is 0 in both


def test_the_group_label_selects_the_stratum_and_nothing_else(ev, folds):
    train = ps.with_group(ev[ev["participant_id"].map(folds) != 0], GROUPS)
    held = "CGMacros-001"
    p_h, d_h = ps.blueprint_prior_for_participant(train[train["participant_id"] != held], held, "healthy", "C", None)
    p_t, d_t = ps.blueprint_prior_for_participant(train[train["participant_id"] != held], held, "t2d", "C", None)
    assert d_h["group_used"] == "healthy" and d_t["group_used"] == "t2d" and p_h.mean[0] != p_t.mean[0]
    assert d_h["noise_sd_model_c"] == d_t["noise_sd_model_c"]               # noise is pooled over the whole training fold, not group-specific


def test_the_held_out_participant_inside_the_training_rows_is_refused(ev, folds):
    tg = ps.with_group(ev, GROUPS)                                           # ALL participants, including the one held out
    with pytest.raises(AssertionError, match="held-out participant"):
        ps.blueprint_prior_for_participant(tg, "CGMacros-001", "healthy", "C", None)


def test_small_strata_fall_back_to_the_pooled_training_fold_and_are_counted():
    sizes = {"healthy": 15, "pre-diabetes": 16, "t2d": 5}
    groups, k = {}, 1
    for name, n in sizes.items():
        for _ in range(n):
            groups[f"CGMacros-{k:03d}"] = name
            k += 1
    full = make_events(per=10, seed=6)
    ev = full[full["participant_id"].isin(groups)]
    f = ma.make_participant_folds(groups, seed=0)
    oof, trajs, priors = mc.cross_validated_sequential(ev, f, prior_scheme="blueprint", group_of=groups)
    summ = [t["prior_summary"] for t in trajs.values()]
    t2d_fallbacks = [s for s, p in zip(summ, trajs) if groups[p] == "t2d"]
    assert len(t2d_fallbacks) == 5 and all(s["group_used"] is None and "only" in s["fallback_reason"] for s in t2d_fallbacks)
    assert sum(s["group_used"] is None for s in summ) == 5                   # healthy and pre-diabetes strata are large enough
    assert sum(priors[k_]["n_pooled_fallbacks"] for k_ in priors) == 5
    rep, *_ = mc.run_model_c(ev, groups, seed=0, n_boot=10, prior_scheme="blueprint")
    assert rep["manifest"]["prior"]["n_pooled_fallbacks"] == 5 and rep["manifest"]["prior"]["fallback_reasons"]


# ------------------------------------------------------------------ fold integrity and reproducibility

def test_folds_are_identical_across_schemes_and_participants_stay_in_one_fold(ev, folds):
    reports = {}
    for scheme in ("empirical_bayes", "blueprint"):
        rb, ob, *_ = mb.run_model_b(ev, GROUPS, seed=0, n_boot=10, prior_scheme=scheme)
        rc, oc, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=10, prior_scheme=scheme)
        reports[scheme] = (rb, rc)
        for o in (ob, oc):
            assert (o.groupby("participant_id")["fold"].nunique() == 1).all()
            assert o.groupby("participant_id")["fold"].first().to_dict() == {q: folds[q] for q in o["participant_id"].unique()}
    h = ma.fold_assignment_hash(folds)
    for scheme, (rb, rc) in reports.items():
        assert rb["manifest"]["fold_assignment_sha256"] == rc["manifest"]["fold_assignment_sha256"] == h


@pytest.mark.parametrize("width", [None, 0.25, 0.5, 1.0, 2.0])
def test_blueprint_runs_are_reproducible(ev, width):
    a, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint", gamma_relative_sd=width)
    b, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint", gamma_relative_sd=width)
    strip = lambda r: {k: v for k, v in r.items() if k != "manifest"}
    assert jhash(strip(a)) == jhash(strip(b))
    x, *_ = mb.run_model_b(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint")
    y, *_ = mb.run_model_b(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint")
    assert jhash({k: v for k, v in x.items() if k != "manifest"}) == jhash({k: v for k, v in y.items() if k != "manifest"})


# ------------------------------------------------------------------ gamma width options (Model C only)

def test_gamma_prior_sd_scales_with_the_prespecified_width_and_default_is_half(ev, folds):
    sd = {}
    for w in ps.GAMMA_WIDTHS:
        _, trajs, _ = mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS, gamma_relative_sd=w)
        t0 = trajs["CGMacros-020"]["trajectory"][0]
        sd[w] = t0["gamma_sd"]
        assert t0["gamma_mean"] == 0.0 and t0["beta_sd"] > 0
    assert sd[0.5] == pytest.approx(2 * sd[0.25]) and sd[1.0] == pytest.approx(2 * sd[0.5]) and sd[2.0] == pytest.approx(2 * sd[1.0])
    _, trajs, _ = mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    assert trajs["CGMacros-020"]["trajectory"][0]["gamma_sd"] == pytest.approx(sd[0.5])
    assert ps.GAMMA_WIDTHS == (0.25, 0.5, 1.0, 2.0)


def test_model_b_is_unaffected_by_anything_about_gamma(ev, folds):
    a, _, _ = mb.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    b, _, _ = mb.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    assert sha(a) == sha(b)
    assert "gamma" not in json.dumps(mb.run_model_b(ev, GROUPS, n_boot=5, prior_scheme="blueprint")[0]["manifest"]["prior"]).replace('"gamma_relative_sd": null', "")


# ------------------------------------------------------------------ manifests

REQUIRED_MANIFEST = ("seed_for_folds", "fold_assignment_sha256", "n_participants_in_folds", "cgm_channel", "git_commit", "working_tree_dirty", "prior",
                     "n_bootstrap")


def test_manifests_record_scheme_width_folds_seed_counts_and_code_revision(ev):
    rb, *_ = mb.run_model_b(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint", channel="Libre GL")
    rc, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint", gamma_relative_sd=2.0, channel="Libre GL")
    re_, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=10, channel="Libre GL")
    for r in (rb, rc, re_):
        for k in REQUIRED_MANIFEST:
            assert k in r["manifest"], k
        assert r["manifest"]["n_participants_in_folds"] == 45 and r["data"]["n_participants"] == 45 and r["manifest"]["seed_for_folds"] == 0
        assert r["manifest"]["cgm_channel"] == "Libre GL" and isinstance(r["manifest"]["working_tree_dirty"], (bool, type(None)))
    assert rb["manifest"]["prior"]["scheme"] == "blueprint" and rb["manifest"]["prior"]["gamma_relative_sd"] is None
    assert rc["manifest"]["prior"]["scheme"] == "blueprint" and rc["manifest"]["prior"]["gamma_relative_sd"] == 2.0
    assert rc["manifest"]["prior"]["n_participant_priors"] == 45 and "training folds only" in rc["manifest"]["prior"]["fitted_on"]
    assert re_["manifest"]["prior"]["scheme"] == "empirical_bayes" and re_["manifest"]["prior"]["gamma_relative_sd"] is None


def test_personalization_summaries_work_with_per_participant_priors(ev):
    rc, *_ = mc.run_model_c(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint")
    s = rc["personalization"]
    assert s["final_over_prior_sd_gamma"]["n"] == 45 and s["prior_across_folds"]["gamma_population_mean"]["mean"] == 0.0
    rb, *_ = mb.run_model_b(ev, GROUPS, seed=0, n_boot=10, prior_scheme="blueprint")
    assert rb["personalization"]["final_over_prior_sensitivity_sd"]["n"] == 45
    assert "CGMacros-" not in json.dumps(rc) and "CGMacros-" not in json.dumps(rb)                   # aggregate-only output is preserved


# ------------------------------------------------------------------ scripts: options, output names, no overwrite, sidecar

def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path):
    root = tmp_path / "ds"; root.mkdir()
    a1c = {"healthy": 5.2, "pre-diabetes": 6.0, "t2d": 7.1}
    pd.DataFrame({"subject": [int(p[-3:]) for p in GROUPS], "A1c PDL (Lab)": [a1c[v] for v in GROUPS.values()]}).to_csv(root / "bio.csv", index=False)
    table = tmp_path / "event_table_Libre_GL.csv"
    make_events(per=8).to_csv(table, index=False)
    return root, table


def test_scripts_name_variant_outputs_separately_and_never_overwrite_the_primary_run(tmp_path, capsys):
    rmb, rmc = _load("run_model_b"), _load("run_model_c")
    root, table = _tree(tmp_path)
    out = tmp_path / "out"
    base = ["--data-root", str(root), "--event-table", str(table), "--n-boot", "10", "--out-dir", str(out)]
    assert rmb.main(base + ["--population", "activity-eligible"]) == 0 and rmc.main(base) == 0
    capsys.readouterr()
    primary = {p.name: p.read_bytes() for p in out.iterdir()}
    assert rmb.main(base + ["--population", "activity-eligible", "--prior-scheme", "blueprint"]) == 0
    assert rmc.main(base + ["--prior-scheme", "blueprint", "--gamma-relative-sd", "0.25"]) == 0
    assert rmc.main(base + ["--prior-scheme", "blueprint"]) == 0
    reps = capsys.readouterr().out
    for name, content in primary.items():
        assert (out / name).read_bytes() == content, name                                       # primary files byte-identical
    names = sorted(p.name for p in out.iterdir())
    assert "model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv" in names
    assert "model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma0.25.csv" in names
    assert "model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma0.5.csv" in names
    assert "CGMacros-" not in reps
    # the variant B file still satisfies the comparison script's naming rule and pairs with a variant C on the same events
    fb = pd.read_csv(out / "model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv")
    fc = pd.read_csv(out / "model_c_sequential_forecasts_Libre_GL_prior-blueprint_gamma0.5.csv")
    assert "activity_eligible" in "model_b_sequential_forecasts_Libre_GL_activity_eligible_prior-blueprint.csv" and set(fb["event_id"]) == set(fc["event_id"])


def test_script_option_validation(tmp_path, capsys):
    rmb, rmc = _load("run_model_b"), _load("run_model_c")
    root, table = _tree(tmp_path)
    base = ["--data-root", str(root), "--event-table", str(table), "--n-boot", "5", "--out-dir", str(tmp_path / "o")]
    with pytest.raises(SystemExit):
        rmc.main(base + ["--prior-scheme", "blueprint", "--gamma-relative-sd", "0.3"])            # not a prespecified width
    with pytest.raises(SystemExit):
        rmb.main(base + ["--prior-scheme", "stratified"])
    with pytest.raises(SystemExit):
        rmb.main(base + ["--gamma-relative-sd", "0.5"])                                          # Model B has no such option
    assert rmc.main(base + ["--gamma-relative-sd", "0.5"]) == 2                                   # width without the blueprint scheme
    assert "applies only to the blueprint prior" in capsys.readouterr().err


def test_event_table_settings_are_recorded_in_every_manifest_and_unknown_when_absent(tmp_path, capsys):
    rma, rmb, rmc = _load("run_model_a"), _load("run_model_b"), _load("run_model_c")
    root, table = _tree(tmp_path)
    out = tmp_path / "o"
    base = ["--data-root", str(root), "--event-table", str(table), "--n-boot", "5"]
    rmb.main(base + ["--out-dir", str(out)]); r_unknown = json.loads(capsys.readouterr().out)
    assert r_unknown["manifest"]["event_table_settings"]["status"].startswith("UNKNOWN")
    assert r_unknown["manifest"]["event_table_file_sha256"] == hashlib.sha256(table.read_bytes()).hexdigest()
    settings = {"channel": "Libre GL", "max_cgm_gap_minutes": 15, "require_isolated": True, "outcome_window_minutes": 120.0, "label_threshold_mg_dl": 180.0}
    ps.settings_sidecar_path(table).write_text(json.dumps(settings))
    rma.main(base + ["--report-out", str(tmp_path / "a.json"), "--oof-out", str(tmp_path / "a.csv"), "--folds-out", str(tmp_path / "f.json")]); ra = json.loads(capsys.readouterr().out)
    rmb.main(base + ["--out-dir", str(out)]); rb = json.loads(capsys.readouterr().out)
    rmc.main(base + ["--out-dir", str(out)]); rc = json.loads(capsys.readouterr().out)
    for r in (ra, rb, rc):
        assert r["manifest"]["event_table_settings"] == settings and r["manifest"]["protocol_arguments"]["channel"] == "Libre GL"
        assert r["manifest"]["event_table_file_sha256"] == hashlib.sha256(table.read_bytes()).hexdigest()
    assert ra["manifest"]["fold_assignment_sha256"] == rb["manifest"]["fold_assignment_sha256"] == rc["manifest"]["fold_assignment_sha256"]
    assert rc["manifest"]["protocol_arguments"]["prior_scheme"] == "empirical_bayes" and rc["manifest"]["protocol_arguments"]["seed"] == 0


def test_build_event_table_writes_a_settings_sidecar_next_to_the_table(tmp_path, capsys):
    from test_build_event_table_script import _tree as make_tree, bet
    root = tmp_path / "ds"; make_tree(root)
    table = tmp_path / "t" / "event_table_Libre_GL.csv"
    assert bet.main(["--data-root", str(root), "--channel", "Libre GL", "--max-gap-minutes", "30", "--table-out", str(table),
                     "--report-out", str(tmp_path / "r.json")]) == 0
    capsys.readouterr()
    side = json.loads(ps.settings_sidecar_path(table).read_text())
    assert side["channel"] == "Libre GL" and side["max_cgm_gap_minutes"] == 30 and side["require_isolated"] is True
    assert side["outcome_window_minutes"] == 120.0 and side["label_threshold_mg_dl"] == 180.0 and "Meal Type row" in side["event_definition"]
    assert ps.event_table_info(table)["event_table_settings"] == side
    assert "CGMacros-" not in json.dumps(side)


# ------------------------------------------------------------------ the summaries compare each person with THEIR OWN prior (pinned by the mutation checks)

def test_personalisation_summaries_use_each_participants_own_prior_under_the_blueprint_scheme(ev, folds):
    oof, trajs, priors = mc.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    s = mc.personalization_summary(oof, trajs, priors, ev)
    d_beta = [t["trajectory"][-1]["beta_mean"] - t["trajectory"][0]["beta_mean"] for t in trajs.values()]       # trajectory[0] IS that person's prior
    d_gamma = [t["trajectory"][-1]["gamma_mean"] - t["trajectory"][0]["gamma_mean"] for t in trajs.values()]
    assert s["final_minus_prior_beta"]["mean"] == pytest.approx(np.mean(d_beta), abs=1e-12)
    assert s["final_minus_prior_gamma"]["mean"] == pytest.approx(np.mean(d_gamma), abs=1e-12)
    r = [t["trajectory"][-1]["beta_sd"] / t["trajectory"][0]["beta_sd"] for t in trajs.values()]
    assert s["final_over_prior_sd_beta"]["mean"] == pytest.approx(np.mean(r), abs=1e-12)
    ob, tb, pb = mb.cross_validated_sequential(ev, folds, prior_scheme="blueprint", group_of=GROUPS)
    sb = mb.personalization_summary(ob, tb, pb)
    d = [t["trajectory"][-1]["sens_mean"] - t["trajectory"][0]["sens_mean"] for t in tb.values()]
    assert sb["final_minus_prior_sensitivity_mean"]["mean"] == pytest.approx(np.mean(d), abs=1e-12)
    assert sb["abs_final_minus_prior_sensitivity_mean"]["mean"] == pytest.approx(np.mean(np.abs(d)), abs=1e-12)     # not invariant to averaging priors within a fold
    rs = [t["trajectory"][-1]["sens_sd"] / t["trajectory"][0]["sens_sd"] for t in tb.values()]
    assert sb["final_over_prior_sensitivity_sd"]["mean"] == pytest.approx(np.mean(rs), abs=1e-12)


def test_fold_level_prior_summaries_count_pooled_fallbacks():
    sums = [{"beta_prior_mean": 0.9, "beta_prior_sd": 0.1, "noise_sd_model_b": 10.0, "noise_sd_model_c": 10.0, "gamma_prior_sd": 0.05,
             "n_stratum_events": 100, "n_stratum_participants": 10, "group_used": g, "fallback_reason": None} for g in ("healthy", None, None)]
    assert ps.fold_summary_B(sums)["n_pooled_fallbacks"] == 2 and ps.fold_summary_C(sums, 0.5)["n_pooled_fallbacks"] == 2
    assert ps.prior_manifest("C", "blueprint", 0.5, sums)["n_pooled_fallbacks"] == 2
