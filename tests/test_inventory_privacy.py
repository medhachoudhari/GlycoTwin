"""Privacy behaviour of the public inventory report (synthetic trees; nothing here is real data)."""
import json

import pandas as pd

from glycotwin.data.inventory import (
    _redact_subject_ids, is_participant_file, run_audit, summarize_participant_files)

DIRS = {"CGMacros-001", "CGMacros-002"}


def test_file_names_are_redacted_not_just_folder_names():
    assert _redact_subject_ids("CGMacros-001/CGMacros-001.csv", DIRS) == "<participant_id>/<participant_file>.csv"
    assert _redact_subject_ids("bio.csv", DIRS) == "bio.csv"
    assert _redact_subject_ids("CGMacros-099.csv", DIRS) == "<participant_file>.csv"      # id not in the dir set


def test_windows_separators_are_handled_on_any_os():
    assert _redact_subject_ids(r"CGMacros-001\CGMacros-001.csv", DIRS) == "<participant_id>/<participant_file>.csv"
    assert is_participant_file(r"CGMacros-002\notes.csv", DIRS)
    assert not is_participant_file(r"docs\readme.md", DIRS)


def test_aggregate_summary_math_and_no_per_file_entries():
    s = summarize_participant_files([(14730, 15), (14275, 14), (5655, 14), (14400, 14), (None, None)])
    assert s["n_files"] == 5 and s["total_rows"] == 14730 + 14275 + 5655 + 14400
    assert s["rows_min"] == 5655 and s["rows_max"] == 14730
    assert s["files_with_fewer_than_14400_rows"] == 2
    assert s["row_counts_divisible_by_5"] == 4 and s["row_counts_divisible_by_15"] == 3
    assert s["column_count_distribution"] == {14: 3, 15: 1}
    assert not any(isinstance(v, list) for v in s.values())                                # nothing per-file


def _tree(root):
    for pid in ("CGMacros-001", "CGMacros-002", "CGMacros-003"):
        d = root / pid
        d.mkdir()
        pd.DataFrame({"Timestamp": pd.date_range("2000-01-01", periods=10, freq="1min"), "Dexcom GL": range(10)}) \
            .to_csv(d / f"{pid}.csv", index=False)
    pd.DataFrame({"age": [1, 2]}).to_csv(root / "bio.csv", index=False)


def test_public_report_has_no_participant_names_or_per_file_participant_entries(tmp_path):
    root = tmp_path / "ds"; root.mkdir(); _tree(root)
    pub, loc = tmp_path / "pub", tmp_path / "loc"
    r = run_audit(root, output_dir=pub, local_output_dir=loc)
    text = (pub / "dataset_inventory_summary.json").read_text() + (pub / "dataset_inventory_summary.md").read_text()
    assert "CGMacros-00" not in text
    assert [p["relative_path"] for p in r.tabular_profiles_public] == ["bio.csv"]            # non-participant table stays per-file
    assert r.participant_file_summary["n_files"] == 3 and r.participant_file_summary["total_rows"] == 30
    assert any("participant-pattern CSV files" in f for f in r.observed_facts)
    assert "CGMacros-001" in (loc / "full_inventory.json").read_text()                       # local-only report keeps ids
    assert json.loads((pub / "dataset_inventory_summary.json").read_text())["participant_file_summary"]["n_files"] == 3
