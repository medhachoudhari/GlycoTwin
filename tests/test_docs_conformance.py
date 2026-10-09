"""Documentation integrity: every file path cited in the conformance, architecture and model-card docs exists."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["docs/BLUEPRINT_CONFORMANCE.md", "docs/ARCHITECTURE.md", "docs/model_card.md", "docs/activity_definition.md", "docs/blueprint_prior.md"]
PATH = re.compile(r"`((?:src|scripts|docs|tests)/[A-Za-z0-9_./-]+\.(?:py|md))")


@pytest.mark.parametrize("doc", DOCS)
def test_cited_paths_exist(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    cited = set(PATH.findall(text))
    assert cited or doc.endswith("model_card.md")
    missing = [p for p in cited if not (ROOT / p).exists() and "{" not in p]
    assert not missing, missing


def test_conformance_is_built_from_the_pdf_and_uses_the_full_status_vocabulary():
    t = (ROOT / "docs/BLUEPRINT_CONFORMANCE.md").read_text(encoding="utf-8")
    assert "wrongly said the PDF was unreadable" in t and "38 pages" in t
    assert "not readable" not in t and "cannot be read" not in t
    for word in ("SQLite", "FastAPI", "React", "BLOCKED", "MISSING", "PARTIAL", "COMPLETE", "DEVIATION"):
        assert word in t


def test_conformance_rows_are_well_formed_and_every_blueprint_part_is_covered():
    t = (ROOT / "docs/BLUEPRINT_CONFORMANCE.md").read_text(encoding="utf-8")
    rows = [l for l in t.splitlines() if l.startswith("| ") and not l.startswith("| ---") and not l.startswith("| ID")
            and l.split("|")[1].strip()[:1].isalpha() and l.split("|")[1].strip()[1:].isdigit()]
    assert len(rows) >= 50
    statuses = ("COMPLETE", "PARTIAL", "MISSING", "BLOCKED", "NOT BUILT", "DEVIATION", "DELIBERATE DEVIATION")
    ids = set()
    for l in rows:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        assert len(cells) == 8, l                                       # ID, Part, Requirement, Implementation, Status, Tests, Real data, Next action
        assert cells[0] not in ids, cells[0]
        ids.add(cells[0])
        assert any(cells[4].startswith(x) for x in statuses), l
        assert cells[6] and cells[7] and cells[5], l
    parts = " ".join(l.split("|")[2] for l in rows).replace(",", " ").split()
    for part in ("4", "6", "7", "9", "10", "11", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "25", "26", "30", "32"):
        assert part in parts, part


def test_conformance_never_claims_model_c_superiority_or_clinical_validity():
    t = (ROOT / "docs/BLUEPRINT_CONFORMANCE.md").read_text(encoding="utf-8").lower()
    assert "inconclusive" in t and "not clinically validated" in t
    assert "model c outperforms" not in t and "c beats b" not in t.replace("no claim that model c beats model b", "")


def test_every_test_file_cited_in_the_matrix_exists():
    t = (ROOT / "docs/BLUEPRINT_CONFORMANCE.md").read_text(encoding="utf-8")
    cited = set(re.findall(r"`(tests/[A-Za-z0-9_]+\.py)`", t))
    assert len(cited) >= 15 and all((ROOT / c).exists() for c in cited)


def test_cited_python_symbols_exist():
    from glycotwin.twin import insight, replay, state, adapter
    from glycotwin.models.baseline import PopulationBaselineModel
    assert hasattr(PopulationBaselineModel, "contributions")
    for mod, names in ((insight, ["twin_insight", "parameter_history", "reconciliation_report", "explain_forecast", "what_if", "store_overview", "effective_sensitivity", "GUARDRAILS"]),
                       (replay, ["PASSTHROUGH", "replay_lifecycle"]), (state, ["TwinStore", "reconcile_forecast", "forecast_meal"]),
                       (adapter, ["initialize_twin_from_population", "prepare_participant_events", "canonical_participant_id"]),
                       (insight, ["posterior_convergence", "hit_rate_trend", "explain_forecast_in_context", "what_if_side_by_side", "twin_history_rows", "WHAT_IF_SCREEN_LABEL"])):
        for n in names:
            assert hasattr(mod, n), n


# ------------------------------------------------------------------ the runbook only uses arguments that the scripts really define

def _runbook_commands():
    text = (ROOT / "docs/REAL_DATA_RUNBOOK.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```powershell\n(.*?)```", text, flags=re.S)
    cmds = []
    for b in blocks:
        joined = re.sub(r"`\s*\n\s*", " ", b)                      # PowerShell line continuation
        for line in joined.splitlines():
            m = re.search(r"python scripts\\([a-z_0-9]+)\.py(.*)$", line)
            if m:
                cmds.append((m.group(1), m.group(2)))
    return cmds


def test_every_runbook_command_uses_only_arguments_the_script_defines():
    cmds = _runbook_commands()
    assert len(cmds) >= 25
    for script, args in cmds:
        src = (ROOT / "scripts" / f"{script}.py").read_text(encoding="utf-8")
        defined = set(re.findall(r'add_argument\("(--[a-z0-9-]+)"', src))
        if script == "compare_priors":                                  # its eight input flags are generated from the arm names
            from glycotwin.models.prior_compare import ARMS
            defined |= {f"--{a.replace('_', '-')}" for a in ARMS} | {f"--{a.replace('_', '-')}-report" for a in ARMS}
        used = set(re.findall(r"(--[a-z][a-z0-9-]*)", args))
        assert used <= defined, (script, used - defined)


def test_runbook_sets_the_channel_explicitly_wherever_a_default_could_silently_pick_dexcom():
    for script, args in _runbook_commands():
        if script in ("build_event_table", "check_leakage_on_data"):
            assert "--channel" in args, script                      # these two scripts default to Dexcom GL


def test_runbook_never_writes_outside_ignored_folders_and_keeps_the_primary_protocol_values():
    text = (ROOT / "docs/REAL_DATA_RUNBOOK.md").read_text(encoding="utf-8")
    paths = re.findall(r'--(?:report-out|svg-out|table-out|out-dir|oof-out|folds-out)\s+"?\$?(?:RUN\w*|\{?[A-Za-z]*\}?)[^\s"]*', text)
    assert paths and all("data\\audit" not in p and "docs" not in p for p in paths)
    assert "git add -A" in text and "never" in text.lower()
    primary = text.split("## 2.")[0]
    assert "--max-gap-minutes 15" in primary and "--seed 0" in primary and "--prior-scheme" not in primary.split("## 1.")[1]


# ------------------------------------------------------------------ fresh-run-folder guarantees in the runbook

def test_runbook_uses_fresh_run_folders_and_never_targets_existing_output_folders():
    text = (ROOT / "docs/REAL_DATA_RUNBOOK.md").read_text(encoding="utf-8")
    cmds = _runbook_commands()
    for script, args in cmds:
        for flag in ("--report-out", "--svg-out", "--table-out", "--out-dir", "--oof-out", "--folds-out"):
            for val in re.findall(flag + r'\s+"?([^\s"]+)', args):
                assert val.startswith(("$RUN", "$P", "$T")), (script, flag, val)           # always a run folder variable, never data\processed or audit_local
    assert 'throw "$RUN already holds a run' in text and "existing_outputs_before" in text and "existing_outputs_after" in text
    for folder in ("primary_Libre_gap15", "S1_Libre_gap30", "S2S3_Libre_gap15_blueprint", "S4_Dexcom_gap15"):
        assert folder in text


def test_runbook_downstream_commands_all_use_the_new_event_table():
    for script, args in _runbook_commands():
        if script in ("run_model_a", "run_model_b", "run_model_c", "replay_participant"):
            assert "--event-table" in args, script                                        # never the default (possibly old) table
            assert re.search(r'--event-table\s+("?\$RUN\w*\\event_table_|\$T\b)', args), (script, args)
    text = (ROOT / "docs/REAL_DATA_RUNBOOK.md").read_text(encoding="utf-8")
    assert "event_table_Libre_GL.settings.json" in text and "max_cgm_gap_minutes" in text and "Compare-Object" in text


def test_runbook_prior_comparison_commands_pass_all_eight_inputs_and_the_gamma_pin():
    cmds = [a for s, a in _runbook_commands() if s == "compare_priors"]
    assert cmds
    for a in cmds:
        for flag in ("--b-eb", "--b-eb-report", "--b-bp", "--b-bp-report", "--c-eb", "--c-eb-report", "--c-bp", "--c-bp-report", "--expect-gamma", "--report-out"):
            assert re.search(re.escape(flag) + r"\s", a), flag
        assert "prior-blueprint" in a and "$RUN2" in a and "$P" in a
