"""Tests for bambulab_metrics_exporter.startup."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bambulab_metrics_exporter.cloud_auth import CloudAuthInvalidError, CloudAuthTransientError
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.startup import (
    _probe_connection,
    _try_cloud_reauth,
    _try_token_refresh,
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


# ---------------------------------------------------------------------------
# _try_token_refresh
# ---------------------------------------------------------------------------

def test_try_token_refresh_persists_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful refresh updates env vars and persists encrypted credentials."""
    from bambulab_metrics_exporter.cloud_auth import LoginResult

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "my-secret")

    refreshed_result = LoginResult(
        access_token="new_access",
        refresh_token="new_refresh",
        expires_in=3600,
        user_id="uid99",
    )

    called = {"saved": False, "synced": False}

    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.refresh_access_token",
        lambda rt, **kw: refreshed_result,
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.save_encrypted_credentials",
        lambda path, secret, payload: called.__setitem__("saved", True),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.sync_env_file",
        lambda path: called.__setitem__("synced", True),
    )

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
        bambulab_cloud_user_id="uid_old",
        bambulab_cloud_access_token="old_access",
        bambulab_cloud_refresh_token="old_refresh",
        bambulab_config_dir=str(tmp_path),
        bambulab_credentials_file="credentials.enc.json",
        bambulab_cloud_mqtt_host="us.mqtt.bambulab.com",
        bambulab_cloud_mqtt_port=8883,
    )
    import os
    _try_token_refresh(settings, "old_refresh")

    assert os.environ.get("BAMBULAB_CLOUD_ACCESS_TOKEN") == "new_access"
    assert os.environ.get("BAMBULAB_CLOUD_REFRESH_TOKEN") == "new_refresh"
    assert called["saved"] is True
    assert called["synced"] is True


# ---------------------------------------------------------------------------
# _validate_cloud — refresh token scenarios
# ---------------------------------------------------------------------------

def test_validate_cloud_invalid_access_valid_refresh_skips_2fa(monkeypatch: pytest.MonkeyPatch) -> None:
    """When access token is invalid but refresh succeeds, no 2FA is triggered."""
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad_token",
        bambulab_cloud_refresh_token="valid_refresh",
    )

    # First probe (with bad token) => False; second probe (after refresh) => True
    probe_calls = {"count": 0}
    def fake_probe(s):
        probe_calls["count"] += 1
        return probe_calls["count"] > 1

    reauth_called = {"called": False}

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", fake_probe)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_token_refresh",
        lambda s, rt: None,  # success, no-op
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_cloud_reauth",
        lambda s: reauth_called.__setitem__("called", True),
    )

    _validate_cloud(settings)

    assert reauth_called["called"] is False, "2FA re-auth should NOT be triggered when refresh succeeds"


def test_validate_cloud_invalid_refresh_falls_back_to_2fa(monkeypatch: pytest.MonkeyPatch) -> None:
    """When refresh token is invalid, fallback to email/code re-auth occurs."""
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad_token",
        bambulab_cloud_refresh_token="expired_refresh",
    )

    reauth_called = {"called": False}

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", lambda s: False)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_token_refresh",
        lambda s, rt: (_ for _ in ()).throw(CloudAuthInvalidError("refresh rejected")),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_cloud_reauth",
        lambda s: reauth_called.__setitem__("called", True),
    )

    with pytest.raises(RuntimeError):
        _validate_cloud(settings)

    assert reauth_called["called"] is True, "Fallback to 2FA re-auth should occur after invalid refresh"


