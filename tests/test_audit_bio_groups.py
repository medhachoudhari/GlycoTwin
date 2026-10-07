"""scripts/audit_bio_groups.py on SYNTHETIC files only (software test; says nothing about the real bio.csv)."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("audit_bio_groups", ROOT / "scripts" / "audit_bio_groups.py")
abg = importlib.util.module_from_spec(_spec)
sys.modules["audit_bio_groups"] = abg
_spec.loader.exec_module(abg)


def participant(root, k):
    p = root / f"CGMacros-{k:03d}" / f"CGMacros-{k:03d}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Timestamp": ["2000-01-01 00:00:00", "2000-01-01 00:01:00"], "Meal Type": ["Lunch", np.nan]}).to_csv(p, index=False)
    return p


def files(root, numbers):
    return [participant(root, k) for k in numbers]


A1C = "A1c PDL (Lab)"


# ------------------------------------------------------------------ classification rule (the authors' notebook rule)

@pytest.mark.parametrize("a1c, group", [(5.0, "healthy"), (5.69, "healthy"), (5.7, "pre-diabetes"), (6.0, "pre-diabetes"),
                                        (6.4, "pre-diabetes"), (6.41, "t2d"), (9.0, "t2d"), (np.nan, "unknown"), (None, "unknown")])
def test_a1c_rule_and_boundaries(a1c, group):
    assert abg.classify_a1c(a1c) == group


@pytest.mark.parametrize("raw, value, annotated", [("5.4", 5.4, False), (5.4, 5.4, False), ("5.4 (low)", 5.4, True), (" 6.1 (high)", 6.1, True),
                                                    ("n/a", np.nan, False), (np.nan, np.nan, False), (None, np.nan, False), ("<4", np.nan, False)])
def test_parse_numeric_handles_lab_annotations(raw, value, annotated):
    v, a = abg.parse_numeric(raw)
    assert (np.isnan(v) and np.isnan(value)) or v == value
    assert a == annotated


def test_fasting_glucose_diagnostic_categories():
    assert [abg.classify_fasting_glucose(g) for g in (99.9, 100, 125.9, 126, np.nan)] == ["healthy", "pre-diabetes", "pre-diabetes", "t2d", "unknown"]


# ------------------------------------------------------------------ mapping

def test_identifier_column_mapping_is_verified_and_order_independent(tmp_path):
    fs = files(tmp_path, [1, 2, 3, 4, 5, 6])
    bio = pd.DataFrame({"Subject ": ["CGMacros-006", "CGMacros-001", "CGMacros-003", "CGMacros-002", "CGMacros-005", "CGMacros-004"],
                        A1C: [6.5, 5.4, 6.4, 5.7, np.nan, 5.69]})
    bio.to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["mapping"]["method"] == "identifier_column" and rep["mapping"]["verified"] is True
    g = rep["glycaemic_groups"]
    assert (g["healthy"]["n"], g["pre-diabetes"]["n"], g["t2d"]["n"]) == (2, 2, 1)   # 5.4 and 5.69 | 5.7 and 6.4 | 6.5
    mc = rep["mapping_completeness"]
    assert mc["n_participant_files"] == 6 and mc["n_mapped"] == 6 and mc["n_unmapped_participants"] == 0
    assert mc["n_unknown_group_among_mapped"] == 1 and mc["n_classified"] == 5
    assert g["healthy"]["percent_of_classified"] == pytest.approx(40.0)


def test_group_follows_the_identifier_not_the_row_position(tmp_path):
    fs = files(tmp_path, [1, 2])
    bio = pd.DataFrame({"participant": [2, 1], A1C: [7.0, 5.0]})                     # participant 2 is the T2D row, listed first
    bio.to_csv(tmp_path / "bio.csv", index=False)
    mapping = abg.map_participants(bio, [1, 2])
    t, _ = abg.group_table(bio, A1C, mapping, [1, 2])
    assert dict(zip(t["number"], t["group"])) == {1: "healthy", 2: "t2d"}


def test_without_an_identifier_column_the_positional_mapping_is_reported_unverified(tmp_path):
    fs = files(tmp_path, [1, 2, 3])
    pd.DataFrame({A1C: [5.0, 6.0, 7.0], "Age": [30, 40, 50]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["mapping"]["method"] == "positional" and rep["mapping"]["verified"] is False and "NOT documented" in rep["mapping"]["caveat"]
    assert rep["status"].startswith("GROUPS DERIVED BUT SIZES DO NOT MATCH") and "positional and unverified" in rep["status"]   # 3 participants cannot match 15/16/14
    assert any("positional only" in u for u in rep["unresolved"])


def test_row_count_mismatch_without_identifier_makes_no_mapping(tmp_path):
    fs = files(tmp_path, [1, 2, 3])
    pd.DataFrame({A1C: [5.0, 6.0]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["mapping"]["method"] == "none"
    assert rep["mapping_completeness"]["n_mapped"] == 0 and rep["mapping_completeness"]["n_unmapped_participants"] == 3
    assert rep["status"] == "UNRESOLVED mapping"


def test_positional_mapping_with_matching_sizes_is_flagged_unverified_not_established(tmp_path):
    fs = files(tmp_path, list(range(1, 46)))
    pd.DataFrame({A1C: [5.0] * 15 + [6.0] * 16 + [7.0] * 14}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["blueprint_compatibility"]["matches_readme_group_sizes"] is True
    assert rep["status"].startswith("GROUPS DERIVED BUT MAPPING UNVERIFIED") and not rep["status"].startswith("GROUPS ESTABLISHED")


def test_unmapped_participants_and_extra_bio_rows_are_counted(tmp_path):
    fs = files(tmp_path, [1, 2, 3])
    pd.DataFrame({"ID": [1, 2, 9], A1C: [5.0, 6.0, 7.0]}).to_csv(tmp_path / "bio.csv", index=False)       # 3 has no bio row; 9 has no file
    mc = abg.audit(tmp_path / "bio.csv", fs)["mapping_completeness"]
    assert mc["n_mapped"] == 2 and mc["n_unmapped_participants"] == 1 and mc["n_bio_rows_without_a_participant_file"] == 1


def test_identifier_column_that_does_not_match_the_files_is_not_used(tmp_path):
    fs = files(tmp_path, [1, 2])
    pd.DataFrame({"Subject": ["a", "b"], A1C: [5.0, 7.0]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["mapping"]["method"] == "positional"
    assert rep["mapping"]["identifier_evidence"]["candidate_columns_by_name"] == ["Subject"]
    assert rep["mapping"]["identifier_evidence"]["columns_whose_values_match_participant_files"] == []


# ------------------------------------------------------------------ definition, unresolved items, compatibility

def test_no_a1c_column_means_no_group_is_assigned(tmp_path):
    fs = files(tmp_path, [1, 2])
    pd.DataFrame({"Subject": [1, 2], "Age": [30, 40]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["status"].startswith("UNRESOLVED") and "glycaemic_groups" not in rep


def test_a_precomputed_group_column_is_reported_not_silently_preferred(tmp_path):
    fs = files(tmp_path, [1, 2])
    pd.DataFrame({"Subject": [1, 2], A1C: [5.0, 7.0], "Diabetes status": ["x", "y"]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["candidate_fields"]["explicit_group_like_columns_by_name"] == ["Diabetes status"]
    assert rep["group_definition"]["official_per_participant_group_label_found_in_bio_csv"] is True
    assert rep["group_definition"]["a1c_column_used"] == A1C                          # the documented rule is still the one applied


def test_medication_columns_are_listed_and_the_insulin_lab_value_is_not_mistaken_for_therapy(tmp_path):
    fs = files(tmp_path, [1])
    pd.DataFrame({"Subject": [1], A1C: [5.0], "Insulin ": [8.0], "Metformin use": ["no"]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["candidate_fields"]["medication_or_treatment_like_columns_by_name"] == ["Metformin use"]
    pd.DataFrame({"Subject": [1], A1C: [5.0], "Insulin ": [8.0]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["candidate_fields"]["medication_or_treatment_like_columns_by_name"] == []
    assert any("fasting lab value" in u for u in rep["unresolved"])


def test_column_names_with_trailing_spaces_are_matched_and_reported(tmp_path):
    fs = files(tmp_path, [1, 2])
    pd.DataFrame({"Subject": [1, 2], A1C + " ": [5.0, 7.0]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["group_definition"]["a1c_column_name_matches_the_notebook_exactly"] is True
    assert rep["bio_table"]["column_names_with_leading_or_trailing_spaces"] == [A1C + " "]


def test_readme_sizes_and_stratified_fold_feasibility(tmp_path):
    n = 45
    fs = files(tmp_path, list(range(1, 46)))
    a1c = [5.0] * 15 + [6.0] * 16 + [7.0] * 14
    pd.DataFrame({"Subject": list(range(1, 46)), A1C: a1c}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    bc = rep["blueprint_compatibility"]
    assert bc["matches_readme_group_sizes"] and bc["stratified_kfold_feasible"] and bc["smallest_group_participants"] == 14
    assert rep["status"].startswith("GROUPS ESTABLISHED")
    # a group with fewer participants than folds cannot be stratified 5 ways, and sizes that differ from the README are flagged
    a1c = [5.0] * 4 + [6.0] * 27 + [7.0] * 14
    pd.DataFrame({"Subject": list(range(1, 46)), A1C: a1c}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert not rep["blueprint_compatibility"]["stratified_kfold_feasible"] and not rep["blueprint_compatibility"]["matches_readme_group_sizes"]
    assert rep["status"].startswith("GROUPS DERIVED BUT SIZES DO NOT MATCH")


def test_boundary_and_annotation_counts_are_reported(tmp_path):
    fs = files(tmp_path, [1, 2, 3, 4])
    pd.DataFrame({"Subject": [1, 2, 3, 4], A1C: ["5.7", 6.4, "5.2 (low)", "x"]}).to_csv(tmp_path / "bio.csv", index=False)
    q = abg.audit(tmp_path / "bio.csv", fs)["a1c_column_quality"]
    assert q["n_exactly_at_5.7"] == 1 and q["n_exactly_at_6.4"] == 1 and q["n_annotated_strings_such_as_low_high"] == 1
    assert q["n_missing_or_unparseable"] == 1


def test_diagnostic_crosstab_is_labelled_as_not_a_definition(tmp_path):
    fs = files(tmp_path, [1, 2])
    pd.DataFrame({"Subject": [1, 2], A1C: [5.0, 7.0], "Fasting GLU - PDL (Lab)": [90.0, 150.0]}).to_csv(tmp_path / "bio.csv", index=False)
    d = abg.audit(tmp_path / "bio.csv", fs)["diagnostic_a1c_group_vs_fasting_glucose_category"]
    assert "DIAGNOSTIC ONLY" in d["_note"]
    assert d["counts_rows_a1c_group_columns_fasting_category"] == {"healthy|healthy": 1, "t2d|t2d": 1}


# ------------------------------------------------------------------ per-group event counts (optional)

def test_event_counts_by_group_from_an_event_table(tmp_path):
    fs = files(tmp_path, [1, 2, 3])
    pd.DataFrame({"Subject": [1, 2, 3], A1C: [5.0, 6.0, 7.0]}).to_csv(tmp_path / "bio.csv", index=False)
    ev = pd.DataFrame({"participant_id": ["CGMacros-001"] * 3 + ["CGMacros-002"] * 2 + ["CGMacros-003"] * 2 + ["CGMacros-099"],
                       "eligible_core": [True, True, False, True, True, True, True, True],
                       "label_exceeds_180": [1, 0, 1, 0, 0, 1, 1, 1]})
    out = abg.audit(tmp_path / "bio.csv", fs, ev)["event_counts_by_group"]
    assert out["healthy"] == {"n_participants_with_events": 1, "n_extraction_valid": 3, "n_core_eligible": 2, "n_positive": 1, "n_negative": 1}
    assert out["pre-diabetes"]["n_core_eligible"] == 2 and out["pre-diabetes"]["n_negative"] == 2
    assert out["t2d"]["n_positive"] == 2
    assert out["unknown"]["n_extraction_valid"] == 1                                 # a participant that is not in bio.csv is not silently dropped


# ------------------------------------------------------------------ CLI: privacy, read-only, errors

def _cli_tree(root):
    files(root, [1, 2, 3, 4, 5, 6])
    pd.DataFrame({"Subject": [1, 2, 3, 4, 5, 6], A1C: [5.123, 5.789, 6.234, 6.789, 7.456, 5.321], "Age": [31, 42, 53, 64, 75, 86]}).to_csv(root / "bio.csv", index=False)


def test_cli_output_is_aggregate_only_and_the_source_is_not_modified(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir(); _cli_tree(root)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}
    out = tmp_path / "r.json"
    assert abg.main(["--data-root", str(root), "--report-out", str(out)]) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)
    assert rep["glycaemic_groups"]["healthy"]["n"] == 2 and rep["glycaemic_groups"]["pre-diabetes"]["n"] == 2 and rep["glycaemic_groups"]["t2d"]["n"] == 2
    for needle in ("CGMacros-00", "2000-01-01", "5.123", "5.789", "6.234", "6.789", "7.456", "5.321", str(root)):
        assert needle not in text, needle
    assert json.loads(out.read_text()) == rep
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}


def test_missing_bio_csv_or_dataset_is_an_error_not_a_guess(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir(); files(root, [1, 2])
    assert abg.main(["--data-root", str(root)]) == 2
    (tmp_path / "e").mkdir()
    assert abg.main(["--data-root", str(tmp_path / "e")]) == 2


def test_the_existing_event_table_script_is_untouched_by_this_audit():
    src = (ROOT / "scripts" / "build_event_table.py").read_text(encoding="utf-8")
    assert "audit_bio_groups" not in src and "bio.csv" in src                       # it still only lists bio.csv as 'not ingested'


@pytest.mark.parametrize("ids, why", [([1, 1], "duplicate identifiers"), ([101, 102], "numbers that match no participant file"),
                                      ([1, None], "an identifier missing for one row")])
def test_an_unusable_identifier_column_is_rejected_and_never_used(tmp_path, ids, why):
    fs = files(tmp_path, [1, 2])
    pd.DataFrame({"Subject": ids, A1C: [5.0, 7.0]}).to_csv(tmp_path / "bio.csv", index=False)
    rep = abg.audit(tmp_path / "bio.csv", fs)
    assert rep["mapping"]["method"] == "positional" and rep["mapping"]["verified"] is False, why
    assert rep["mapping"]["identifier_evidence"]["columns_whose_values_match_participant_files"] == [], why
