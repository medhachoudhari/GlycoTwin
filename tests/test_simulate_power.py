import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("simulate_power", ROOT / "scripts" / "simulate_power.py")
sp = importlib.util.module_from_spec(_spec)
sys.modules["simulate_power"] = sp
_spec.loader.exec_module(sp)

TINY = ["--participants", "8", "--events", "6", "--effects", "0", "-0.35", "--reps", "2", "--n-boot", "40"]


def test_report_is_labelled_a_simulation_and_has_one_row_per_scenario(capsys):
    assert sp.main(TINY) == 0
    rep = json.loads(capsys.readouterr().out)
    assert "SIMULATION" in rep["WHAT_THIS_IS"] and "not an estimate" in rep["WHAT_THIS_IS"]
    assert len(rep["scenarios"]) == 2 and {s["assumed_interaction"] for s in rep["scenarios"]} == {0.0, -0.35}
    for s in rep["scenarios"]:
        assert all(0.0 <= s[k] <= 1.0 for k in ("C_beats_B_active", "C_beats_B_all", "B_beats_frozen", "C_worse_than_B_active"))
        assert s["reps"] == 2


def test_is_deterministic_for_a_seed(capsys):
    sp.main(TINY); a = capsys.readouterr().out
    sp.main(TINY); assert capsys.readouterr().out == a


def test_rejects_degenerate_arguments(capsys):
    assert sp.main(["--participants", "1"]) == 2 and sp.main(["--reps", "0"]) == 2
