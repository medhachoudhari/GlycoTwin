"""scripts/run_experiment.py on a SYNTHETIC event table (software test; not a result)."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from synthetic import make_hierarchical_meals
from glycotwin.models.experiment import MODEL_A, MODELS, run_prequential_experiment

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("run_experiment", ROOT / "scripts" / "run_experiment.py")
rx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rx)


def _table(path, **kw):
    df = make_hierarchical_meals(**kw)
    df["eligible_activity"] = True
    df["event_id"] = [f"{p}-{i}" for i, p in enumerate(df.participant_id)]
    df.to_csv(path, index=False)
    return path


def test_model_a_is_included_on_request_and_never_trained_on_the_held_out_participant():
    df = make_hierarchical_meals(10, 20, seed=1, sens_sd=0.3, noise_sd=8.0)
    rec = run_prequential_experiment(df, seed=1, include_model_a=True)
    a = rec[rec.model == MODEL_A]
    assert len(a) == len(rec[rec.model == "B"]) and a["p"].between(0, 1).all() and a["mean_rise"].isna().all()
    assert MODEL_A not in set(run_prequential_experiment(df, seed=1)["model"]) and set(MODELS) <= set(rec["model"])


def test_refuses_underpowered_data_and_stamps_forced_runs(tmp_path, capsys):
    t = _table(tmp_path / "t.csv", n_participants=5, n_meals=6, seed=0)
    assert rx.main(["--table", str(t), "--out", str(tmp_path / "o.json")]) == 3
    refused = json.loads(capsys.readouterr().out)
    assert refused["ran"] is False and "participants" in refused["sample_size"]["shortfalls"]
    assert not (tmp_path / "o.json").exists()
    assert rx.main(["--table", str(t), "--out", str(tmp_path / "o.json"), "--force-underpowered", "--n-boot", "50", "--no-model-a"]) == 0
    forced = json.loads(capsys.readouterr().out)
    assert forced["underpowered"] is True and forced["comparisons"]


def test_adequate_synthetic_data_runs_and_reports_every_prelisted_comparison(tmp_path, capsys):
    t = _table(tmp_path / "t.csv", n_participants=22, n_meals=12, seed=2, sens_sd=0.35, interaction_mean=-0.35, noise_sd=8.0)
    assert rx.main(["--table", str(t), "--out", str(tmp_path / "o.json"), "--n-boot", "200"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert not rep["underpowered"] and rep["sample_size"]["adequate"]
    assert len(rep["comparisons"]) == len(rx.COMPARISONS)                     # none dropped or added after the fact
    assert all("interval_excludes_zero" in c for c in rep["comparisons"])
    assert rep["manifest"]["event_table_sha256"] and "reading_rules" in rep
    assert "p000" not in json.dumps(rep) and json.loads((tmp_path / "o.json").read_text()) == rep


def test_missing_table_is_a_clear_error_that_does_not_echo_the_path(tmp_path, capsys):
    assert rx.main(["--table", str(tmp_path / "nope.csv")]) == 2
    assert "nope.csv" not in capsys.readouterr().err


def test_the_population_activity_control_is_among_the_prelisted_comparisons():
    """C vs frozen_C separates personal activity learning from a population-level activity effect;
    it must be fixed in advance, not added after seeing results."""
    pairs = {(a, b, sub) for a, b, _m, sub in rx.COMPARISONS}
    assert ("C", "frozen_C", "active") in pairs and ("frozen_C", "frozen_B", "active") in pairs
    assert len(rx.COMPARISONS) == len(set(rx.COMPARISONS))
