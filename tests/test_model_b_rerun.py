"""Model B re-run on Model C's exact event subset (paired B-vs-C preparation). SYNTHETIC data only; no real-data claim."""
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
from test_model_c_cv import cohort, make_events

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path, per=10, drop_participant="CGMacros-007"):
    root = tmp_path / "ds"; root.mkdir()
    g = cohort()
    a1c = {"healthy": 5.2, "pre-diabetes": 6.0, "t2d": 7.1}
    pd.DataFrame({"subject": [int(p[-3:]) for p in g], "A1c PDL (Lab)": [a1c[v] for v in g.values()]}).to_csv(root / "bio.csv", index=False)
    ev = make_events(per=per)
    ev.loc[ev["participant_id"] == drop_participant, "eligible_activity"] = False      # a participant with NO activity-eligible events
    ev.loc[ev.index[:6], "eligible_activity"] = False                                    # plus a few scattered ones
    ev.loc[ev.index[6:8], "eligible_core"] = False
    table = tmp_path / "event_table_Libre_GL.csv"; ev.to_csv(table, index=False)
    return root, table, ev


def test_default_behaviour_of_run_model_b_is_unchanged_by_the_optional_fold_argument():
    ev = make_events(per=8)
    rep0, oof0, *_ = mb.run_model_b(ev, cohort(), seed=0, n_boot=10)
    rep1, oof1, *_ = mb.run_model_b(ev, cohort(), seed=0, n_boot=10, fold_group_of=cohort())    # same participants: must be identical
    pd.testing.assert_frame_equal(oof0, oof1)
    assert rep0["model_b_overall"] == rep1["model_b_overall"] and rep0["manifest"]["fold_assignment_sha256"] == rep1["manifest"]["fold_assignment_sha256"]


def test_folds_stay_identical_to_models_a_and_c_when_a_participant_has_no_events_in_the_subset():
    ev = make_events(per=8)
    subset = ev[ev["participant_id"] != "CGMacros-007"]
    reference = ma.fold_assignment_hash(ma.make_participant_folds(cohort(), seed=0))
    default_b, *_ = mb.run_model_b(subset, cohort(), seed=0, n_boot=10)                          # original behaviour: folds drift (this is why the option exists)
    fixed_b, oof_b, *_ = mb.run_model_b(subset, cohort(), seed=0, n_boot=10, fold_group_of=cohort())
    c_rep, oof_c, *_ = mc.run_model_c(subset, cohort(), seed=0, n_boot=10)
    assert default_b["manifest"]["fold_assignment_sha256"] != reference
    assert fixed_b["manifest"]["fold_assignment_sha256"] == reference == c_rep["manifest"]["fold_assignment_sha256"]
    folds = ma.make_participant_folds(cohort(), seed=0)
    fold_b = oof_b.set_index("event_id")["fold"]; fold_c = oof_c.set_index("event_id")["fold"]
    pd.testing.assert_series_equal(fold_b.sort_index(), fold_c.sort_index())                       # every event is validated in the same fold by B and C
    assert (oof_b["participant_id"].map(folds) == oof_b["fold"]).all()


def test_fold_group_of_must_cover_every_participant_in_the_events():
    ev = make_events(per=4)
    partial = {p: g for p, g in cohort().items() if p != "CGMacros-001"}
    with pytest.raises(ValueError, match="fold_group_of"):
        mb.run_model_b(ev, cohort(), seed=0, n_boot=5, fold_group_of=partial)


def test_model_b_still_ignores_activity_completely():
    ev = make_events(per=8)
    changed = ev.assign(activity_level=ev["activity_level"] * 50, eligible_activity=True)
    a, *_ = mb.run_model_b(ev, cohort(), seed=0, n_boot=10)
    b, *_ = mb.run_model_b(changed, cohort(), seed=0, n_boot=10)
    assert a["model_b_overall"] == b["model_b_overall"]                                          # B never reads activity


