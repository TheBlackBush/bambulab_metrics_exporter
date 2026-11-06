"""Tests for the /auth page: saved overrides, page actions, and HTTP routes."""
from __future__ import annotations

import http.client
import logging
import os
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bambulab_metrics_exporter import auth_actions, overrides
from bambulab_metrics_exporter.api import _send_code_button, build_app
from bambulab_metrics_exporter.auth_actions import (
    AuthInputError,
    CloudDevice,
    CloudDeviceList,
    CodeSender,
    add_local_printer,
    remove_printer,
    select_cloud_printers,
)
from bambulab_metrics_exporter.cloud_auth import CloudAuthError, LoginResult
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.printers import MAX_PRINTERS, PrinterConfig, printer_id_for

SECRET = "fake-development-key-never-use"
S1, S2, S3 = "FAKE00TEST000001", "FAKE00TEST000002", "FAKE00TEST000003"
DEV1 = CloudDevice(printer_id_for(S1), S1, "One", "H2D", True)
DEV2 = CloudDevice(printer_id_for(S2), S2, "Two", "X1C", False)
LAN3 = PrinterConfig(
    serial=S3, transport="local_mqtt", host="192.0.2.3", access_code="fake-access-code"
)
ENV_KEYS = (
    *overrides.OVERRIDE_KEYS,
    "BAMBULAB_SECRET_KEY",
    "BAMBULAB_CONFIG_DIR",
    "BAMBULAB_CLOUD_USER_ID",
    "BAMBULAB_CLOUD_ACCESS_TOKEN",
    "BAMBULAB_CLOUD_REFRESH_TOKEN",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    overrides._ORIGINAL_ENV.clear()
    yield
    overrides._ORIGINAL_ENV.clear()


def _login() -> LoginResult:
    return LoginResult(access_token="fresh_token", refresh_token="fresh_refresh", expires_in=1, user_id="u")


# ---------------------------------------------------------------------------
# overrides
# ---------------------------------------------------------------------------

def test_overrides_roundtrip_and_apply(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")  # e.g. from an Unraid template
    assert overrides.save_overrides({"BAMBULAB_TRANSPORT": "local_mqtt", "UNRELATED": "x"}) is True

    assert overrides.load_overrides() == {"BAMBULAB_TRANSPORT": "local_mqtt"}
    assert overrides.apply_overrides_to_env() == ["BAMBULAB_TRANSPORT"]
    assert os.environ["BAMBULAB_TRANSPORT"] == "local_mqtt"  # page settings win

    overrides.restore_original_env()
    assert os.environ["BAMBULAB_TRANSPORT"] == "cloud_mqtt"


def test_overrides_merge_and_clear(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    overrides.save_overrides({"BAMBULAB_HOST": "192.0.2.25"})
    overrides.save_overrides({"BAMBULAB_SERIAL": "FAKE00TEST000001"})
    assert set(overrides.load_overrides()) == {"BAMBULAB_HOST", "BAMBULAB_SERIAL"}
    assert overrides.clear_overrides() is True
    assert overrides.clear_overrides() is False
    assert overrides.load_overrides() == {}


def test_overrides_without_secret_are_not_persisted() -> None:
    assert overrides.save_overrides({"BAMBULAB_HOST": "192.0.2.25"}) is False
    assert not overrides.overrides_path().exists()
    assert overrides.load_overrides() == {}


def test_unreadable_overrides_are_ignored(monkeypatch, caplog) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    overrides.save_overrides({"BAMBULAB_HOST": "192.0.2.25"})
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "another-fake-key")
    assert overrides.load_overrides() == {}
    assert "could not be read" in caplog.text


def test_restore_removes_keys_that_were_unset() -> None:
    overrides.set_env("BAMBULAB_HOST", "192.0.2.25")
    overrides.restore_original_env()
    assert "BAMBULAB_HOST" not in os.environ


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

def test_configure_local_validates_and_persists(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    result = auth_actions.configure_local(" 192.0.2.25 ", "fake00test000001", "fake-access-code", "8883")
    assert result.ok and "overrides the container's env vars" in result.note
    assert os.environ["BAMBULAB_TRANSPORT"] == "local_mqtt"
    assert os.environ["BAMBULAB_SERIAL"] == "FAKE00TEST000001"
    assert overrides.load_overrides()["BAMBULAB_ACCESS_CODE"] == "fake-access-code"
    assert "fake-access-code" not in result.message + result.note


def test_configure_local_without_secret_is_session_only() -> None:
    result = auth_actions.configure_local("192.0.2.25", "FAKE00TEST000001", "fake-access-code")
    assert result.ok and "until the next restart" in result.note


@pytest.mark.parametrize(
    ("host", "serial", "code", "port", "fragment"),
    [
        ("bad host!", "FAKE00TEST000001", "code1234", "", "IP address"),
        ("192.0.2.25", "short", "code1234", "", "serial"),
        ("192.0.2.25", "FAKE00TEST000001", "", "", "access code"),
        ("192.0.2.25", "FAKE00TEST000001", "code1234", "99999", "port"),
    ],
)
def test_configure_local_rejects_bad_input(host, serial, code, port, fragment) -> None:
    with pytest.raises(AuthInputError, match=fragment):
        auth_actions.configure_local(host, serial, code, port)
    assert "BAMBULAB_TRANSPORT" not in os.environ


def test_code_sender_rate_limits(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    sender = CodeSender()
    assert sender.send("operator@example.invalid").ok
    with pytest.raises(AuthInputError, match="Try again"):
        sender.send("operator@example.invalid")
    assert sent == ["operator@example.invalid"]


def test_code_sender_validates_and_reports_failure(monkeypatch) -> None:
    with pytest.raises(AuthInputError):
        CodeSender().send("not-an-email")

    def fail(email: str) -> None:
        raise CloudAuthError("network down")

    monkeypatch.setattr(auth_actions, "send_code", fail)
    result = CodeSender().send("operator@example.invalid")
    assert not result.ok and "network down" in result.message


def test_configure_cloud_single_printer_auto_selected(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "get_bind_devices", lambda token: [{"dev_id": "FAKE00TEST000001"}])

    result = auth_actions.configure_cloud("operator@example.invalid", "000000")

    assert result.ok
    assert "FAK" in result.message and "FAKE00TEST000001" not in result.message
    assert os.environ["BAMBULAB_TRANSPORT"] == "cloud_mqtt"
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"
    assert (Path(os.environ["BAMBULAB_CONFIG_DIR"]) / "credentials.enc.json").exists()


def test_configure_cloud_no_printers_fails(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "get_bind_devices", lambda token: [])
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert not result.ok and "no printers" in result.message
    assert "BAMBULAB_TRANSPORT" not in os.environ


def test_configure_cloud_with_serial_session_only(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "get_bind_devices", lambda token: pytest.fail("serial given"))
    result = auth_actions.configure_cloud("operator@example.invalid", "000000", "fake00test000001")
    assert result.ok and "until the next restart" in result.note
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_configure_cloud_failures(monkeypatch) -> None:
    with pytest.raises(AuthInputError):
        auth_actions.configure_cloud("operator@example.invalid", "")
    with pytest.raises(AuthInputError):
        auth_actions.configure_cloud("operator@example.invalid", "000000", "bad")

    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    assert not auth_actions.configure_cloud("operator@example.invalid", "000000").ok

    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())

    def bind_fails(token: str):
        raise CloudAuthError("bind down")

    monkeypatch.setattr(auth_actions, "get_bind_devices", bind_fails)
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert not result.ok and "printer list failed" in result.message


def test_mask_serial() -> None:
    assert auth_actions.mask_serial("FAKE00TEST000001") == "FAK" + "*" * 13
    assert auth_actions.mask_serial("") == ""


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

class _Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.metrics = ExporterMetrics(printer_name="test", serial=settings.bambulab_serial)
        self.ready = False
        self.reconfigured = 0

    def status(self) -> dict[str, str]:
        return {"state": "auth_required", "message": "Re-authentication required: <b>x</b>",
                "transport": self.settings.bambulab_transport}

    def reconfigure(self) -> None:
        self.reconfigured += 1


def _client(settings: Settings | None = None) -> tuple[TestClient, _Runtime]:
    runtime = _Runtime(settings or Settings(bambulab_serial="FAKE00TEST000001", bambulab_host="192.0.2.25"))
    return TestClient(build_app(runtime=runtime)), runtime


def test_auth_page_renders_status_escaped_and_masked() -> None:
    client, _ = _client()
    resp = client.get("/auth")
    assert resp.status_code == 200
    assert "Login required" in resp.text
    assert "&lt;b&gt;x&lt;/b&gt;" in resp.text  # status text is escaped
    assert "FAK*************" in resp.text and "FAKE00TEST000001" not in resp.text
    assert 'id="mode-local" checked' in resp.text
    assert resp.headers["cache-control"] == "no-store"


def test_auth_page_cloud_tab_selected_in_cloud_mode() -> None:
    client, _ = _client(Settings(bambulab_transport="cloud_mqtt", bambulab_serial="FAKE00TEST000001"))
    assert 'id="mode-cloud" checked' in client.get("/auth").text


def test_auth_status_json() -> None:
    client, _ = _client()
    assert client.get("/auth/status").json()["state"] == "auth_required"


def test_post_local_reconfigures_and_flashes_once() -> None:
    client, runtime = _client()
    resp = client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "fake-access-code"},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/auth"
    assert runtime.reconfigured == 1
    page = client.get("/auth").text
    assert "Local connection saved" in page and "fake-access-code" not in page
    assert "Local connection saved" not in client.get("/auth").text  # shown once


def test_post_invalid_input_shows_error_without_reconfigure() -> None:
    client, runtime = _client()
    page = client.post("/auth/local", data={"host": "", "serial": "", "access_code": ""})
    assert runtime.reconfigured == 0
    assert "IP address" in page.text


def test_post_send_code_does_not_reconfigure(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, runtime = _client()
    page = client.post("/auth/cloud/send-code", data={"email": "operator@example.invalid"})
    assert runtime.reconfigured == 0
    assert "Verification code sent" in page.text


def test_post_cloud_login(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    client, runtime = _client()
    client.post(
        "/auth/cloud/login",
        data={"email": "operator@example.invalid", "code": "000000", "serial": "FAKE00TEST000001"},
    )
    assert runtime.reconfigured == 1


def test_post_reset_restores_env(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    overrides.save_overrides({"BAMBULAB_TRANSPORT": "local_mqtt"})
    overrides.apply_overrides_to_env()
    client, runtime = _client()

    page = client.post("/auth/reset")

    assert os.environ["BAMBULAB_TRANSPORT"] == "cloud_mqtt"
    assert not overrides.overrides_path().exists()
    assert runtime.reconfigured == 1
    assert "Page settings removed" in page.text

    assert "already using env vars" in client.post("/auth/reset").text


def test_cross_origin_post_is_rejected() -> None:
    client, runtime = _client()
    resp = client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "x1234"},
        headers={"Origin": "https://evil.example.invalid"},
    )
    assert resp.status_code == 403
    assert runtime.reconfigured == 0

    null_origin = client.post("/auth/reset", headers={"Origin": "null"})
    assert null_origin.status_code == 403


def test_same_origin_post_is_allowed() -> None:
    client, runtime = _client()
    resp = client.post("/auth/reset", headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert resp.status_code == 303 and runtime.reconfigured == 1


def test_runtime_backed_core_endpoints() -> None:
    client, runtime = _client()
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 503
    runtime.ready = True
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.get("/metrics").status_code == 200
    assert "Warming Up" not in client.get("/").text


def test_build_app_requires_runtime_or_components() -> None:
    with pytest.raises(ValueError):
        build_app()


def test_landing_page_escapes_printer_name() -> None:
    settings = Settings(bambulab_serial="FAKE00TEST000001", printer_name_label="<script>x</script>")
    client, _ = _client(settings)
    page = client.get("/").text
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page


def test_cloud_form_has_single_email_field_and_login_as_default_button() -> None:
    client, _ = _client()
    page = client.get("/auth").text
    start = page.index('class="card panel panel-cloud"')
    cloud = page[start:page.index("</form>", start)]
    assert cloud.count('name="email"') == 1
    first_button = cloud[cloud.index("<button"):cloud.index("</button>")]
    assert "Log in" in first_button and "formaction" not in first_button
    assert 'formaction="/auth/cloud/send-code"' in cloud


def test_send_code_keeps_email_filled_and_cloud_tab_selected(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, _ = _client()  # local mode, so the cloud tab must be selected explicitly
    resp = client.post("/auth/cloud/send-code", data={"email": "operator@example.invalid"})
    assert resp.status_code == 200
    assert 'value="operator@example.invalid"' in resp.text
    assert 'id="mode-cloud" checked' in resp.text
    assert "Verification code sent" in resp.text
    # Nothing is stored: a fresh page load has an empty email field.
    assert 'value="operator@example.invalid"' not in client.get("/auth").text


def test_failed_cloud_login_keeps_email(monkeypatch) -> None:
    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    client, runtime = _client()
    resp = client.post(
        "/auth/cloud/login", data={"email": "operator@example.invalid", "code": "000000"}
    )
    assert resp.status_code == 200 and runtime.reconfigured == 0
    assert 'value="operator@example.invalid"' in resp.text and "Login failed" in resp.text


def test_echoed_email_is_escaped() -> None:
    client, _ = _client()
    resp = client.post("/auth/cloud/send-code", data={"email": '"><script>x</script>'})
    assert "<script>x</script>" not in resp.text
    assert "&quot;&gt;&lt;script&gt;" in resp.text


def test_cloud_post_cross_origin_rejected() -> None:
    client, _ = _client()
    resp = client.post(
        "/auth/cloud/send-code",
        data={"email": "operator@example.invalid"},
        headers={"Origin": "https://evil.example.invalid"},
    )
    assert resp.status_code == 403



def test_notice_is_rendered_inside_status_card_with_note() -> None:
    client, _ = _client()
    page = client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "fake-access-code"},
    ).text
    status_card = page[page.index('<span class="label">Status</span>'):page.index('role="radiogroup"')]
    assert 'class="notice ok"' in status_card
    assert 'class="notice-note"' in status_card and "Applies until the next restart" in status_card
    assert "Connecting..." not in page


def test_error_notice_uses_bad_style() -> None:
    client, _ = _client()
    page = client.post("/auth/local", data={"host": "", "serial": "", "access_code": ""}).text
    assert 'class="notice bad"' in page


def test_page_auto_refreshes_only_while_connecting() -> None:
    client, runtime = _client()
    assert 'http-equiv="refresh"' not in client.get("/auth").text  # auth_required

    runtime.status = lambda: {"state": "connecting", "message": "", "transport": "local_mqtt"}
    client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "fake-access-code"},
    )
    page = client.get("/auth").text
    assert '<meta http-equiv="refresh" content="3;url=/auth">' in page
    # The result stays visible across refreshes until the connection settles.
    assert "Local connection saved" in client.get("/auth").text

    runtime.status = lambda: {"state": "running", "message": "", "transport": "local_mqtt"}
    settled = client.get("/auth").text
    assert 'http-equiv="refresh"' not in settled and "Local connection saved" in settled
    assert "Local connection saved" not in client.get("/auth").text


# ---------------------------------------------------------------------------
# Review fixes: credential backup, .env exclusion, page security
# ---------------------------------------------------------------------------

def test_credentials_backup_and_restore(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.enc.json"
    creds.write_bytes(b"operator-tokens")
    overrides.backup_credentials(creds)
    creds.write_bytes(b"page-login-tokens")
    overrides.backup_credentials(creds)  # second login keeps the first backup
    assert overrides.restore_credentials_backup(creds) is True
    assert creds.read_bytes() == b"operator-tokens"
    assert overrides.restore_credentials_backup(creds) is False


def test_credentials_backup_when_none_existed(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.enc.json"
    overrides.backup_credentials(creds)
    creds.write_bytes(b"page-login-tokens")
    assert overrides.restore_credentials_backup(creds) is True
    assert not creds.exists()


def test_reset_undoes_page_cloud_login(monkeypatch, tmp_path: Path) -> None:
    """Regression: reset left another account's tokens in env and in the store."""
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "operator_token")
    creds = tmp_path / "credentials.enc.json"
    creds.write_bytes(b"operator-store")
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    client, _ = _client()
    client.post(
        "/auth/cloud/login",
        data={"email": "operator@example.invalid", "code": "000000", "serial": "FAKE00TEST000001"},
    )
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"

    client.post("/auth/reset")
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "operator_token"
    assert creds.read_bytes() == b"operator-store"


def test_env_sync_exclude_keeps_file_values(tmp_path: Path, monkeypatch) -> None:
    from bambulab_metrics_exporter.env_sync import sync_env_file

    env_file = tmp_path / ".env"
    env_file.write_text("BAMBULAB_HOST=192.0.2.10\n")
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.99")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "page-code")
    sync_env_file(env_file, exclude={"BAMBULAB_HOST", "BAMBULAB_ACCESS_CODE"})
    text = env_file.read_text()
    assert "BAMBULAB_HOST=192.0.2.10" in text and "page-code" not in text


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("192.0.2.25:9109", True),
        ("[::1]:9109", True),
        ("localhost:9109", True),
        ("tower:9109", True),
        ("tower.local:9109", True),
        ("nas.home.arpa", True),
        ("exporter.example.com", False),
        ("evil.example:9109", False),
        ("", False),
    ],
)
def test_host_allowlist(host: str, allowed: bool) -> None:
    from bambulab_metrics_exporter.api import _host_allowed

    assert _host_allowed(host, set()) is allowed


