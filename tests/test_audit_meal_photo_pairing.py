"""scripts/audit_meal_photo_pairing.py on SYNTHETIC files only (software test; says nothing about CGMacros)."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("audit_meal_photo_pairing", ROOT / "scripts" / "audit_meal_photo_pairing.py")
amp = importlib.util.module_from_spec(_spec)
sys.modules["audit_meal_photo_pairing"] = amp
_spec.loader.exec_module(amp)


def write(path, rows, image_col=True):
    """rows: (timestamp, meal_type or None, image name or None). Padded with plain CGM rows."""
    d = {"Timestamp": [r[0] for r in rows], "Meal Type": [r[1] for r in rows], "Dexcom GL": 100.0}
    if image_col:
        d["Image path"] = [r[2] for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(d).to_csv(path, index=False)
    return path


def recs(tmp_path, rows, **kw):
    p = write(tmp_path / "CGMacros-001" / "CGMacros-001.csv", rows, **kw)
    df, notes = amp.load_rows(p)
    return amp.pair_candidates(df), df, notes


def test_clear_pair_is_single_candidate_and_next_meal_is_a_bound_not_an_end(tmp_path):
    r, _, _ = recs(tmp_path, [("2000-05-01 14:23:00", "Lunch", "a.jpg"), ("2000-05-01 14:53:00", None, "b.jpg"),
                              ("2000-05-01 18:00:00", "Dinner", "c.jpg")])
    assert [x["class"] for x in r] == [amp.SINGLE, amp.NO_CANDIDATE]
    assert r[0]["offsets_min"] == [30.0] and r[0]["next_meal_gap_min"] == 217.0
    assert "meal_end" not in json.dumps(r)


def test_multiple_candidates_are_reported_not_resolved(tmp_path):
    r, _, _ = recs(tmp_path, [("2000-05-01 20:48:00", "Dinner", "a.jpg"), ("2000-05-01 20:57:00", None, "b.jpg"),
                              ("2000-05-01 21:05:00", None, "c.jpg")])
    assert r[0]["class"] == amp.MULTIPLE and r[0]["offsets_min"] == [9.0, 17.0]
    assert "chosen" not in r[0] and "end" not in r[0]


def test_two_meal_rows_close_together_candidates_belong_only_before_the_next_meal_row(tmp_path):
    r, _, _ = recs(tmp_path, [("2000-05-08 20:16:00", "Dinner", "a.jpg"), ("2000-05-08 20:22:00", "Dinner", "b.jpg"),
                              ("2000-05-08 20:37:00", None, "c.jpg"), ("2000-05-08 21:19:00", None, "d.jpg")])
    assert r[0]["class"] == amp.NO_CANDIDATE and r[0]["next_same_type"] and r[0]["next_meal_gap_min"] == 6.0
    assert r[1]["class"] == amp.MULTIPLE and r[1]["offsets_min"] == [15.0, 57.0] and not r[1]["has_next_meal_row"]


def test_no_candidate_when_nothing_follows_and_meal_row_without_own_image(tmp_path):
    r, _, _ = recs(tmp_path, [("2000-05-01 10:00:00", "Breakfast", None), ("2000-05-01 10:30:00", None, None)])
    assert r[0]["class"] == amp.NO_CANDIDATE and r[0]["own_photo"] is False


def test_candidates_strictly_after_meal_row_and_orphans_counted(tmp_path):
    r, df, _ = recs(tmp_path, [("2000-05-01 09:00:00", None, "early.jpg"), ("2000-05-01 10:00:00", "Lunch", "a.jpg"),
                               ("2000-05-01 10:01:00", None, "b.jpg")])
    assert amp.photos_before_first_meal(df) == 1
    assert r[0]["offsets_min"] == [1.0]


def test_unsorted_file_is_ordered_by_time_and_duplicates_counted(tmp_path):
    r, _, notes = recs(tmp_path, [("2000-05-01 10:30:00", None, "b.jpg"), ("2000-05-01 10:00:00", "Lunch", "a.jpg"),
                                  ("2000-05-01 10:30:00", None, "c.jpg")])
    assert notes["duplicate_timestamps"] == 1 and r[0]["n_candidates"] == 2


def test_missing_image_column_is_reported_and_yields_no_candidates(tmp_path):
    r, _, notes = recs(tmp_path, [("2000-05-01 10:00:00", "Lunch", None)], image_col=False)
    assert notes["image_column_missing"] is True and r[0]["class"] == amp.NO_CANDIDATE


def test_unparseable_timestamps_counted_not_dropped_silently(tmp_path):
    _, _, notes = recs(tmp_path, [("2000-05-01 10:00:00", "Lunch", "a.jpg"), ("garbage", None, "b.jpg")])
    assert notes["unparseable_timestamps"] == 1


def _tree(root):
    for k in range(1, 7):
        rows = [("2000-05-01 14:23:00", "Lunch", f"CGMacros-00{k}/before_{k}.jpg"),
                ("2000-05-01 14:53:00", None, f"CGMacros-00{k}/after_{k}.jpg"),
                ("2000-05-01 20:48:00", "Dinner", f"CGMacros-00{k}/before_{k + 10}.jpg"),
                ("2000-05-01 20:57:00", None, f"CGMacros-00{k}/after_x.jpg"),
                ("2000-05-01 21:05:00", None, f"CGMacros-00{k}/person{'abc'[k % 3]}secret{k}.jpg")]
        write(root / f"CGMacros-00{k}" / f"CGMacros-00{k}.csv", rows)
    pd.DataFrame({"HbA1c": [5.5]}).to_csv(root / "bio.csv", index=False)


def test_end_to_end_counts_reconcile_privacy_and_read_only(tmp_path, capsys):
    root = tmp_path / "ds"; root.mkdir(); _tree(root)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}
    out = tmp_path / "r.json"
    assert amp.main(["--data-root", str(root), "--report-out", str(out)]) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)
    assert rep["rows"]["meal_rows"] == 12 and rep["rows"]["photo_rows"] == 30 and rep["reconciles"]
    assert rep["classification"][amp.SINGLE]["n"] == 6 and rep["classification"][amp.MULTIPLE]["n"] == 6
    assert rep["minutes_from_meal_row_to_first_candidate"]["n"] == 12
    mk = rep["file_name_markers"]
    assert {"before", "after"} <= set(mk["possible_before_after_marker_tokens_present"])
    assert mk["generic_tokens"]["before"]["on_meal_rows"] == 12 and mk["generic_tokens"]["after"]["on_non_meal_rows"] == 12
    for needle in ("secret", "CGMacros-00", "2000-05-01", ".jpg", str(root)):
        assert needle not in text, needle
    assert json.loads(out.read_text()) == rep
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.csv")}


def test_rare_filename_tokens_are_suppressed_below_k(tmp_path):
    root = tmp_path / "ds"; root.mkdir()
    for k in range(1, 7):
        tag = "rareword" if k <= 2 else "commonword"
        write(root / f"CGMacros-00{k}" / f"CGMacros-00{k}.csv", [("2000-05-01 14:00:00", "Lunch", f"{tag}_{k}.jpg")])
    rep = amp.audit(sorted(root.rglob("*.csv")), min_participants=5)
    toks = rep["file_name_markers"]["generic_tokens"]
    assert "rareword" not in toks and "commonword" not in toks   # 4 and 2 participants, below the floor of 5
    assert rep["file_name_markers"]["n_tokens_suppressed_for_rarity"] >= 2


def test_no_dataset_returns_error(tmp_path, capsys):
    (tmp_path / "e").mkdir()
    assert amp.main(["--data-root", str(tmp_path / "e")]) == 2
