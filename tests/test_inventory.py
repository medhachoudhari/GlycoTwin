"""Tests for glycotwin.data.inventory, using synthetic fixture files only.

Nothing here is real CGMacros data: all values are clearly fabricated and exist
only to exercise the scanning/profiling logic.
"""
from __future__ import annotations

import re

import json

from glycotwin.data.inventory import (
    find_subject_like_dirs,
    profile_csv_file,
    run_audit,
    scan_directory,
)


def _make_fake_dataset(root):
    """Build a small synthetic directory tree shaped like a multi-participant dataset.

    This mimics *structure* only (folders, a doc file, per-participant CSVs and an
    image placeholder) to test the tool's logic -- it is not a claim about what
    CGMacros actually looks like.
    """
    (root / "README.md").write_text("fake top-level documentation placeholder", encoding="utf-8")

    for pid in ("CGMacros-001", "CGMacros-002"):
        pdir = root / pid
        pdir.mkdir()
        csv_text = (
            "Timestamp,glucose_value,note\n"
            "2000-01-01 00:00:00,100,\n"
            "2000-01-01 00:05:00,105,ok\n"
            "2000-01-01 00:10:00,,\n"
        )
        (pdir / "cgm.csv").write_text(csv_text, encoding="utf-8")
        (pdir / "meal_photo.jpg").write_bytes(b"\x00")  # content irrelevant; never read

    return root


def test_scan_directory_counts_files_and_sizes(tmp_path):
    _make_fake_dataset(tmp_path)
    records = scan_directory(tmp_path)
    rel_paths = {r.relative_path for r in records}
    assert "README.md" in rel_paths
    assert any(p.endswith("cgm.csv") for p in rel_paths)
    assert any(p.endswith("meal_photo.jpg") for p in rel_paths)
    assert all(r.size_bytes >= 0 for r in records)


def test_find_subject_like_dirs_detects_pattern(tmp_path):
    _make_fake_dataset(tmp_path)
    subject_dirs = find_subject_like_dirs(tmp_path)
    assert subject_dirs == ["CGMacros-001", "CGMacros-002"]


def test_profile_csv_file_reports_schema_without_row_values(tmp_path):
    _make_fake_dataset(tmp_path)
    csv_path = tmp_path / "CGMacros-001" / "cgm.csv"
    profile = profile_csv_file(csv_path, "CGMacros-001/cgm.csv")

    assert profile.read_error is None
    assert profile.row_count == 3
    names = {c.name for c in profile.columns}
    assert names == {"Timestamp", "glucose_value", "note"}

    ts_col = next(c for c in profile.columns if c.name == "Timestamp")
    assert ts_col.looks_like_timestamp_name is True
    assert ts_col.sample_datetime_parse_fraction == 1.0

    glucose_col = next(c for c in profile.columns if c.name == "glucose_value")
    assert glucose_col.null_count == 1
    assert glucose_col.missing_fraction == 1 / 3

    # The profile object must never carry raw row values, only aggregate stats.
    profile_text = str(profile)
    assert "105" not in profile_text
    assert "2000-01-01" not in profile_text


def test_run_audit_counts_images_without_opening_them(tmp_path):
    _make_fake_dataset(tmp_path)
    output_dir = tmp_path.parent / "out_public"
    local_dir = tmp_path.parent / "out_local"
    result = run_audit(tmp_path, output_dir=output_dir, local_output_dir=local_dir)

    assert result.image_summary["total_count"] == 2
    assert result.image_summary["by_extension"] == {".jpg": 2}


def test_run_audit_redacts_participant_ids_in_public_report_only(tmp_path):
    _make_fake_dataset(tmp_path)
    output_dir = tmp_path.parent / "out_public2"
    local_dir = tmp_path.parent / "out_local2"
    run_audit(tmp_path, output_dir=output_dir, local_output_dir=local_dir)

    public_json = json.loads((output_dir / "dataset_inventory_summary.json").read_text(encoding="utf-8"))
    public_text = json.dumps(public_json)
    assert "CGMacros-001" not in public_text
    assert "CGMacros-002" not in public_text
    assert "<participant_id>" in public_text

    local_json = json.loads((local_dir / "full_inventory.json").read_text(encoding="utf-8"))
    local_text = json.dumps(local_json)
    assert "CGMacros-001" in local_text
    assert "CGMacros-002" in local_text


def test_run_audit_never_prints_row_values_into_reports(tmp_path):
    _make_fake_dataset(tmp_path)
    output_dir = tmp_path.parent / "out_public3"
    local_dir = tmp_path.parent / "out_local3"
    run_audit(tmp_path, output_dir=output_dir, local_output_dir=local_dir)

    for f in [output_dir / "dataset_inventory_summary.json", output_dir / "dataset_inventory_summary.md"]:
        text = f.read_text(encoding="utf-8")
        # the report's own generation time (ISO timestamp with microseconds) can contain any digit run, e.g. "...10.401105";
        # it is not a row value, so it is removed before searching (this was the intermittent failure E-03)
        text = re.sub(r'("generated_at_utc": "|Generated: )[^"\n]*', r"\1<generated-at>", text)   # only the report's own timestamp
        assert "105" not in text  # a glucose value from the fixture
        assert "2000-01-01" not in text  # a timestamp value from the fixture


def test_run_audit_is_read_only_on_the_dataset(tmp_path):
    _make_fake_dataset(tmp_path)
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in tmp_path.rglob("*") if p.is_file()
    }

    run_audit(tmp_path, output_dir=tmp_path.parent / "out_public4", local_output_dir=tmp_path.parent / "out_local4")

    after = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in tmp_path.rglob("*") if p.is_file()
    }
    assert before == after


def test_run_audit_caps_tabular_profiling_and_warns(tmp_path):
    _make_fake_dataset(tmp_path)
    result = run_audit(
        tmp_path,
        output_dir=tmp_path.parent / "out_public5",
        local_output_dir=tmp_path.parent / "out_local5",
        max_tabular_files=1,
    )
    # participant-pattern files are summarised in aggregate, never listed one by one in the public output
    assert result.tabular_profiles_public == []
    assert result.participant_file_summary["n_files"] == 1
    assert any("profiled only the first" in w for w in result.warnings)
