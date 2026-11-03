import os

import pytest

from emporio import api_key
from emporio.api_key import ensure_api_key


def test_missing_key_is_asked_for_and_kept_in_memory_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-...")  # the template's placeholder counts as missing
    monkeypatch.setattr(api_key.getpass, "getpass", lambda prompt: "sk-ant-typed")
    ensure_api_key()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-typed"
    assert list(tmp_path.iterdir()) == []  # nothing written to disk


def test_no_key_given_stops_cleanly(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(api_key.getpass, "getpass", lambda prompt: "")
    with pytest.raises(SystemExit):
        ensure_api_key()


def test_existing_key_is_not_asked_again(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")

    def fail(prompt):
        raise AssertionError("should not ask")

    monkeypatch.setattr(api_key.getpass, "getpass", fail)
    ensure_api_key()
