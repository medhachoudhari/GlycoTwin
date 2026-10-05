import pytest

from glycotwin.config import DATA_ROOT_ENV_VAR, DatasetNotFoundError, get_dataset_root


def test_unset_env_raises_clear_error(monkeypatch):
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)
    with pytest.raises(DatasetNotFoundError, match=DATA_ROOT_ENV_VAR):
        get_dataset_root()


def test_missing_path_raises(tmp_path):
    with pytest.raises(DatasetNotFoundError, match="does not exist"):
        get_dataset_root(tmp_path / "nope")


def test_file_path_raises(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(DatasetNotFoundError, match="not a directory"):
        get_dataset_root(f)


def test_env_var_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(tmp_path))
    assert get_dataset_root() == tmp_path.resolve()


def test_explicit_path_overrides_env(monkeypatch, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(tmp_path))
    assert get_dataset_root(other) == other.resolve()
