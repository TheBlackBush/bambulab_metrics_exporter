"""Tests for bambulab_metrics_exporter.cloud_auth."""
from __future__ import annotations

import base64
import io
import json
import os
from argparse import Namespace
from pathlib import Path
from urllib import error
from unittest.mock import MagicMock, patch

import pytest

from bambulab_metrics_exporter import cloud_auth
from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthError,
    CloudAuthInvalidError,
    CloudAuthTransientError,
    _extract_user_id,
    login_with_code,
    refresh_access_token,
    send_code,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {}

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _jwt_with_uid(uid: str) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"uid": uid}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


# ---------------------------------------------------------------------------
# Primitive helpers (_as_int, _extract_user_id)
# ---------------------------------------------------------------------------

def test_as_int_conversions() -> None:
    assert cloud_auth._as_int(5) == 5
    assert cloud_auth._as_int("7") == 7
    assert cloud_auth._as_int(True) == 1
    assert cloud_auth._as_int("bad", default=3) == 3


def test_extract_user_id_from_response() -> None:
    data = {"uid": 1234}
    uid = _extract_user_id(data, "x.y.z", timeout_seconds=1, retries=0, api_bases=[])
    assert uid == "1234"


def test_extract_user_id_from_jwt_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._resolve_user_id_from_profile",
        lambda **_: None,
    )
    uid = _extract_user_id({}, _jwt_with_uid("777"), timeout_seconds=1, retries=0, api_bases=[])
    assert uid == "777"


def test_extract_user_id_from_profile_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._resolve_user_id_from_profile",
        lambda **_: "555",
    )
    uid = _extract_user_id({}, "x.y.z", timeout_seconds=1, retries=0, api_bases=["https://x"])
    assert uid == "555"


# ---------------------------------------------------------------------------
# HTTP helpers (_post_json, _get_json)
# ---------------------------------------------------------------------------

def test_post_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", lambda *a, **k: _Resp({"ok": True}))
    data = cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=0)
    assert data["ok"] is True


def test_post_json_http_403_1010(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"error code: 1010"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)
    with pytest.raises(cloud_auth.CloudAuthError):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=0)


def test_post_json_urlerror_raises_when_retries_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error.URLError("net")),
    )
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda *_: None)
    with pytest.raises(cloud_auth.CloudAuthError):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=0)


def test_post_json_multi_base_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(base: str, *args, **kwargs):
        if base == "https://a":
            raise cloud_auth.CloudAuthError("bad a")
        return {"ok": True}

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth._post_json", fake_post)
    data = cloud_auth._post_json_multi_base("/p", {}, 1, 0, ["https://a", "https://b"])
    assert data["ok"] is True


def test_get_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", lambda *a, **k: _Resp({"uid": 1}))
    data = cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=0, access_token="t")
    assert data["uid"] == 1


def test_get_json_http_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 401, "unauthorized", hdrs=None, fp=io.BytesIO(b"denied"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)
    with pytest.raises(cloud_auth.CloudAuthError):
        cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=0, access_token="t")


def test_resolve_user_id_from_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._get_json",
        lambda *a, **k: {"uid": 99},
    )
    assert cloud_auth._resolve_user_id_from_profile("t", 1, 0, ["https://x"]) == "99"


# ---------------------------------------------------------------------------
# login_with_code / send_code
# ---------------------------------------------------------------------------

def test_login_with_code_parses_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._post_json_multi_base",
        lambda *args, **kwargs: {
            "accessToken": "token123",
            "refreshToken": "refresh123",
            "expiresIn": "3600",
            "uid": 42,
        },
    )
    result = login_with_code("user@example.com", "123456", timeout_seconds=1, retries=0)
    assert result.user_id == "42"
    assert result.access_token == "token123"


def test_login_with_code_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._post_json_multi_base",
        lambda *args, **kwargs: {"error": "bad code"},
    )
    with pytest.raises(CloudAuthError):
        login_with_code("user@example.com", "bad", timeout_seconds=1, retries=0)


