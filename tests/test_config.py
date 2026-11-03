from datetime import datetime

from emporio.config import load_settings


def test_demo_date_is_the_default(tmp_path, monkeypatch):
    monkeypatch.delenv("EMPORIO_REFERENCE_DATE", raising=False)
    settings = load_settings(env_file=tmp_path / "missing.env")
    assert settings.reference_now == datetime(2026, 3, 25, 10, 0)


def test_empty_reference_date_means_the_real_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPORIO_REFERENCE_DATE", "")
    assert load_settings(env_file=tmp_path / "missing.env").reference_now is None
