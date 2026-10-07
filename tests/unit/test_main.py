"""Tests for bambulab_metrics_exporter.main."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest


from bambulab_metrics_exporter import main


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

class _RuntimeStub:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def stop(self) -> None:
        self.events.append("stop")


def _capture_app(handlers: dict):
    class _AppStub:
        def on_event(self, name):
            def deco(fn):
                handlers[name] = fn
                return fn
            return deco

    return _AppStub()


def test_run_starts_runtime_before_server_and_stops_on_shutdown(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    order: list[str] = []
    runtime = _RuntimeStub()
    handlers: dict = {}

    monkeypatch.setattr("bambulab_metrics_exporter.main._safe_load_dotenv", lambda: order.append("dotenv"))
    monkeypatch.setattr("bambulab_metrics_exporter.main.apply_overrides_to_env", lambda: order.append("overrides"))
    monkeypatch.setattr("bambulab_metrics_exporter.main._bootstrap_cloud_credentials", lambda: order.append("bootstrap"))
    monkeypatch.setattr("bambulab_metrics_exporter.main.ExporterRuntime", lambda: runtime)

    def fake_build_app(runtime=None):
        assert runtime is not None
        order.append("app")
        return _capture_app(handlers)

    monkeypatch.setattr("bambulab_metrics_exporter.main.build_app", fake_build_app)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.main.uvicorn.run",
        lambda app, host, port, log_level: order.append(f"serve:{port}"),
    )

    main.run()

    # Page overrides apply after .env and before credentials bootstrap; the server starts
    # without waiting for the printer connection.
    assert order[:3] == ["dotenv", "overrides", "bootstrap"]
    assert "BAMBU LAB METRICS EXPORTER WEB UI" in caplog.text and "/auth" in caplog.text
    assert order[-2:] == ["app", "serve:9109"]
    assert runtime.events == ["start"]

    handlers["shutdown"]()
    assert runtime.events == ["start", "stop"]


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("0.0.0.0", 9109, "http://<docker-host>:9109"),
        ("::", 9200, "http://<docker-host>:9200"),
        ("127.0.0.1", 9109, "http://127.0.0.1:9109"),
        ("::1", 9109, "http://[::1]:9109"),
    ],
)
def test_base_url(host: str, port: int, expected: str) -> None:
    from bambulab_metrics_exporter.config import Settings

    assert main.base_url(Settings(listen_host=host, listen_port=port)) == expected


def test_log_web_endpoints(caplog) -> None:
    from bambulab_metrics_exporter.config import Settings

    caplog.set_level(logging.INFO)
    main.log_web_endpoints(Settings(listen_host="0.0.0.0", listen_port=9110))
    for path in ("/", "/auth", "/metrics", "/health", "/ready"):
        assert f"http://<docker-host>:9110{path}" in caplog.text
    assert "9110 is the container port" in caplog.text

    caplog.clear()
    main.log_web_endpoints(Settings(listen_host="127.0.0.1", listen_port=9109))
    assert "http://127.0.0.1:9109/auth" in caplog.text
    assert "container port" not in caplog.text