def test_send_code_calls_multi_base(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"ok": False}

    def fake_post(*args, **kwargs):
        called["ok"] = True
        return {}

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth._post_json_multi_base", fake_post)
    send_code("user@example.com", timeout_seconds=1, retries=0)
    assert called["ok"] is True


# ---------------------------------------------------------------------------
# Device discovery (get_bind_devices)
# ---------------------------------------------------------------------------

def test_get_bind_devices_success() -> None:
    mock_data = {
        "devices": [
            {"dev_id": "S1", "name": "P1S-Living", "model": "P1S"},
            {"dev_id": "S2", "name": "X1C-Work", "model": "X1C"},
        ]
    }
    with patch("bambulab_metrics_exporter.cloud_auth._get_json", return_value=mock_data):
        devices = cloud_auth.get_bind_devices("tok", 10, 1, ["base"])
        assert len(devices) == 2
        assert devices[0]["dev_id"] == "S1"


def test_cloud_auth_main_discovers_name_model() -> None:
    mock_result = MagicMock()
    mock_result.access_token = "tok"
    mock_result.user_id = "uid"
    mock_result.refresh_token = "ref"

    mock_devices = [{"dev_id": "S123", "name": "MyPrinter", "model": "P1S"}]

    with patch("bambulab_metrics_exporter.cloud_auth.login_with_code", return_value=mock_result):
        with patch("bambulab_metrics_exporter.cloud_auth.get_bind_devices", return_value=mock_devices):
            with patch("bambulab_metrics_exporter.cloud_auth.sync_env_file"):
                with patch("sys.stdout"):
                    with patch("argparse.ArgumentParser.parse_args") as mock_args:
                        mock_args.return_value = MagicMock(
                            email="a@b.com", code="123", send_code=False,
                            serial="S123", save=False, env_file=".env",
                            timeout=10, retries=1, api_bases="base",
                            config_dir="/config", credentials_file="cred.json",
                            secret_key="",
                        )
                        cloud_auth.main()
                        assert os.environ.get("BAMBULAB_PRINTER_NAME") == "MyPrinter"
                        assert os.environ.get("BAMBULAB_PRINTER_MODEL") == "P1S"


# ---------------------------------------------------------------------------
# CLI parser (_build_parser)
# ---------------------------------------------------------------------------

def test_build_parser_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", "/tmp/conf")
    parser = cloud_auth._build_parser()
    args = parser.parse_args(["--email", "user@example.com", "--send-code"])
    assert args.config_dir == "/tmp/conf"


# ---------------------------------------------------------------------------
# main() flows
# ---------------------------------------------------------------------------

def test_main_send_code_flow(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code=None, send_code=True, save=False,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="", env_file=".env", timeout=1, retries=0, api_bases="https://api",
        )})(),
    )
    called = {"ok": False}
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.send_code", lambda *a, **k: called.__setitem__("ok", True))

    rc = cloud_auth.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert called["ok"] is True
    assert "Verification code sent" in out


def test_main_requires_code_when_not_send_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code=None, send_code=False, save=False,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="", env_file=".env", timeout=1, retries=0, api_bases="https://api",
        )})(),
    )
    rc = cloud_auth.main()
    err = capsys.readouterr().err
    assert rc == 2
    assert "--code is required" in err


def test_main_save_requires_secret(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code="123456", send_code=False, save=True,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="SERIAL", env_file=".env", timeout=1, retries=0, api_bases="https://api",
        )})(),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.login_with_code",
        lambda *a, **k: cloud_auth.LoginResult("acc", "ref", 3600, "uid"),
    )
    rc = cloud_auth.main()
    err = capsys.readouterr().err
    assert rc == 2
    assert "--secret-key" in err


