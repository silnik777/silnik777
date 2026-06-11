"""Testy loadera danych konfiguracyjnych (core.config)."""

import pytest

from core import config


@pytest.fixture(autouse=True)
def _clear_cache():
    config.clear_cache()
    yield
    config.clear_cache()


def test_data_dir_exists():
    assert config.data_dir().is_dir()


def test_load_quality_limits():
    data = config.load_data_file("quality_limits.yaml")
    wobbe = data["wobbe_index_group_E"]
    assert wobbe["min_mj_per_m3"] < wobbe["nominal_mj_per_m3"] < wobbe["max_mj_per_m3"]
    assert "source" in wobbe


def test_load_reference_conditions_defaults():
    data = config.load_data_file("reference_conditions.yaml")
    assert data["defaults"]["volume_reference"] in {"0C", "15C", "25C"}


def test_missing_file_polish_message():
    with pytest.raises(FileNotFoundError, match="Nie znaleziono pliku danych"):
        config.load_data_file("nie_istnieje.yaml")


def test_missing_meta_raises(tmp_path, monkeypatch):
    (tmp_path / "bez_meta.yaml").write_text("foo: 1\n", encoding="utf-8")
    monkeypatch.setenv("GAS_RD_DATA_DIR", str(tmp_path))
    with pytest.raises(config.ConfigError, match="meta"):
        config.load_data_file("bez_meta.yaml")


def test_data_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_RD_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