def test_auth_rejects_public_host_names() -> None:
    """DNS rebinding: a page on a public domain re-pointed at the exporter is refused."""
    client, runtime = _client()
    headers = {"Host": "evil.example:9109", "Origin": "http://evil.example:9109"}
    assert client.get("/auth", headers=headers).status_code == 403
    assert client.get("/auth/status", headers=headers).status_code == 403
    resp = client.post("/auth/reset", headers=headers)
    assert resp.status_code == 403 and runtime.reconfigured == 0


def test_auth_allowed_hosts_setting() -> None:
    settings = Settings(
        bambulab_serial="FAKE00TEST000001", auth_allowed_hosts="exporter.example.com, other.example"
    )
    client, _ = _client(settings)
    assert client.get("/auth", headers={"Host": "exporter.example.com"}).status_code == 200


def test_security_headers_on_all_pages() -> None:
    client, _ = _client()
    for path in ("/", "/auth", "/metrics", "/health"):
        resp = client.get(path)
        assert resp.headers["x-frame-options"] == "DENY", path
        assert "frame-ancestors 'none'" in resp.headers["content-security-policy"], path


def test_oversized_form_is_rejected() -> None:
    client, runtime = _client()
    resp = client.post("/auth/local", data={"host": "x" * 10000})
    assert resp.status_code == 413 and runtime.reconfigured == 0


