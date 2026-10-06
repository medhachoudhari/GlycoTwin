import pandas as pd

from glycotwin.data.discovery import discover_participant_files


def test_matches_by_header_not_by_name_and_is_sorted(tmp_path):
    (tmp_path / "a").mkdir()
    pd.DataFrame({"Timestamp": [1], "Meal Type": ["x"]}).to_csv(tmp_path / "a" / "weird_name.csv", index=False)
    pd.DataFrame({"Timestamp": [1], "Meal Type ": ["x"]}).to_csv(tmp_path / "b_padded_header.csv", index=False)   # stripped header still matches
    pd.DataFrame({"Timestamp": [1]}).to_csv(tmp_path / "no_meal_column.csv", index=False)
    pd.DataFrame({"HbA1c": [5.5]}).to_csv(tmp_path / "bio.csv", index=False)
    (tmp_path / "broken.csv").write_bytes(b"\x00\x01\x02")
    (tmp_path / "notes.txt").write_text("Timestamp,Meal Type\n")
    paths = discover_participant_files(tmp_path)
    assert paths == sorted(paths)                                            # deterministic (full-path) order
    assert {p.name for p in paths} == {"b_padded_header.csv", "weird_name.csv"}


def test_empty_directory_returns_nothing(tmp_path):
    assert discover_participant_files(tmp_path) == []
