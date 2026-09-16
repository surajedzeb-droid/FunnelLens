import pytest

from funnellens.settings import SettingsError, load_settings


def test_missing_secrets_raises_clear_error_without_leaking_values(tmp_path, monkeypatch):
    monkeypatch.delenv("LSQ_ACCESS_KEY", raising=False)
    monkeypatch.delenv("LSQ_SECRET_KEY", raising=False)
    monkeypatch.delenv("LSQ_API_HOST", raising=False)
    monkeypatch.setenv("LSQ_ACCESS_KEY", "SHOULD_NOT_APPEAR")
    monkeypatch.delenv("LSQ_SECRET_KEY", raising=False)

    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SettingsError) as exc_info:
        load_settings()
    message = str(exc_info.value)
    assert "SHOULD_NOT_APPEAR" not in message
    assert "LSQ_SECRET_KEY" in message  # names the missing key, not its value


def test_missing_config_file_raises_settings_error(tmp_path, monkeypatch):
    monkeypatch.setenv("LSQ_ACCESS_KEY", "a")
    monkeypatch.setenv("LSQ_SECRET_KEY", "b")
    monkeypatch.setenv("LSQ_API_HOST", "host")
    with pytest.raises(SettingsError):
        load_settings(config_path=tmp_path / "does_not_exist.yaml")
