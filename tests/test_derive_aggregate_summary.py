"""scripts/derive_aggregate_summary.py: parsing, privacy, and sync with the committed artifacts.
The text fixture imitates the inventory markdown's LINE FORMAT with made-up numbers."""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("derive_aggregate_summary", ROOT / "scripts" / "derive_aggregate_summary.py")
das = importlib.util.module_from_spec(_spec)
sys.modules["derive_aggregate_summary"] = das
_spec.loader.exec_module(das)

FIXTURE = r"""# Dataset inventory summary
## Observed facts
- 12 files found under the configured dataset root.
- File extensions present: {'.csv': 5, '.jpg': 7}.
- 3 top-level directories match a per-participant naming pattern (heuristic; not a confirmed participant count).
- 7 image files found ({'.jpg': 7}); none were opened or read.
- 'bio.csv' (csv): 4 rows, 6 columns, candidate timestamp column(s): ['t'].
- '<participant_id>\CGMacros-001.csv' (csv): 100 rows, 14 columns, candidate timestamp column(s): ['Timestamp'].
- '<participant_id>\CGMacros-002.csv' (csv): 105 rows, 15 columns, candidate timestamp column(s): ['Timestamp'].
- '<participant_id>/CGMacros-003.csv' (csv): 99 rows, 14 columns.
## Open questions
- something
"""


def test_parse_extracts_totals_participant_shapes_and_other_tables():
    p = das.parse_inventory_markdown(FIXTURE)
    assert p["total_files"] == 12 and p["extension_counts"] == {".csv": 5, ".jpg": 7}
    assert p["participant_like_dirs"] == 3 and p["image_files"] == 7
    assert sorted(p["participant_shapes"]) == [(99, 14), (100, 14), (105, 15)]    # both separators handled
    assert p["other_tables"] == {"bio.csv": {"rows": 4, "columns": 6}}


def test_summary_has_no_names_no_per_file_entries_and_correct_arithmetic():
    s = das.build_aggregate_summary(das.parse_inventory_markdown(FIXTURE), "ab" * 32, "data/audit/x.md")
    pf = s["participant_files"]
    assert pf["n_files"] == 3 and pf["total_rows"] == 304 and pf["row_counts_divisible_by_5"] == 2 and pf["row_counts_divisible_by_15"] == 1
    assert pf["column_count_distribution"] == {14: 2, 15: 1}
    text = json.dumps(s) + das.render_markdown(s)
    assert "CGMacros-00" not in text and "participant_id" not in text
    assert s["provenance"]["source_sha256"] == "ab" * 32


def test_committed_aggregate_files_are_in_sync_with_the_committed_markdown():
    """If someone edits the inventory markdown, the aggregate must be regenerated."""
    src = ROOT / "data" / "audit" / "dataset_inventory_summary.md"
    agg = ROOT / "data" / "audit" / "dataset_aggregate_summary.json"
    if not (src.exists() and agg.exists()):
        return
    raw = src.read_bytes()
    expect = das.build_aggregate_summary(das.parse_inventory_markdown(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest(),
                                         "data/audit/dataset_inventory_summary.md")
    assert json.loads(agg.read_text(encoding="utf-8")) == json.loads(json.dumps(expect))   # JSON turns int keys into str
    md = (ROOT / "data" / "audit" / "dataset_aggregate_summary.md").read_text(encoding="utf-8")
    assert md == das.render_markdown(expect)


def test_committed_aggregate_artifacts_contain_no_participant_file_names():
    for name in ("dataset_aggregate_summary.json", "dataset_aggregate_summary.md"):
        f = ROOT / "data" / "audit" / name
        if f.exists():
            assert not re.search(r"CGMacros-\d+", f.read_text(encoding="utf-8")), name


def test_main_writes_both_files_deterministically(tmp_path):
    src = tmp_path / "in.md"; src.write_text(FIXTURE, encoding="utf-8")
    out = tmp_path / "out"
    assert das.main(["--source", str(src), "--out-dir", str(out)]) == 0
    a = (out / "dataset_aggregate_summary.json").read_bytes()
    assert das.main(["--source", str(src), "--out-dir", str(out)]) == 0
    assert (out / "dataset_aggregate_summary.json").read_bytes() == a
    assert (out / "dataset_aggregate_summary.md").exists()