def test_validate_cloud_transient_refresh_error_no_2fa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient network error during refresh raises RuntimeError but does NOT trigger 2FA."""
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad_token",
        bambulab_cloud_refresh_token="some_refresh",
    )

    reauth_called = {"called": False}

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", lambda s: False)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_token_refresh",
        lambda s, rt: (_ for _ in ()).throw(CloudAuthTransientError("connection refused")),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_cloud_reauth",
        lambda s: reauth_called.__setitem__("called", True),
    )

    with pytest.raises(RuntimeError, match="transient"):
        _validate_cloud(settings)

    assert reauth_called["called"] is False, "2FA re-auth must NOT be triggered on transient network errors"


def test_startup_validate_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict = {"local": 0, "cloud": 0}
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_local", lambda s: calls.__setitem__("local", 1))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_cloud", lambda s: calls.__setitem__("cloud", 1))

    startup_validate(Settings(bambulab_transport="local_mqtt", bambulab_host="h", bambulab_serial="s", bambulab_access_code="a"))
    startup_validate(Settings(bambulab_transport="cloud_mqtt", bambulab_serial="s", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t"))

    assert calls["local"] == 1
    assert calls["cloud"] == 1


# ---------------------------------------------------------------------------
# Additional edge cases — startup token refresh and reauth branches
# ---------------------------------------------------------------------------

def test_try_token_refresh_no_secret_key_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """_try_token_refresh: when no secret key, skips persistence but doesn't crash."""
    import os
    from bambulab_metrics_exporter.cloud_auth import LoginResult

    result = LoginResult(
        access_token="new_tok",
        refresh_token="new_ref",
        expires_in=3600,
        user_id="uid1",
    )

    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.refresh_access_token",
        lambda rt, **kw: result,
    )
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "old")
    monkeypatch.setenv("BAMBULAB_CLOUD_REFRESH_TOKEN", "old_ref")

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="old",
        bambulab_cloud_refresh_token="old_ref",
    )
    # Should not raise even without secret key
    _try_token_refresh(settings, "old_ref")
    # Env should be updated
    assert os.environ.get("BAMBULAB_CLOUD_ACCESS_TOKEN") == "new_tok"


def test_validate_cloud_refresh_probe_fails_falls_back_to_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """After refresh, if probe still fails, falls back to reauth (covers token-refresh flow)."""
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad",
        bambulab_cloud_refresh_token="valid_ref",
    )

    probe_calls = {"n": 0}
    def fake_probe(s):
        probe_calls["n"] += 1
        return probe_calls["n"] >= 3  # fail twice, succeed on third

    reauth_called = {"called": False}
    def fake_reauth(s):
        reauth_called["called"] = True

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", fake_probe)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_token_refresh", lambda s, rt: None)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_cloud_reauth", fake_reauth)
    monkeypatch.setattr("bambulab_metrics_exporter.startup.Settings", lambda: settings)

    _validate_cloud(settings)
    assert reauth_called["called"] is True


def test_validate_cloud_no_refresh_token_goes_to_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no refresh token, skips refresh and proceeds to reauth."""
    monkeypatch.delenv("BAMBULAB_CLOUD_REFRESH_TOKEN", raising=False)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="bad",
        bambulab_cloud_refresh_token="",
    )

    probe_calls = {"n": 0}
    def fake_probe(s):
        probe_calls["n"] += 1
        return probe_calls["n"] > 1

    reauth_called = {"called": False}
    def fake_reauth(s):
        reauth_called["called"] = True

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", fake_probe)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_cloud_reauth", fake_reauth)
    monkeypatch.setattr("bambulab_metrics_exporter.startup.Settings", lambda: settings)

    _validate_cloud(settings)
    assert reauth_called["called"] is True


def test_try_cloud_reauth_no_code_sends_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """_try_cloud_reauth: when code missing, calls send_code and raises."""
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "user@example.com")
    monkeypatch.delenv("BAMBULAB_CLOUD_CODE", raising=False)

    send_called = {"called": False}
    def fake_send_code(email):
        send_called["called"] = True

    monkeypatch.setattr("bambulab_metrics_exporter.startup.send_code", fake_send_code)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
    )

    with pytest.raises(RuntimeError, match="2FA code was sent"):
        _try_cloud_reauth(settings)

    assert send_called["called"] is True


def test_try_cloud_reauth_no_secret_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_try_cloud_reauth: when secret key missing after login, raises."""
    from bambulab_metrics_exporter.cloud_auth import LoginResult as _LR

    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "user@example.com")
    monkeypatch.setenv("BAMBULAB_CLOUD_CODE", "123456")
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)

    result = _LR(
        access_token="new_tok",
        refresh_token="new_ref",
        expires_in=3600,
        user_id="uid1",
    )
    monkeypatch.setattr("bambulab_metrics_exporter.startup.login_with_code", lambda email, code: result)

    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="S1",
    )

    with pytest.raises(RuntimeError, match="BAMBULAB_SECRET_KEY is required"):
        _try_cloud_reauth(settings)
