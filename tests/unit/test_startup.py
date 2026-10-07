"""Tests for bambulab_metrics_exporter.startup."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bambulab_metrics_exporter.cloud_auth import CloudAuthInvalidError, CloudAuthTransientError
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.startup import (
    ReauthRequiredError,
    _probe_connection,
    _try_legacy_env_login,
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


def _as_probe(fake):
    """Adapt a bool probe stub to the three-way probe: True -> ok, False -> rejected."""
    from bambulab_metrics_exporter.startup import PROBE_OK, PROBE_REJECTED

    return lambda s: PROBE_OK if fake(s) else PROBE_REJECTED


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
# _try_legacy_env_login
# ---------------------------------------------------------------------------

def _cloud_settings(tmp_path: Path, **overrides) -> Settings:
    values: dict = dict(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="FAKE00TEST000001",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="stale_token",
        bambulab_cloud_refresh_token="stale_refresh",
        bambulab_config_dir=str(tmp_path),
        bambulab_credentials_file="credentials.enc.json",
    )
    values.update(overrides)
    return Settings(**values)


def test_legacy_login_without_email_does_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BAMBULAB_CLOUD_EMAIL", raising=False)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.send_code",
        lambda email: pytest.fail("no code may be sent without an email"),
    )
    assert _try_legacy_env_login(_cloud_settings(tmp_path)) is False


def test_legacy_login_with_code_saves_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    monkeypatch.setenv("BAMBULAB_CLOUD_CODE", "000000")
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "fake-development-key-never-use")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.login_with_code", lambda email, code: _LoginResult()
    )
    settings = _cloud_settings(tmp_path)

    assert _try_legacy_env_login(settings) is True

    # Applied in place, so the client built after startup uses the new token.
    assert settings.bambulab_cloud_access_token == "token"
    assert (tmp_path / "credentials.enc.json").exists()


def test_legacy_login_without_code_sends_one_code_and_returns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    monkeypatch.delenv("BAMBULAB_CLOUD_CODE", raising=False)
    sent: list[str] = []
    monkeypatch.setattr("bambulab_metrics_exporter.startup.send_code", sent.append)

    assert _try_legacy_env_login(_cloud_settings(tmp_path)) is False
    assert sent == ["operator@example.invalid"]


def test_legacy_login_bad_code_returns_false(tmp_path: Path, monkeypatch) -> None:
    from bambulab_metrics_exporter.cloud_auth import CloudAuthError

    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    monkeypatch.setenv("BAMBULAB_CLOUD_CODE", "000000")

    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    monkeypatch.setattr("bambulab_metrics_exporter.startup.login_with_code", reject)
    assert _try_legacy_env_login(_cloud_settings(tmp_path)) is False


def test_legacy_login_send_code_failure_is_not_fatal(tmp_path: Path, monkeypatch) -> None:
    from bambulab_metrics_exporter.cloud_auth import CloudAuthError

    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    monkeypatch.delenv("BAMBULAB_CLOUD_CODE", raising=False)

    def fail(email: str):
        raise CloudAuthError("network down")

    monkeypatch.setattr("bambulab_metrics_exporter.startup.send_code", fail)
    assert _try_legacy_env_login(_cloud_settings(tmp_path)) is False


# ---------------------------------------------------------------------------
# _validate_cloud
# ---------------------------------------------------------------------------

def test_validate_cloud_waits_instead_of_exiting(tmp_path: Path, monkeypatch) -> None:
    settings = _cloud_settings(tmp_path, bambulab_cloud_refresh_token="")
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", _as_probe(lambda s: False))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_legacy_env_login", lambda s: False)

    with pytest.raises(ReauthRequiredError, match="expired"):
        _validate_cloud(settings)


def test_validate_cloud_prefers_newer_store_over_stale_env(tmp_path: Path, monkeypatch) -> None:
    """Stale tokens from a container template must not hide rotated stored tokens."""
    from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "fake-development-key-never-use")
    save_encrypted_credentials(
        tmp_path / "credentials.enc.json",
        "fake-development-key-never-use",
        {
            "BAMBULAB_CLOUD_USER_ID": "u",
            "BAMBULAB_CLOUD_ACCESS_TOKEN": "rotated_token",
            "BAMBULAB_CLOUD_REFRESH_TOKEN": "rotated_refresh",
        },
    )
    settings = _cloud_settings(tmp_path)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._probe",
        _as_probe(lambda s: s.bambulab_cloud_access_token == "rotated_token"),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_token_refresh",
        lambda s, rt: pytest.fail("refresh must not run when stored credentials work"),
    )

    _validate_cloud(settings)

    assert settings.bambulab_cloud_access_token == "rotated_token"
    assert settings.bambulab_cloud_refresh_token == "rotated_refresh"


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
    probed: list[str] = []
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._probe",
        _as_probe(lambda s: probed.append(s.bambulab_transport) or True),
    )
    startup_validate(settings)
    assert probed == ["cloud_mqtt"]


def test_startup_validate_local_calls_probe(monkeypatch) -> None:
    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SERIAL",
        bambulab_access_code="ACCESS",
    )
    probed: list[str] = []
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._probe",
        _as_probe(lambda s: probed.append(s.bambulab_transport) or True),
    )
    startup_validate(settings)
    assert probed == ["local_mqtt"]


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
        lambda path, exclude=(): called.update(synced=True, exclude=set(exclude)),
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
    assert "exclude" in called


# ---------------------------------------------------------------------------
# _validate_cloud: refresh token scenarios
# ---------------------------------------------------------------------------

def test_validate_cloud_valid_refresh_skips_reauth(tmp_path: Path, monkeypatch) -> None:
    probe_calls = {"count": 0}

    def fake_probe(s):
        probe_calls["count"] += 1
        return probe_calls["count"] > 1

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", _as_probe(fake_probe))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_token_refresh", lambda s, rt: None)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_legacy_env_login",
        lambda s: pytest.fail("re-auth must not run when refresh succeeds"),
    )

    _validate_cloud(_cloud_settings(tmp_path))


def test_validate_cloud_invalid_refresh_falls_back_to_reauth(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", _as_probe(lambda s: False))
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_token_refresh",
        lambda s, rt: (_ for _ in ()).throw(CloudAuthInvalidError("refresh rejected")),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_legacy_env_login",
        lambda s: calls.append("legacy") or False,
    )

    with pytest.raises(ReauthRequiredError):
        _validate_cloud(_cloud_settings(tmp_path))

    assert calls == ["legacy"]


def test_validate_cloud_transient_refresh_error_no_reauth(tmp_path: Path, monkeypatch) -> None:
    """A pure outage exits for a later retry and never triggers re-auth or emails."""
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", _as_probe(lambda s: False))
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_token_refresh",
        lambda s, rt: (_ for _ in ()).throw(CloudAuthTransientError("connection refused")),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_legacy_env_login",
        lambda s: pytest.fail("re-auth must not run on a network outage"),
    )

    with pytest.raises(RuntimeError, match="outage"):
        _validate_cloud(_cloud_settings(tmp_path))


def test_validate_cloud_legacy_login_success_returns(tmp_path: Path, monkeypatch) -> None:
    probe_results = iter([False, True])
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._probe", _as_probe(lambda s: next(probe_results))
    )
    legacy_calls: list[bool] = []
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_legacy_env_login",
        lambda s: legacy_calls.append(True) or True,
    )

    _validate_cloud(_cloud_settings(tmp_path, bambulab_cloud_refresh_token=""))
    assert legacy_calls == [True]
    assert next(probe_results, "exhausted") == "exhausted"  # probed before and after login


def test_validate_cloud_refresh_tokens_rejected_by_broker_reaches_reauth(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", _as_probe(lambda s: False))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_token_refresh", lambda s, rt: None)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_legacy_env_login",
        lambda s: calls.append("legacy") or False,
    )

    with pytest.raises(ReauthRequiredError):
        _validate_cloud(_cloud_settings(tmp_path))

    assert calls == ["legacy"]


def test_startup_validate_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict = {"local": 0, "cloud": 0}
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_local", lambda s: calls.__setitem__("local", 1))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_cloud", lambda s: calls.__setitem__("cloud", 1))

    startup_validate(Settings(bambulab_transport="local_mqtt", bambulab_host="h", bambulab_serial="s", bambulab_access_code="a"))
    startup_validate(Settings(bambulab_transport="cloud_mqtt", bambulab_serial="s", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t"))

    assert calls["local"] == 1
    assert calls["cloud"] == 1


# ---------------------------------------------------------------------------
# Additional edge cases: startup token refresh and reauth branches
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


# ---------------------------------------------------------------------------
# Probe classification and outage handling (review fixes)
# ---------------------------------------------------------------------------

class _ProbeClient:
    def __init__(self, raw=None, connected=True, rejected=False, fail=False) -> None:
        self._raw = raw if raw is not None else {}
        self._connected = connected
        self.auth_rejected = rejected
        self._fail = fail

    def connect(self) -> None:
        if self._fail:
            raise OSError("connection refused")

    def disconnect(self) -> None:
        pass

    def fetch_snapshot(self, _timeout: float):
        from bambulab_metrics_exporter.models import PrinterSnapshot

        return PrinterSnapshot(connected=self._connected, raw=self._raw)


@pytest.mark.parametrize(
    ("client", "expected"),
    [
        (_ProbeClient(raw={"print": {}}), "ok"),
        (_ProbeClient(connected=False, rejected=True), "rejected"),
        (_ProbeClient(connected=True, raw={}), "unreachable"),  # printer did not answer
        (_ProbeClient(connected=False), "unreachable"),  # broker down / timeout
        (_ProbeClient(fail=True), "unreachable"),
        (_ProbeClient(fail=True, rejected=True), "rejected"),
    ],
)
def test_probe_classifies_outcomes(monkeypatch, client, expected: str) -> None:
    from bambulab_metrics_exporter.startup import _probe

    monkeypatch.setattr("bambulab_metrics_exporter.startup.build_client", lambda s: client)
    assert _probe(Settings(bambulab_serial="FAKE00TEST000001")) == expected


def _no_reauth(monkeypatch) -> None:
    for name in ("_try_token_refresh", "_try_legacy_env_login"):
        monkeypatch.setattr(
            f"bambulab_metrics_exporter.startup.{name}",
            lambda *a: pytest.fail(f"{name} must not run during an outage"),
        )


def test_unreachable_broker_is_an_outage_not_reauth(tmp_path: Path, monkeypatch) -> None:
    """Valid tokens + broker down or printer off: retry later, never re-auth or email."""
    from bambulab_metrics_exporter.startup import PROBE_UNREACHABLE

    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", lambda s: PROBE_UNREACHABLE)
    _no_reauth(monkeypatch)
    with pytest.raises(RuntimeError, match="unreachable") as exc_info:
        _validate_cloud(_cloud_settings(tmp_path))
    assert not isinstance(exc_info.value, ReauthRequiredError)


def test_unreachable_after_refresh_is_an_outage(tmp_path: Path, monkeypatch) -> None:
    from bambulab_metrics_exporter.startup import PROBE_REJECTED, PROBE_UNREACHABLE

    results = iter([PROBE_REJECTED, PROBE_UNREACHABLE])
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe", lambda s: next(results))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_token_refresh", lambda s, rt: None)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup._try_legacy_env_login",
        lambda s: pytest.fail("no OTP after a refresh that only hit an outage"),
    )
    with pytest.raises(RuntimeError, match="after token refresh"):
        _validate_cloud(_cloud_settings(tmp_path))


def test_legacy_code_sent_once_per_process(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    monkeypatch.delenv("BAMBULAB_CLOUD_CODE", raising=False)
    sent: list[str] = []
    monkeypatch.setattr("bambulab_metrics_exporter.startup.send_code", sent.append)
    settings = _cloud_settings(tmp_path)

    for _ in range(3):  # re-validation after page saves, retries, ...
        assert _try_legacy_env_login(settings) is False
    assert sent == ["operator@example.invalid"]


def test_legacy_code_value_tried_once(tmp_path: Path, monkeypatch) -> None:
    from bambulab_metrics_exporter.cloud_auth import CloudAuthError

    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    monkeypatch.setenv("BAMBULAB_CLOUD_CODE", "000000")
    attempts: list[str] = []

    def reject(email: str, code: str):
        attempts.append(code)
        raise CloudAuthError("code expired")

    monkeypatch.setattr("bambulab_metrics_exporter.startup.login_with_code", reject)
    settings = _cloud_settings(tmp_path)
    assert _try_legacy_env_login(settings) is False
    assert _try_legacy_env_login(settings) is False
    assert attempts == ["000000"]


def test_refresh_persistence_failure_does_not_fail_refresh(tmp_path: Path, monkeypatch) -> None:
    from bambulab_metrics_exporter.cloud_auth import LoginResult

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "fake-development-key-never-use")
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.refresh_access_token",
        lambda rt: LoginResult(access_token="new", refresh_token="r2", expires_in=1, user_id="u"),
    )

    def unwritable(**_kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("bambulab_metrics_exporter.startup.save_encrypted_credentials", unwritable)
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.sync_env_file", lambda p, exclude=(): (_ for _ in ()).throw(OSError())
    )
    settings = _cloud_settings(tmp_path)
    _try_token_refresh(settings, "old")
    assert settings.bambulab_cloud_access_token == "new"


def test_try_token_refresh_keeps_page_overrides_out_of_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the refresh path synced /auth page values into .env, so "Reset to env
    vars" was undone by the next restart."""
    from bambulab_metrics_exporter.cloud_auth import LoginResult

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "my-secret")
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.refresh_access_token",
        lambda rt, **kw: LoginResult(
            access_token="new_access", refresh_token="new_refresh", expires_in=3600,
            user_id="uid99",
        ),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.save_encrypted_credentials", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.startup.overridden_keys",
        lambda: {"BAMBULAB_SERIAL", "BAMBULAB_TRANSPORT"},
    )
    env_file = tmp_path / ".env"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAMBULAB_SERIAL", "PAGESERIAL0001")
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    settings = Settings(
        bambulab_transport="cloud_mqtt", bambulab_serial="PAGESERIAL0001",
        bambulab_cloud_user_id="uid_old", bambulab_cloud_access_token="old_access",
        bambulab_config_dir=str(tmp_path),
    )
    _try_token_refresh(settings, "old_refresh")

    text = env_file.read_text()
    assert "BAMBULAB_CLOUD_ACCESS_TOKEN=new_access" in text
    assert "PAGESERIAL0001" not in text and "BAMBULAB_TRANSPORT" not in text