def test_script_activity_eligible_population_matches_model_c_events_folds_and_does_not_overwrite_the_core_run(tmp_path, capsys):
    rmb, rmc = _load("run_model_b"), _load("run_model_c")
    root, table, ev = _tree(tmp_path)
    out = tmp_path / "out"
    base = ["--data-root", str(root), "--event-table", str(table), "--n-boot", "10", "--out-dir", str(out)]
    assert rmb.main(base) == 0
    core_rep = json.loads(capsys.readouterr().out)
    assert rmb.main(base + ["--population", "activity-eligible"]) == 0
    act_rep = json.loads(capsys.readouterr().out)
    assert rmc.main(base) == 0
    c_rep = json.loads(capsys.readouterr().out)
    # outputs are separate: the core-eligible run is never overwritten
    for name in ("model_b_Libre_GL.json", "model_b_sequential_forecasts_Libre_GL.csv", "model_b_trajectories_Libre_GL.json",
                 "model_b_Libre_GL_activity_eligible.json", "model_b_sequential_forecasts_Libre_GL_activity_eligible.csv",
                 "model_b_trajectories_Libre_GL_activity_eligible.json"):
        assert (out / name).exists(), name
    assert json.loads((out / "model_b_Libre_GL.json").read_text()) == core_rep
    # population, counts and folds
    n_core, n_act = int(ev["eligible_core"].sum()), int((ev["eligible_core"] & ev["eligible_activity"]).sum())
    assert core_rep["data"]["n_events"] == n_core and act_rep["data"]["n_events"] == n_act == c_rep["data"]["n_events"] < n_core
    assert act_rep["manifest"]["n_core_events"] == n_core and act_rep["manifest"]["n_events_dropped_for_missing_or_low_coverage_activity"] == n_core - n_act
    assert "activity-eligible" in act_rep["manifest"]["population"] and core_rep["manifest"]["population"] == "core-eligible events"
    assert act_rep["manifest"]["fold_assignment_sha256"] == c_rep["manifest"]["fold_assignment_sha256"] == core_rep["manifest"]["fold_assignment_sha256"]
    assert act_rep["data"]["n_participants"] == 44 and c_rep["data"]["n_participants"] == 44        # CGMacros-007 has none, folds still use all 45
    # B and C forecast exactly the same events, so the paired comparison works
    fb = pd.read_csv(out / "model_b_sequential_forecasts_Libre_GL_activity_eligible.csv")
    fc = pd.read_csv(out / "model_c_sequential_forecasts_Libre_GL.csv")
    assert set(fb["event_id"]) == set(fc["event_id"]) and len(fb) == len(fc) == n_act
    assert (fb.set_index("event_id").loc[fc["event_id"], "fold"].to_numpy() == fc["fold"].to_numpy()).all()
    paired = mc.compare_c_to_b(fc, fb, n_boot=20)
    assert paired["comparisons"][0]["n_events"] == n_act
    with pytest.raises(ValueError, match="same events"):
        mc.compare_c_to_b(fc, pd.read_csv(out / "model_b_sequential_forecasts_Libre_GL.csv"))      # the core-eligible B run cannot be paired with C


def test_script_default_population_and_outputs_are_the_original_ones_and_aggregate_only(tmp_path, capsys):
    rmb = _load("run_model_b")
    root, table, ev = _tree(tmp_path)
    before = hashlib.sha256(table.read_bytes()).hexdigest()
    out = tmp_path / "out"
    assert rmb.main(["--data-root", str(root), "--event-table", str(table), "--n-boot", "10", "--out-dir", str(out)]) == 0
    text = capsys.readouterr().out
    assert sorted(p.name for p in out.iterdir()) == ["model_b_Libre_GL.json", "model_b_sequential_forecasts_Libre_GL.csv", "model_b_trajectories_Libre_GL.json"]
    for needle in ("CGMacros-", "2000-01-01", str(root)):
        assert needle not in text, needle
    assert hashlib.sha256(table.read_bytes()).hexdigest() == before
    assert rmb.main(["--data-root", str(root), "--event-table", str(table), "--population", "activity-eligible"] + ["--out-dir", str(tmp_path / "o2")]) == 0
    capsys.readouterr()
    no_flag = table.parent / "nf_Libre_GL.csv"; ev.drop(columns=["eligible_activity"]).to_csv(no_flag, index=False)
    assert rmb.main(["--data-root", str(root), "--event-table", str(no_flag), "--population", "activity-eligible", "--out-dir", str(tmp_path / "o3")]) == 2


def test_model_b_module_still_has_no_activity_or_model_c_dependency_and_model_c_does_not_import_it():
    b_src = (ROOT / "src" / "glycotwin" / "models" / "model_b_cv.py").read_text(encoding="utf-8")
    assert "model_c" not in b_src and "activity_level" not in b_src                               # B never reads activity
    c_src = (ROOT / "src" / "glycotwin" / "models" / "model_c_cv.py").read_text(encoding="utf-8")
    assert "import model_b_cv" not in c_src and "from glycotwin.models.model_b_cv" not in c_src   # the two pipelines stay separate