def test_login_attempts_are_limited(monkeypatch) -> None:
    from bambulab_metrics_exporter.cloud_auth import CloudAuthError

    calls = {"n": 0}

    def reject(email: str, code: str):
        calls["n"] += 1
        raise CloudAuthError("bad code")

    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    client, _ = _client()
    for _ in range(6):
        page = client.post(
            "/auth/cloud/login", data={"email": "operator@example.invalid", "code": "000000"}
        ).text
    assert calls["n"] == 5
    assert "Too many login attempts" in page


def test_results_are_per_visitor() -> None:
    client, _ = _client()
    client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "fake-access-code"},
        follow_redirects=False,
    )
    other_visitor = TestClient(client.app)
    assert "Local connection saved" not in other_visitor.get("/auth").text
    assert "Local connection saved" in client.get("/auth").text


def test_save_error_shows_notice_instead_of_500(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)

    def unwritable(_values):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(auth_actions, "save_overrides", unwritable)
    client, runtime = _client()
    resp = client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "fake-access-code"},
    )
    assert resp.status_code == 200
    assert "Could not save the settings: Permission denied" in resp.text
    assert runtime.reconfigured == 0


def test_page_after_a_press_is_a_single_view_without_auto_reload(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, runtime = _client()
    runtime.status = lambda: {"state": "connecting", "message": "", "transport": "local_mqtt"}
    _post_send(client)
    page = client.get("/auth").text
    assert f'value="{EMAIL}"' in page and 'http-equiv="refresh"' not in page
    _assert_timer_shown(page)
    page = client.get("/auth").text
    assert EMAIL not in page and 'http-equiv="refresh"' in page
    _assert_timer_hidden(page)


def test_email_is_escaped_after_the_redirect(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, _ = _client()
    client.post("/auth/cloud/send-code", data={"email": '"><script>x@example.invalid'})
    page = client.get("/auth").text
    assert "<script>x@" not in page


def test_streamed_form_without_length_is_capped() -> None:
    """A chunked body has no Content-Length; the streamed size is still capped at 8 KB."""
    client, runtime = _client()

    def body():
        yield b"host=" + b"a" * 5000
        yield b"a" * 5000

    resp = client.post(
        "/auth/local", content=body(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 413 and runtime.reconfigured == 0


def test_flash_store_keeps_only_recent_visitors() -> None:
    client, _ = _client()
    message = "already using env vars"
    tokens = [f"visitor-token-{i:04d}" for i in range(65)]
    for token in tokens:
        client.cookies.set("bme_auth", token)
        client.post("/auth/reset", follow_redirects=False)
    client.cookies.set("bme_auth", tokens[0])
    assert message not in client.get("/auth").text  # oldest evicted (limit 64)
    client.cookies.set("bme_auth", tokens[-1])
    assert message in client.get("/auth").text


def test_short_error_truncates_and_prefers_os_reason() -> None:
    from bambulab_metrics_exporter.api import _short_error

    assert _short_error(OSError(13, "Permission denied")) == "Permission denied"
    assert len(_short_error(ValueError("x" * 500))) == 200


def test_page_cloud_login_tokens_stay_out_of_env_file(monkeypatch, tmp_path: Path) -> None:
    """Page-login tokens live in the encrypted store only, so .env never carries another
    account's tokens and reset fully returns to the container's credentials."""
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    client, _ = _client()
    client.post(
        "/auth/cloud/login",
        data={"email": "operator@example.invalid", "code": "000000", "serial": "FAKE00TEST000001"},
    )
    assert set(overrides.CLOUD_CREDENTIAL_KEYS) <= overrides.overridden_keys()

    # Simulated restart: the process forgets what it recorded; the backup file remains.
    overrides._ORIGINAL_ENV.clear()
    assert overrides.page_login_active()
    assert set(overrides.CLOUD_CREDENTIAL_KEYS) <= overrides.overridden_keys()


def test_page_cloud_login_survives_restart_and_reset_restores_env(
    monkeypatch, tmp_path: Path
) -> None:
    from bambulab_metrics_exporter import main

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_CLOUD_USER_ID", "operator_uid")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "operator_token")
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    client, _ = _client()
    client.post(
        "/auth/cloud/login",
        data={"email": "operator@example.invalid", "code": "000000", "serial": "FAKE00TEST000001"},
    )

    # Restart: the container env carries its own tokens again, page settings are re-applied.
    overrides.restore_original_env()
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "operator_token"
    overrides.apply_overrides_to_env()
    main._bootstrap_cloud_credentials()
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"  # page login wins

    client.post("/auth/reset")
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "operator_token"
    assert os.environ["BAMBULAB_CLOUD_USER_ID"] == "operator_uid"
    assert not overrides.page_login_active()


def test_successful_page_login_resets_send_code_limit(monkeypatch, tmp_path) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(
        auth_actions, "get_bind_devices", lambda token: [{"dev_id": "FAKE00TEST000001"}]
    )
    client, _ = _client()
    email = "operator@example.invalid"

    client.post("/auth/cloud/send-code", data={"email": email})
    client.post("/auth/cloud/send-code", data={"email": email})
    assert sent == [email]  # second press is inside the 60 s spacing

    client.post("/auth/cloud/login", data={"email": email, "code": "123456"})
    client.post("/auth/cloud/send-code", data={"email": email})
    assert sent == [email, email]


def test_failed_page_login_keeps_send_code_limit(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)

    def reject(email: str, code: str) -> LoginResult:
        raise CloudAuthError("bad code")

    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    client, _ = _client()
    email = "operator@example.invalid"
    client.post("/auth/cloud/send-code", data={"email": email})
    client.post("/auth/cloud/login", data={"email": email, "code": "123456"})
    client.post("/auth/cloud/send-code", data={"email": email})
    assert sent == [email]


def test_reset_and_local_do_not_clear_the_send_code_ladder(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    client.post("/auth/cloud/send-code", data={"email": "operator@example.invalid"})
    client.post("/auth/reset")
    client.post(
        "/auth/local",
        data={"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": "fake-access-code"},
    )
    page = client.post("/auth/cloud/send-code", data={"email": "operator@example.invalid"})
    assert "A code was just sent" in page.text
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# send-code button shows the wait
# ---------------------------------------------------------------------------

def test_send_code_button_attributes_and_label() -> None:
    assert _send_code_button(0) == ("", "Send code")
    assert _send_code_button(42) == (' disabled data-wait="42"', "Send code (42s)")
    assert _send_code_button(60) == (' disabled data-wait="60"', "Send code (60s)")
    assert _send_code_button(61) == (' disabled data-wait="61"', "Send code (1m 1s)")
    assert _send_code_button(570) == (' disabled data-wait="570"', "Send code (9m 30s)")


def test_send_code_button_is_enabled_without_a_wait() -> None:
    page = _client()[0].get("/auth").text
    button = page[page.index('id="send-code"'):]
    button = button[: button.index(">")]
    assert "disabled" not in button and "data-wait" not in button
    assert '<span id="send-code-label">Send code</span>' in page


def _send_button(page: str) -> str:
    start = page.index('id="send-code"')
    return page[start: page.index(">", start)]


def _assert_timer_hidden(page: str) -> None:
    assert "disabled" not in _send_button(page) and 'data-wait="' not in page
    assert '<span id="send-code-label">Send code</span>' in page


def _assert_timer_shown(page: str) -> None:
    assert "disabled" in _send_button(page) and 'data-wait="' in page
    assert "Send code (" in page


EMAIL = "operator@example.invalid"


def _post_send(client: TestClient):
    return client.post(
        "/auth/cloud/send-code", data={"email": EMAIL}, follow_redirects=False
    )


def test_send_code_post_redirects_and_the_next_view_shows_the_wait(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    resp = _post_send(client)
    assert resp.status_code == 303 and resp.headers["location"] == "/auth"
    page = client.get("/auth").text
    assert f'value="{EMAIL}"' in page
    assert "Verification code sent" in page
    _assert_timer_shown(page)
    assert sent == [EMAIL]


def test_refresh_after_a_press_shows_an_active_button_and_sends_nothing(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    _assert_timer_hidden(client.get("/auth").text)  # fresh page
    _post_send(client)
    client.get("/auth")
    page = client.get("/auth").text  # a refresh
    _assert_timer_hidden(page)
    assert EMAIL not in page
    assert len(sent) == 1


def test_press_after_reload_is_refused_and_shows_the_timer(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    _post_send(client)
    client.get("/auth")
    resp = _post_send(client)
    assert resp.status_code == 303
    page = client.get("/auth").text
    assert "A code was just sent" in page
    assert len(sent) == 1
    _assert_timer_shown(page)
    assert f'value="{EMAIL}"' in page


def test_invalid_send_code_input_redirects(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, _ = _client()
    resp = client.post(
        "/auth/cloud/send-code", data={"email": "not-an-email"}, follow_redirects=False
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/auth"


def test_another_visitor_never_sees_the_email_or_timer(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, _ = _client()
    _post_send(client)
    other = TestClient(client.app)
    page = other.get("/auth").text
    assert EMAIL not in page
    _assert_timer_hidden(page)


def test_failed_login_redirects_and_keeps_email_and_timer(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)

    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    client, _ = _client()
    _post_send(client)
    resp = client.post(
        "/auth/cloud/login", data={"email": EMAIL, "code": "000000"}, follow_redirects=False
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/auth"
    page = client.get("/auth").text
    assert "Login failed" in page and f'value="{EMAIL}"' in page
    _assert_timer_shown(page)


def test_forced_post_during_the_wait_is_still_refused(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    email = "operator@example.invalid"
    client.post("/auth/cloud/send-code", data={"email": email})
    resp = client.post("/auth/cloud/send-code", data={"email": email})
    assert "A code was just sent" in resp.text
    assert sent == [email]


# ---------------------------------------------------------------------------
# background send (Accept: application/json)
# ---------------------------------------------------------------------------

_JSON = {"Accept": "application/json"}


def test_json_send_code_stays_on_the_page(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    resp = client.post(
        "/auth/cloud/send-code", data={"email": EMAIL}, headers=_JSON, follow_redirects=False
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["message"]
    assert 50 <= body["wait_seconds"] <= 60
    assert sent == [EMAIL]
    assert EMAIL not in resp.text
    assert resp.headers["cache-control"] == "no-store"
    page = client.get("/auth").text  # no flash was stored
    _assert_timer_hidden(page)
    assert EMAIL not in page


def test_json_send_code_during_a_wait_is_refused(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    client.post("/auth/cloud/send-code", data={"email": EMAIL}, headers=_JSON)
    resp = client.post("/auth/cloud/send-code", data={"email": EMAIL}, headers=_JSON)
    body = resp.json()
    assert resp.status_code == 200 and body["ok"] is False and body["wait_seconds"] > 0
    assert len(sent) == 1


def test_json_send_code_invalid_email(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(auth_actions, "send_code", sent.append)
    client, _ = _client()
    resp = client.post("/auth/cloud/send-code", data={"email": "nope"}, headers=_JSON)
    assert resp.json()["ok"] is False and sent == []


def test_json_send_code_keeps_the_guards() -> None:
    client, _ = _client()
    cross = client.post(
        "/auth/cloud/send-code",
        data={"email": EMAIL},
        headers={**_JSON, "Origin": "https://evil.example.invalid"},
    )
    assert cross.status_code == 403
    bad_host = client.post(
        "/auth/cloud/send-code",
        data={"email": EMAIL},
        headers={**_JSON, "Host": "evil.example:9109", "Origin": "http://evil.example:9109"},
    )
    assert bad_host.status_code == 403
    big = client.post("/auth/cloud/send-code", data={"email": "x" * 10000}, headers=_JSON)
    assert big.status_code == 413


def test_send_code_without_the_json_header_still_redirects(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, _ = _client()
    assert _post_send(client).status_code == 303


# ---------------------------------------------------------------------------
# every /auth action in the background (Accept: application/json)
# ---------------------------------------------------------------------------

ACCESS_CODE = "fake-access-code"
_LOCAL_FORM = {"host": "192.0.2.25", "serial": "FAKE00TEST000001", "access_code": ACCESS_CODE}
_ROUTES = {
    "/auth/local": _LOCAL_FORM,
    "/auth/cloud/send-code": {"email": EMAIL},
    "/auth/cloud/login": {"email": EMAIL, "code": "123456"},
    "/auth/reset": {},
}


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(
        auth_actions, "get_bind_devices", lambda token: [{"dev_id": "FAKE00TEST000001"}]
    )


@pytest.mark.parametrize("path", list(_ROUTES))
def test_json_post_answers_without_redirect_or_flash(stubbed, path) -> None:
    client, runtime = _client()
    resp = client.post(path, data=_ROUTES[path], headers=_JSON, follow_redirects=False)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["message"]
    assert ("wait_seconds" in body) == (path == "/auth/cloud/send-code")
    assert resp.headers["cache-control"] == "no-store"
    for secret in (EMAIL, ACCESS_CODE, "123456", "fresh_token"):
        assert secret not in resp.text
    assert (runtime.reconfigured == 1) == (path != "/auth/cloud/send-code")
    page = client.get("/auth").text  # no flash was stored
    assert body["message"] not in page and EMAIL not in page
    _assert_timer_hidden(page)


@pytest.mark.parametrize("path", list(_ROUTES))
def test_post_without_the_json_header_redirects(stubbed, path) -> None:
    client, _ = _client()
    resp = client.post(path, data=_ROUTES[path], follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/auth"


def test_json_login_success_resets_the_send_code_wait(stubbed) -> None:
    client, runtime = _client()
    client.post("/auth/cloud/send-code", data={"email": EMAIL}, headers=_JSON)
    refused = client.post("/auth/cloud/send-code", data={"email": EMAIL}, headers=_JSON)
    assert refused.json()["ok"] is False
    login = client.post("/auth/cloud/login", data=_ROUTES["/auth/cloud/login"], headers=_JSON)
    assert login.json()["ok"] is True and runtime.reconfigured == 1
    again = client.post("/auth/cloud/send-code", data={"email": EMAIL}, headers=_JSON)
    assert again.json()["ok"] is True


def test_json_login_failure_is_not_ok(monkeypatch) -> None:
    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    client, runtime = _client()
    resp = client.post("/auth/cloud/login", data=_ROUTES["/auth/cloud/login"], headers=_JSON)
    assert resp.status_code == 200 and resp.json()["ok"] is False
    assert runtime.reconfigured == 0
    assert "123456" not in resp.text and EMAIL not in resp.text


@pytest.mark.parametrize("path", list(_ROUTES))
def test_json_post_keeps_every_guard(path) -> None:
    client, runtime = _client()
    data = _ROUTES[path]
    cross = client.post(
        path, data=data, headers={**_JSON, "Origin": "https://evil.example.invalid"}
    )
    assert cross.status_code == 403
    bad_host = client.post(
        path,
        data=data,
        headers={**_JSON, "Host": "evil.example:9109", "Origin": "http://evil.example:9109"},
    )
    assert bad_host.status_code == 403
    big = client.post(path, data={**data, "pad": "x" * 10000}, headers=_JSON)
    assert big.status_code == 413
    assert runtime.reconfigured == 0


def test_auth_page_status_card_is_live_and_refresh_is_noscript_only() -> None:
    client, runtime = _client()
    page = client.get("/auth").text
    assert 'id="status-card" data-live' in page and "data-refresh" not in page.split("<script>")[0]
    assert 'http-equiv="refresh"' not in page
    runtime.status = lambda: {"state": "connecting", "message": "", "transport": "local_mqtt"}
    page = client.get("/auth").text
    assert 'id="status-card" data-live data-refresh="1"' in page
    meta = page.index('http-equiv="refresh"')
    assert page.rindex("<noscript>", 0, meta) > page.rfind("</noscript>", 0, meta)
    assert meta < page.index("</noscript>", meta) < page.index("<style>")
    assert page.count('http-equiv="refresh"') == 1
    assert '<div id="page-notice" role="status" aria-live="polite"></div>' in page


def test_json_reply_carries_the_note(monkeypatch) -> None:
    from bambulab_metrics_exporter import api

    note = "Applies until the next restart. Set BAMBULAB_SECRET_KEY to keep it."
    monkeypatch.setattr(
        api, "configure_local", lambda *a, **k: auth_actions.ActionResult(True, "Saved.", note)
    )
    client, _ = _client()
    resp = client.post("/auth/local", data=_LOCAL_FORM, headers=_JSON)
    assert resp.json() == {"ok": True, "message": "Saved.", "note": note}


def test_page_script_reads_the_formaction_attribute() -> None:
    """The formAction property falls back to the page URL when the attribute is absent."""
    script = _client()[0].get("/auth").text.split("<script>")[1]
    assert 'getAttribute("formaction")' in script
    assert ".formAction" not in script


# ---------------------------------------------------------------------------
# printer list actions and the cloud device list
# ---------------------------------------------------------------------------

def test_select_keeps_lan_printers_and_replaces_cloud_choice() -> None:
    current = [LAN3, PrinterConfig(serial=S1, transport="cloud_mqtt", name="One")]
    result = select_cloud_printers(current, [DEV1, DEV2], {DEV2.printer_id})
    assert [(p.serial, p.transport, p.name, p.model) for p in result] == [
        (S3, "local_mqtt", "", ""), (S2, "cloud_mqtt", "Two", "X1C"),
    ]


def test_select_rejects_unknown_id() -> None:
    with pytest.raises(AuthInputError, match="no longer on this account"):
        select_cloud_printers([], [DEV1], {"000000000000"})


def test_select_rejects_a_printer_already_on_lan() -> None:
    dev = CloudDevice(printer_id_for(S3), S3, "Three", "H2D", True)
    with pytest.raises(AuthInputError, match="already added") as caught:
        select_cloud_printers([LAN3], [dev], {dev.printer_id})
    assert S3 not in str(caught.value)


def test_select_enforces_limit() -> None:
    current = [
        PrinterConfig(serial=f"FAKE00LAN{i:07d}", transport="local_mqtt", host="192.0.2.9")
        for i in range(MAX_PRINTERS)
    ]
    with pytest.raises(AuthInputError, match=str(MAX_PRINTERS)):
        select_cloud_printers(current, [DEV1], {DEV1.printer_id})


def test_select_keeps_env_printer_flag_when_still_selected() -> None:
    current = [PrinterConfig(serial=S1, transport="cloud_mqtt", env_printer=True)]
    assert select_cloud_printers(current, [DEV1], {DEV1.printer_id})[0].env_printer is True


def test_add_local_printer_validates_and_appends() -> None:
    result = add_local_printer([], "192.0.2.25", S1.lower(), "fake-access-code", "8883", "Garage")
    assert (result[0].serial, result[0].name, result[0].port) == (S1, "Garage", 8883)
    with pytest.raises(AuthInputError):
        add_local_printer([], "bad host", S1, "fake-access-code")
    with pytest.raises(AuthInputError):
        add_local_printer([], "192.0.2.25", "short", "fake-access-code")
    with pytest.raises(AuthInputError):
        add_local_printer([], "192.0.2.25", S1, "x")


@pytest.mark.parametrize("port", ["0", "65536", "abc", "\u00b2", "9" * 5000])
def test_add_local_printer_rejects_bad_port(port: str) -> None:
    with pytest.raises(AuthInputError, match="port"):
        add_local_printer([], "192.0.2.25", S1, "fake-access-code", port)


def test_add_local_printer_updates_same_serial_on_lan() -> None:
    result = add_local_printer([LAN3], "192.0.2.77", S3, "another-fake-code")
    assert len(result) == 1 and result[0].host == "192.0.2.77"


def test_add_local_printer_rejects_serial_on_cloud() -> None:
    current = [PrinterConfig(serial=S1, transport="cloud_mqtt")]
    with pytest.raises(AuthInputError, match="already added") as caught:
        add_local_printer(current, "192.0.2.25", S1, "fake-access-code")
    assert S1 not in str(caught.value)


def test_add_local_printer_name_is_bounded() -> None:
    with pytest.raises(AuthInputError):
        add_local_printer([], "192.0.2.25", S1, "fake-access-code", "", "x" * 65)


def test_add_local_printer_enforces_limit() -> None:
    current = [
        PrinterConfig(serial=f"FAKE00LAN{i:07d}", transport="local_mqtt", host="192.0.2.9")
        for i in range(MAX_PRINTERS)
    ]
    with pytest.raises(AuthInputError, match=str(MAX_PRINTERS)):
        add_local_printer(current, "192.0.2.25", S1, "fake-access-code")


def test_remove_printer() -> None:
    assert remove_printer([LAN3], LAN3.printer_id) == []
    with pytest.raises(AuthInputError):
        remove_printer([LAN3], "000000000000")


def test_device_list_caches_and_peek_never_fetches(monkeypatch) -> None:
    calls: list[str] = []

    def fake(token: str, **_kw: object) -> list[dict]:
        calls.append(token)
        return [
            {"dev_id": S1, "name": "One", "dev_product_name": "H2D", "online": True},
            {"dev_id": "", "name": "bad"},
            "garbage",
        ]

    monkeypatch.setattr(auth_actions, "get_bind_devices", fake)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    now = [0.0]
    devices = CloudDeviceList(clock=lambda: now[0])
    assert devices.peek() == []
    assert calls == []
    devices.refresh()
    devices.refresh()
    assert calls == ["fake-access-token"]
    assert [(d.serial, d.model, d.online) for d in devices.peek()] == [(S1, "H2D", True)]
    now[0] = 61.0
    devices.refresh()
    assert len(calls) == 2
    devices.clear()
    assert devices.peek() == []


def test_device_list_without_token_does_nothing(monkeypatch) -> None:
    def fail(*_a: object, **_k: object) -> list[dict]:
        raise AssertionError("must not fetch")

    monkeypatch.setattr(auth_actions, "get_bind_devices", fail)
    CloudDeviceList().refresh()


def test_device_list_failure_is_cached_as_empty(monkeypatch) -> None:
    calls: list[int] = []

    def boom(*_a: object, **_k: object) -> list[dict]:
        calls.append(1)
        raise CloudAuthError("network down")

    monkeypatch.setattr(auth_actions, "get_bind_devices", boom)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    devices = CloudDeviceList(clock=lambda: 0.0)
    devices.refresh()
    devices.refresh()
    assert devices.peek() == [] and len(calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        ValueError("not json: fake-response-body"),
        UnicodeDecodeError("utf-8", b"x", 0, 1, "fake-response-body"),
        AttributeError("fake-response-body"),
        TimeoutError("fake-response-body"),
        http.client.IncompleteRead(b"fake-response-body"),
        RecursionError("fake-response-body"),
    ],
)
def test_device_list_unexpected_error_stays_inside_refresh(monkeypatch, caplog, error) -> None:
    """Bad bytes from Bambu Cloud must not fail the page load, or reach the log."""

    def boom(*_a: object, **_k: object) -> list[dict]:
        raise error

    monkeypatch.setattr(auth_actions, "get_bind_devices", boom)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    devices = CloudDeviceList()
    with caplog.at_level(logging.WARNING):
        devices.refresh()
    assert devices.peek() == []
    assert "Could not read the printer list" in caplog.text
    assert "fake-response-body" not in caplog.text


def test_device_list_treats_the_payload_as_untrusted(monkeypatch) -> None:
    payload = [
        {"dev_id": S1 + "\n", "name": "newline serial"},
        {"dev_id": "bad serial!", "name": "bad"},
        {"dev_id": ["FAKE00TEST000004"], "name": "list serial"},
        {"dev_id": S1, "name": "x" * 500, "dev_product_name": "y" * 500, "online": "yes"},
        {"dev_id": S1, "name": "duplicate"},
        {"dev_id": S2, "name": "bad\ud800name", "model": "X1C"},
        {"dev_id": S3, "name": "<script>", "dev_product_name": None},
    ]
    monkeypatch.setattr(auth_actions, "get_bind_devices", lambda token, **_k: payload)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    devices = CloudDeviceList()
    devices.refresh()
    first, second, third = devices.peek()
    assert (first.serial, first.name, first.model) == (S1, "x" * 64, "y" * 32)
    assert first.online is False
    assert second.serial == S2 and second.model == "X1C"
    second.name.encode("utf-8")  # A stray surrogate would break the page and /metrics.
    assert (third.name, third.model) == ("<script>", "")


def test_select_with_a_repeated_device_adds_it_once() -> None:
    result = select_cloud_printers([], [DEV1, DEV1], {DEV1.printer_id})
    assert [config.serial for config in result] == [S1]


def _blocking_fetch(monkeypatch, payloads: list[list[dict]]) -> tuple[threading.Event, threading.Event, list[str]]:
    """Fake fetch that stops mid-call until released, as a slow Bambu response does."""
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def fake(token: str, **_kw: object) -> list[dict]:
        calls.append(token)
        started.set()
        assert release.wait(5)
        return payloads[len(calls) - 1]

    monkeypatch.setattr(auth_actions, "get_bind_devices", fake)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    return started, release, calls


def test_peek_and_clear_do_not_wait_for_a_slow_fetch(monkeypatch) -> None:
    started, release, _calls = _blocking_fetch(monkeypatch, [[{"dev_id": S1}]])
    devices = CloudDeviceList()
    fetch = threading.Thread(target=devices.refresh)
    fetch.start()
    assert started.wait(5)
    other = threading.Thread(target=lambda: (devices.peek(), devices.clear()))
    other.start()
    other.join(2)
    blocked = other.is_alive()
    release.set()
    fetch.join(5)
    other.join(5)
    assert not blocked


def test_concurrent_refreshes_make_one_fetch(monkeypatch) -> None:
    started, release, calls = _blocking_fetch(monkeypatch, [[{"dev_id": S1}]])
    devices = CloudDeviceList()
    threads = [threading.Thread(target=devices.refresh) for _ in range(4)]
    for thread in threads:
        thread.start()
    assert started.wait(5)
    release.set()
    for thread in threads:
        thread.join(5)
    assert len(calls) == 1
    assert [d.serial for d in devices.peek()] == [S1]


def test_clear_discards_a_fetch_already_running(monkeypatch) -> None:
    """A login clears the list; the previous account's answer must not land afterwards."""
    started, release, calls = _blocking_fetch(monkeypatch, [[{"dev_id": S1}], [{"dev_id": S2}]])
    devices = CloudDeviceList()
    fetch = threading.Thread(target=devices.refresh)
    fetch.start()
    assert started.wait(5)
    devices.clear()
    release.set()
    fetch.join(5)
    assert devices.peek() == []
    devices.refresh()
    assert len(calls) == 2
    assert [d.serial for d in devices.peek()] == [S2]


def test_configure_cloud_with_several_printers_signs_in(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(
        auth_actions, "get_bind_devices", lambda token: [{"dev_id": S1}, {"dev_id": S2}]
    )
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and "Select" in result.message
    assert os.environ.get("BAMBULAB_SERIAL", "") == ""
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_several_printers_login_leaves_an_env_lan_printer_alone(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "local_mqtt")
    monkeypatch.setenv("BAMBULAB_SERIAL", S3)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(
        auth_actions, "get_bind_devices", lambda token: [{"dev_id": S1}, {"dev_id": S2}]
    )
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and "Kept after restarts" in result.note
    assert os.environ["BAMBULAB_TRANSPORT"] == "local_mqtt"
    assert os.environ["BAMBULAB_SERIAL"] == S3
    assert overrides.load_overrides() == {}
    assert (Path(os.environ["BAMBULAB_CONFIG_DIR"]) / "credentials.enc.json").exists()


def test_several_printers_login_without_secret_is_session_only(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(
        auth_actions, "get_bind_devices", lambda token: [{"dev_id": S1}, {"dev_id": S2}]
    )
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and "until the next restart" in result.note
    assert "BAMBULAB_TRANSPORT" not in os.environ
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"
