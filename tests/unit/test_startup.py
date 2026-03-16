"""Tests for bambulab_metrics_exporter.startup."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.startup import (
    _probe_connection,
    _try_cloud_reauth,
    _validate_cloud,
    _validate_local,
    startup_validate,
)


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class _ClientOK:
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def fetch_snapshot(self, _timeout: float):
        from bambulab_metrics_exporter.models import PrinterSnapshot
        return PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 1}})


class _ClientFail:
    def connect(self) -> None:
        raise RuntimeError("boom")

    def disconnect(self) -> None:
        pass

    def fetch_snapshot(self, _timeout: float):
        raise RuntimeError("boom")


class _LoginResult:
    def __init__(self) -> None:
        self.user_id = "123"
        self.access_token = "token"
        self.refresh_token = "refresh"


# ---------------------------------------------------------------------------
# _validate_local
# ---------------------------------------------------------------------------

def test_validate_local_missing_vars() -> None:
    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="",
        bambulab_serial="",
        bambulab_access_code="",
    )
    with pytest.raises(RuntimeError):
        _validate_local(settings)


def test_validate_local_probe_fails() -> None:
    settings = Settings(
        bambulab_host="192.168.1.100",
        bambulab_serial="S1",
        bambulab_access_code="A1",
    )
    with patch("bambulab_metrics_exporter.startup._probe_connection", return_value=False):
        with pytest.raises(RuntimeError, match="Local MQTT connection test failed"):
            _validate_local(settings)


# ---------------------------------------------------------------------------
# _probe_connection
# ---------------------------------------------------------------------------

def test_probe_connection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="t",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup.build_client", lambda s: _ClientOK())
    assert _probe_connection(settings) is True


def test_probe_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="t",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup.build_client", lambda s: _ClientFail())
    assert _probe_connection(settings) is False


def test_probe_disconnect_exception(caplog) -> None:
    """disconnect exception during probe should be logged, not raised."""
    settings = Settings(
        bambulab_host="192.168.1.100",
        bambulab_serial="S1",
        bambulab_access_code="A1",
    )
    mock_client = MagicMock()
    mock_client.disconnect.side_effect = Exception("disconnect failed")
    mock_client.fetch_snapshot.side_effect = Exception("connect failed")

    with patch("bambulab_metrics_exporter.startup.build_client", return_value=mock_client):
        result = _probe_connection(settings)

    assert result is False
    assert "Client disconnect failed during probe" in caplog.text


# ---------------------------------------------------------------------------
# _try_cloud_reauth
# ---------------------------------------------------------------------------

def test_try_cloud_reauth_requires_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAMBULAB_CLOUD_EMAIL", raising=False)
    settings = Settings(bambulab_transport="cloud_mqtt", bambulab_serial="S1")
    with pytest.raises(RuntimeError):
        _try_cloud_reauth(settings)


def test_try_cloud_reauth_saves_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "user@example.com")
    monkeypatch.setenv("BAMBULAB_CLOUD_CODE", "123456")
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "super-secret")

    called = {"saved": False, "synced": False}

    def fake_login_with_code(email: str, code: str):
        assert email == "user@example.com"
        assert code == "123456"
        return _LoginResult()

    def fake_save_encrypted_credentials(path: Path, secret: str, payload: dict):
        called["saved"] = True
        assert secret == "super-secret"
        assert path.name == "credentials.enc.json"
        assert payload["BAMBULAB_CLOUD_USER_ID"] == "123"

    def fake_sync_env_file(path: Path):
        called["synced"] = True
        assert path.name == ".env"

    monkeypatch.setattr("bambulab_metrics_exporter.startup.login_with_code", fake_login_with_code)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.save_encrypted_credentials",
        fake_save_encrypted_credentials,
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup.sync_env_file", fake_sync_env_file)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL1",
        bambulab_config_dir=str(tmp_path),
        bambulab_credentials_file="credentials.enc.json",
        bambulab_cloud_mqtt_host="us.mqtt.bambulab.com",
        bambulab_cloud_mqtt_port=8883,
    )
    _try_cloud_reauth(settings)

    assert called["saved"] is True
    assert called["synced"] is True


# ---------------------------------------------------------------------------
# _validate_cloud
# ---------------------------------------------------------------------------

def test_validate_cloud_raises_after_failed_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="t",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", lambda s: False)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_cloud_reauth", lambda s: None)
    with pytest.raises(RuntimeError):
        _validate_cloud(settings)


# ---------------------------------------------------------------------------
# startup_validate (dispatch)
# ---------------------------------------------------------------------------

def test_startup_validate_cloud_with_valid_probe(monkeypatch) -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL",
        bambulab_cloud_user_id="uid",
        bambulab_cloud_access_token="token",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", lambda _s: True)
    startup_validate(settings)


def test_startup_validate_local_calls_probe(monkeypatch) -> None:
    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SERIAL",
        bambulab_access_code="ACCESS",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", lambda _s: True)
    startup_validate(settings)


def test_startup_validate_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict = {"local": 0, "cloud": 0}
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_local", lambda s: calls.__setitem__("local", 1))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_cloud", lambda s: calls.__setitem__("cloud", 1))

    startup_validate(Settings(bambulab_transport="local_mqtt", bambulab_host="h", bambulab_serial="s", bambulab_access_code="a"))
    startup_validate(Settings(bambulab_transport="cloud_mqtt", bambulab_serial="s", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t"))

    assert calls["local"] == 1
    assert calls["cloud"] == 1