def test_main_success_save_and_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code="123456", send_code=False, save=True,
            config_dir=str(tmp_path), credentials_file="c.json", secret_key="sec",
            serial="SERIAL", env_file=str(env_file), timeout=1, retries=0, api_bases="https://api",
        )})(),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.login_with_code",
        lambda *a, **k: cloud_auth.LoginResult("acc", "ref", 3600, "uid"),
    )
    called = {"saved": False, "synced": False}
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.save_encrypted_credentials",
        lambda *a, **k: called.__setitem__("saved", True),
    )
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.sync_env_file", lambda *a, **k: called.__setitem__("synced", True))

    rc = cloud_auth.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert called["saved"] is True
    assert called["synced"] is True
    assert "Cloud credentials ready" in out


def test_main_cloud_auth_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code="123456", send_code=False, save=False,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="", env_file=".env", timeout=1, retries=0, api_bases="https://api",
        )})(),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.login_with_code",
        lambda *a, **k: (_ for _ in ()).throw(cloud_auth.CloudAuthError("boom")),
    )
    rc = cloud_auth.main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "Cloud auth failed" in err


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------

def test_refresh_access_token_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful refresh returns updated LoginResult."""
    response_data = {
        "accessToken": "new_access",
        "refreshToken": "new_refresh",
        "expiresIn": 7200,
        "uid": 42,
    }
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.request.urlopen",
        lambda *a, **k: _Resp(response_data),
    )
    result = refresh_access_token("old_refresh", timeout_seconds=1, retries=0)
    assert result.access_token == "new_access"
    assert result.refresh_token == "new_refresh"
    assert result.expires_in == 7200
    assert result.user_id == "42"


def test_refresh_access_token_invalid_raises_cloud_auth_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 401 from all bases raises CloudAuthInvalidError."""
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 401, "Unauthorized", hdrs=None, fp=io.BytesIO(b"token expired"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)
    with pytest.raises(CloudAuthInvalidError):
        refresh_access_token("bad_refresh", timeout_seconds=1, retries=0, api_bases=["https://a"])


def test_refresh_access_token_server_error_body_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server returns 200 with error body => CloudAuthInvalidError."""
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.request.urlopen",
        lambda *a, **k: _Resp({"error": "invalid_grant"}),
    )
    with pytest.raises(CloudAuthInvalidError):
        refresh_access_token("bad_refresh", timeout_seconds=1, retries=0)


def test_refresh_access_token_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failure raises CloudAuthTransientError."""
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(error.URLError("connection refused")),
    )
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda *_: None)
    with pytest.raises(CloudAuthTransientError):
        refresh_access_token("some_refresh", timeout_seconds=1, retries=0, api_bases=["https://a"])


def test_refresh_access_token_503_raises_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 503 from all bases raises CloudAuthTransientError, not CloudAuthInvalidError."""
    def fail(*args, **kwargs):
        raise error.HTTPError("u", 503, "Service Unavailable", hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda *_: None)
    with pytest.raises(CloudAuthTransientError):
        refresh_access_token("ok_refresh", timeout_seconds=1, retries=0, api_bases=["https://a"])


# ---------------------------------------------------------------------------
# Additional edge cases — retry paths and missing key branches
# ---------------------------------------------------------------------------

def test_as_int_float_input() -> None:
    """_as_int should convert float input."""
    assert cloud_auth._as_int(3.7) == 3


def test_as_int_empty_string() -> None:
    """_as_int should return default for empty string."""
    assert cloud_auth._as_int("", default=42) == 42
    assert cloud_auth._as_int("   ", default=99) == 99


def test_post_json_retries_transient_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json retries on transient HTTP 503 error and eventually succeeds."""
    import io as _io
    import json as _json
    from urllib import error as _error

    call_count = {"n": 0}

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(req, timeout):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise _error.HTTPError("url", 503, "Service Unavailable", hdrs=None, fp=_io.BytesIO(b"retry"))
        return _FakeResp()

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fake_urlopen)

    result = cloud_auth._post_json("https://x", "/path", {}, timeout_seconds=1, retries=2)
    assert result == {"ok": True}
    assert call_count["n"] == 2


