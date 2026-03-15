"""Tests for bambulab_metrics_exporter.main."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


from bambulab_metrics_exporter import main
from bambulab_metrics_exporter.config import Settings


# ---------------------------------------------------------------------------
# _safe_load_dotenv
# ---------------------------------------------------------------------------

def test_safe_load_dotenv_missing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    main._safe_load_dotenv()


def test_safe_load_dotenv_permission_error(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        with patch("bambulab_metrics_exporter.main.Path.exists", return_value=True):
            with patch("bambulab_metrics_exporter.main.load_dotenv", side_effect=PermissionError):
                main._safe_load_dotenv()
    assert "Skipping .env load due to permission error" in caplog.text


# ---------------------------------------------------------------------------
# _persist_runtime_env
# ---------------------------------------------------------------------------

def test_persist_runtime_env_permission_error(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        with patch("bambulab_metrics_exporter.main.sync_env_file", side_effect=PermissionError):
            main._persist_runtime_env(Path(".env"))
    assert "Skipping .env sync due to permission error" in caplog.text


# ---------------------------------------------------------------------------
# _bootstrap_cloud_credentials
# ---------------------------------------------------------------------------

def test_bootstrap_cloud_credentials_skips_when_not_cloud(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "local_mqtt")
    main._bootstrap_cloud_credentials()  # should no-op


def test_bootstrap_cloud_credentials_skips_when_has_tokens(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_CLOUD_USER_ID", "uid")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "token")
    main._bootstrap_cloud_credentials()  # should no-op


def test_bootstrap_cloud_credentials_skips_without_secret_or_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.delenv("BAMBULAB_CLOUD_USER_ID", raising=False)
    monkeypatch.delenv("BAMBULAB_CLOUD_ACCESS_TOKEN", raising=False)

    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_CREDENTIALS_FILE", "cred.json")
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)
    main._bootstrap_cloud_credentials()

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "sek")
    main._bootstrap_cloud_credentials()


def test_bootstrap_cloud_credentials_loads_from_encrypted_store(tmp_path: Path, monkeypatch) -> None:
    creds = tmp_path / "credentials.enc.json"
    creds.write_bytes(b"dummy")

    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_CREDENTIALS_FILE", "credentials.enc.json")
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "secret")
    monkeypatch.delenv("BAMBULAB_CLOUD_USER_ID", raising=False)
    monkeypatch.delenv("BAMBULAB_CLOUD_ACCESS_TOKEN", raising=False)

    monkeypatch.setattr(
        "bambulab_metrics_exporter.main.load_encrypted_credentials",
        lambda path, secret: {
            "BAMBULAB_CLOUD_USER_ID": "123",
            "BAMBULAB_CLOUD_ACCESS_TOKEN": "token",
        },
    )

    main._bootstrap_cloud_credentials()
    assert os.environ.get("BAMBULAB_CLOUD_USER_ID") == "123"
    assert os.environ.get("BAMBULAB_CLOUD_ACCESS_TOKEN") == "token"


def test_bootstrap_cloud_credentials_loads_and_sets_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.delenv("BAMBULAB_CLOUD_USER_ID", raising=False)
    monkeypatch.delenv("BAMBULAB_CLOUD_ACCESS_TOKEN", raising=False)

    cred_path = tmp_path / "credentials.enc.json"
    cred_path.write_text("dummy")

    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_CREDENTIALS_FILE", "credentials.enc.json")
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "sek")

    payload = {
        "BAMBULAB_CLOUD_USER_ID": "uid2",
        "BAMBULAB_CLOUD_ACCESS_TOKEN": "tok2",
        "BAMBULAB_CLOUD_REFRESH_TOKEN": "ref2",
        "BAMBULAB_CLOUD_MQTT_HOST": "host2",
        "BAMBULAB_CLOUD_MQTT_PORT": "8883",
    }

    with patch("bambulab_metrics_exporter.main.load_encrypted_credentials", return_value=payload):
        main._bootstrap_cloud_credentials()

    assert os.environ.get("BAMBULAB_CLOUD_USER_ID") == "uid2"
    assert os.environ.get("BAMBULAB_CLOUD_ACCESS_TOKEN") == "tok2"


# ---------------------------------------------------------------------------
# run() – wiring and lifecycle
# ---------------------------------------------------------------------------

class _CollectorStub:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


def test_run_wires_components(monkeypatch) -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL1",
        bambulab_cloud_user_id="uid",
        bambulab_cloud_access_token="token",
    )

    monkeypatch.setattr("bambulab_metrics_exporter.main._safe_load_dotenv", lambda: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main._bootstrap_cloud_credentials", lambda: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main.Settings", lambda: settings)
    monkeypatch.setattr("bambulab_metrics_exporter.main.startup_validate", lambda s: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main._persist_runtime_env", lambda p: None)

    class _ClientStub:
        def connect(self): pass
        def disconnect(self): pass
        def fetch_snapshot(self, timeout):
            from bambulab_metrics_exporter.models import PrinterSnapshot
            return PrinterSnapshot(connected=False, raw={})

    monkeypatch.setattr("bambulab_metrics_exporter.main.build_client", lambda s: _ClientStub())

    collector = _CollectorStub()
    monkeypatch.setattr("bambulab_metrics_exporter.main.PollingCollector", lambda client, metrics, settings: collector)

    app_holder: dict = {}

    class _AppStub:
        def on_event(self, _name):
            def deco(fn):
                app_holder["shutdown"] = fn
                return fn
            return deco

    monkeypatch.setattr("bambulab_metrics_exporter.main.build_app", lambda metrics, collector: _AppStub())
    monkeypatch.setattr("bambulab_metrics_exporter.main.uvicorn.run", lambda *a, **k: None)

    main.run()

    assert collector.started is True
    assert "shutdown" in app_holder


def test_main_run_metadata_discovery_from_cloud(monkeypatch) -> None:
    """Cloud metadata discovery updates env vars."""
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-token")
    monkeypatch.delenv("PRINTER_NAME_LABEL", raising=False)

    mock_devices = [{"dev_id": "S123", "name": "CloudName", "model": "P1S"}]
    mock_collector = MagicMock()
    mock_app = MagicMock()

    with patch("bambulab_metrics_exporter.main.get_bind_devices", return_value=mock_devices):
        with patch("bambulab_metrics_exporter.main.PollingCollector", return_value=mock_collector):
            with patch("bambulab_metrics_exporter.main.build_app", return_value=mock_app):
                with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                    with patch("bambulab_metrics_exporter.main.sync_env_file"):
                        with patch("bambulab_metrics_exporter.main.startup_validate"):
                            main.run()

    assert os.environ.get("BAMBULAB_PRINTER_NAME") == "CloudName"
    assert os.environ.get("BAMBULAB_PRINTER_MODEL") == "P1S"


def test_main_run_cloud_discovery_fails_gracefully(monkeypatch, caplog) -> None:
    """Cloud metadata discovery failure is non-fatal."""
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-token")

    with patch("bambulab_metrics_exporter.main.get_bind_devices", side_effect=Exception("API error")):
        with patch("bambulab_metrics_exporter.main.PollingCollector"):
            with patch("bambulab_metrics_exporter.main.build_app"):
                with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                    with patch("bambulab_metrics_exporter.main.sync_env_file"):
                        with patch("bambulab_metrics_exporter.main.startup_validate"):
                            main.run()

    assert "Metadata discovery from cloud failed (non-fatal)" in caplog.text


def test_main_shutdown_handler(monkeypatch) -> None:
    """Shutdown handler is registered and calls collector.stop()."""
    monkeypatch.setenv("BAMBULAB_HOST", "192.168.1.100")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "A123")
    monkeypatch.setenv("BAMBULAB_USERNAME", "bblp")

    mock_collector = MagicMock()
    mock_app = MagicMock()
    shutdown_handlers: list = []

    def capture_on_event(event_name):
        def decorator(func):
            if event_name == "shutdown":
                shutdown_handlers.append(func)
            return func
        return decorator

    mock_app.on_event = capture_on_event

    with patch("bambulab_metrics_exporter.main.PollingCollector", return_value=mock_collector):
        with patch("bambulab_metrics_exporter.main.build_app", return_value=mock_app):
            with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                with patch("bambulab_metrics_exporter.main.sync_env_file"):
                    with patch("bambulab_metrics_exporter.main.startup_validate"):
                        main.run()

    assert len(shutdown_handlers) == 1
    shutdown_handlers[0]()
    mock_collector.stop.assert_called_once()
