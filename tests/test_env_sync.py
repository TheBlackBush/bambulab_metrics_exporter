from pathlib import Path
from unittest.mock import patch

from bambulab_metrics_exporter import env_sync
from bambulab_metrics_exporter.env_sync import sync_env_file


def test_sync_env_file_updates_whitelisted_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=INFO\n# comment\n")

    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LISTEN_PORT", "9999")

    sync_env_file(env_file)
    text = env_file.read_text()

    assert "LOG_LEVEL=DEBUG" in text
    assert "LISTEN_PORT=9999" in text


def test_shell_escape() -> None:
    assert env_sync._shell_escape("") == "''"
    assert env_sync._shell_escape("val'with'quotes") == "'val'\\''with'\\''quotes'"


def test_sync_env_file_chmod_error(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=VAL")
    with patch.object(Path, "chmod", side_effect=OSError):
        sync_env_file(env_file)  # should not raise