def test_post_json_retries_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json raises CloudAuthError after retries exhausted on URLError."""
    from urllib import error as _error

    def fail(*args, **kwargs):
        raise _error.URLError("network down")

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="Network error"):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=1)


def test_post_json_non_transient_http_error_raises_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json raises immediately on non-retryable HTTP error (e.g. 400)."""
    import io as _io
    from urllib import error as _error

    def fail(*args, **kwargs):
        raise _error.HTTPError("u", 400, "Bad Request", hdrs=None, fp=_io.BytesIO(b"bad request"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="HTTP 400"):
        cloud_auth._post_json("https://x", "/p", {}, timeout_seconds=1, retries=3)


def test_post_json_multi_base_all_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_post_json_multi_base raises when all api_bases fail."""
    import io as _io
    from urllib import error as _error

    def fail(*args, **kwargs):
        raise _error.HTTPError("u", 400, "Bad Request", hdrs=None, fp=_io.BytesIO(b"bad"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="All cloud API bases failed"):
        cloud_auth._post_json_multi_base(
            "/path", {}, timeout_seconds=1, retries=0,
            api_bases=["https://a", "https://b"],
        )


def test_get_json_retries_urlerror_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_json raises CloudAuthError after URLError exhausts retries."""
    from urllib import error as _error

    def fail(*args, **kwargs):
        raise _error.URLError("network down")

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="Network error"):
        cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=1, access_token="tok")


def test_get_json_retries_transient_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_json raises after retries exhausted on retryable HTTP error."""
    import io as _io
    from urllib import error as _error

    def fail(*args, **kwargs):
        raise _error.HTTPError("u", 503, "Unavailable", hdrs=None, fp=_io.BytesIO(b"retry"))

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.time.sleep", lambda _: None)
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.request.urlopen", fail)

    with pytest.raises(CloudAuthError, match="HTTP 503"):
        cloud_auth._get_json("https://x", "/p", timeout_seconds=1, retries=1, access_token="tok")


def test_resolve_user_id_from_profile_continues_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """_resolve_user_id_from_profile skips failing api_bases and returns None when all fail."""
    def fail(*args, **kwargs):
        raise CloudAuthError("fail")

    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth._get_json", fail)

    result = cloud_auth._resolve_user_id_from_profile(
        access_token="tok", timeout_seconds=1, retries=0, api_bases=["https://a", "https://b"]
    )
    assert result is None


def test_extract_user_id_from_nested_user_dict() -> None:
    """_extract_user_id can find uid in a nested 'user' dict."""
    data = {"user": {"uid": 999, "id": 888}}
    uid = _extract_user_id(data, "x.y.z", timeout_seconds=1, retries=0, api_bases=[])
    assert uid in ("999", "888")


def test_extract_user_id_from_user_dict_id_key() -> None:
    """_extract_user_id falls back to user.id when user.uid absent."""
    data = {"user": {"id": 777}}
    uid = _extract_user_id(data, "x.y.z", timeout_seconds=1, retries=0, api_bases=[])
    assert uid == "777"


def test_extract_user_id_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """_extract_user_id raises CloudAuthError when no uid found anywhere."""
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._resolve_user_id_from_profile",
        lambda **_: None,
    )
    with pytest.raises(CloudAuthError, match="Missing user id"):
        _extract_user_id({}, "x.y.z", timeout_seconds=1, retries=0, api_bases=["https://a"])


def test_login_with_code_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """login_with_code raises CloudAuthError when response is missing expected key."""
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._post_json_multi_base",
        lambda *a, **kw: {"message": "ok"},  # no accessToken key
    )
    with pytest.raises(CloudAuthError, match="Missing expected response key"):
        cloud_auth.login_with_code(email="a@b.com", code="123456")
