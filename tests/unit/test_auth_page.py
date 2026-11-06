"""Tests for the /auth page: saved overrides, page actions, and HTTP routes."""
from __future__ import annotations

import http.client
import logging
import os
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bambulab_metrics_exporter import api, auth_actions, overrides
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
from bambulab_metrics_exporter.fleet import PrinterFleet
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.printers import (
    MAX_PRINTERS,
    PrinterConfig,
    PrinterStore,
    printer_id_for,
)

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
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": "FAKE00TEST000001"}])

    result = auth_actions.configure_cloud("operator@example.invalid", "000000")

    assert result.ok
    assert "FAK" in result.message and "FAKE00TEST000001" not in result.message
    assert os.environ["BAMBULAB_TRANSPORT"] == "cloud_mqtt"
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"
    assert (Path(os.environ["BAMBULAB_CONFIG_DIR"]) / "credentials.enc.json").exists()


def test_configure_cloud_with_no_printers_keeps_the_login(monkeypatch) -> None:
    """A code is single use, so an empty device list never fails the login."""
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token: [])
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and "no printers" in result.message
    assert "BAMBULAB_TRANSPORT" not in os.environ
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_configure_cloud_with_serial_session_only(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token: pytest.fail("serial given"))
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

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", bind_fails)
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and "did not return your printers" in result.message
    assert "bind down" not in result.message
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


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
        auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": "FAKE00TEST000001"}]
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
        auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": "FAKE00TEST000001"}]
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

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", fake)
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

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", fail)
    CloudDeviceList().refresh()


def test_device_list_failure_is_cached_as_empty(monkeypatch) -> None:
    calls: list[int] = []

    def boom(*_a: object, **_k: object) -> list[dict]:
        calls.append(1)
        raise CloudAuthError("network down")

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", boom)
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

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", boom)
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
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token, **_k: payload)
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

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", fake)
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
        auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": S1}, {"dev_id": S2}]
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
        auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": S1}, {"dev_id": S2}]
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
        auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": S1}, {"dev_id": S2}]
    )
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and "until the next restart" in result.note
    assert "BAMBULAB_TRANSPORT" not in os.environ
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


# ---------------------------------------------------------------------------
# carried rulings on the actions
# ---------------------------------------------------------------------------

def _sign_in(monkeypatch, bind) -> auth_actions.ActionResult:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", bind)
    return auth_actions.configure_cloud("operator@example.invalid", "000000")


@pytest.mark.parametrize("error", [ValueError("x"), OSError("x"), AttributeError("x")])
def test_login_survives_any_device_list_error(monkeypatch, error: Exception) -> None:
    def bind(token: str) -> list[dict]:
        raise error

    result = _sign_in(monkeypatch, bind)
    assert result.ok and os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_login_survives_a_malformed_device_list(monkeypatch) -> None:
    result = _sign_in(monkeypatch, lambda token: ["junk", {"dev_id": "bad id"}])
    assert result.ok and "no printers" in result.message


def test_single_printer_login_uppercases_the_serial(monkeypatch) -> None:
    result = _sign_in(monkeypatch, lambda token: [{"dev_id": S1.lower()}])
    assert result.ok and os.environ["BAMBULAB_SERIAL"] == S1


def test_select_refuses_an_empty_device_list() -> None:
    cloud = PrinterConfig(serial=S1, transport="cloud_mqtt")
    with pytest.raises(AuthInputError, match="not available"):
        select_cloud_printers([cloud, LAN3], [], set())


def test_select_keeps_a_cloud_printer_missing_from_the_device_list() -> None:
    orphan = PrinterConfig(serial=S3, transport="cloud_mqtt", name="Gone")
    result = select_cloud_printers([orphan], [DEV1, DEV2], {DEV1.printer_id})
    assert [p.serial for p in result] == [S3, S1]
    assert result[0] is orphan


def test_select_limit_counts_a_cloud_printer_missing_from_the_device_list() -> None:
    current = [
        PrinterConfig(serial=f"FAKE00LAN{i:07d}", transport="local_mqtt", host="192.0.2.9")
        for i in range(MAX_PRINTERS - 1)
    ]
    current.append(PrinterConfig(serial=S3, transport="cloud_mqtt"))
    with pytest.raises(AuthInputError, match=str(MAX_PRINTERS)):
        select_cloud_printers(current, [DEV1], {DEV1.printer_id})


@pytest.mark.parametrize(
    "failure",
    [CloudAuthError("network down"), OSError("network down")],
)
def test_failed_refresh_keeps_the_last_good_list(monkeypatch, failure: Exception) -> None:
    answers: list[object] = [[{"dev_id": S1}], failure]

    def fetch(*_a: object, **_k: object) -> list[dict]:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[return-value]

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", fetch)
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    now = [0.0]
    devices = CloudDeviceList(ttl_seconds=60.0, clock=lambda: now[0])
    devices.refresh()
    now[0] = 61.0
    devices.refresh()
    assert [d.serial for d in devices.peek()] == [S1]
    devices.refresh()  # the failure is cached too: no retry until the TTL passes
    assert answers == []


def test_real_empty_answer_replaces_the_list(monkeypatch) -> None:
    answers = [[{"dev_id": S1}], []]
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda *_a, **_k: answers.pop(0))
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    now = [0.0]
    devices = CloudDeviceList(ttl_seconds=60.0, clock=lambda: now[0])
    devices.refresh()
    now[0] = 61.0
    devices.refresh()
    assert devices.peek() == [] and answers == []


def test_clear_still_empties_the_list_after_a_failed_refresh(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda *_a, **_k: [{"dev_id": S1}])
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    devices = CloudDeviceList()
    devices.refresh()
    devices.clear()
    assert devices.peek() == []


def test_lan_update_with_a_blank_port_keeps_the_port() -> None:
    first = add_local_printer([], "192.0.2.3", S3, "fake-access-code", "8884")
    updated = add_local_printer(first, "192.0.2.4", S3, "fake-access-code", "  ")
    assert updated[0].port == 8884 and updated[0].host == "192.0.2.4"
    assert add_local_printer(updated, "192.0.2.4", S3, "fake-access-code", "8885")[0].port == 8885


def test_new_lan_printer_with_a_blank_port_uses_the_default() -> None:
    assert add_local_printer([], "192.0.2.3", S3, "fake-access-code")[0].port == 8883


def test_device_serial_is_uppercased(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda *_a, **_k: [{"dev_id": S1.lower()}])
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    devices = CloudDeviceList()
    devices.refresh()
    assert [(d.serial, d.printer_id) for d in devices.peek()] == [(S1, printer_id_for(S1))]


@pytest.mark.parametrize("port", ["0", "65536", "abc", "\u00b2", "9" * 5000])
def test_configure_local_rejects_bad_port(port: str) -> None:
    with pytest.raises(AuthInputError, match="port"):
        auth_actions.configure_local("192.0.2.25", S1, "fake-access-code", port)


def test_remove_accepts_the_id_of_the_printer_from_env_vars() -> None:
    env = PrinterConfig(serial=S1, transport="local_mqtt", env_printer=True)
    assert remove_printer([env, LAN3], "env") == [LAN3]
    with pytest.raises(AuthInputError):
        remove_printer([LAN3], "env")


# ---------------------------------------------------------------------------
# printer routes and page
# ---------------------------------------------------------------------------

class _FleetRuntime(_Runtime):
    """A _Runtime with the fleet's list surface, recording updates."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.list: list[PrinterConfig] = []
        self.updates: list[list[PrinterConfig]] = []
        self.reset_called = False
        self.cloud_reconfigured = 0
        self.saved = True
        self.list_unreadable = False
        self.message = ""

    def configs(self) -> list[PrinterConfig]:
        return list(self.list)

    def update(self, configs: list[PrinterConfig]) -> bool:
        self.list = list(configs)
        self.updates.append(list(configs))
        return True

    def reconfigure_cloud(self) -> None:
        self.cloud_reconfigured += 1

    def reset_to_env(self) -> None:
        self.reset_called = True

    def printers_status(self) -> list[dict[str, str]]:
        return [
            {"id": c.printer_id, "name": c.label, "serial": auth_actions.mask_serial(c.serial),
             "transport": c.transport, "state": "running", "message": self.message}
            for c in self.list
        ]


def _fleet_client(monkeypatch, devices: list[dict] | None = None):
    runtime = _FleetRuntime(Settings(bambulab_serial=S1))
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")

    def bind(token: str, **_k: object) -> list[dict]:
        return devices if devices is not None else [
            {"dev_id": S1, "name": "One <x>", "dev_product_name": "H2D", "online": True},
            {"dev_id": S2, "name": "Two", "dev_product_name": "X1C", "online": False},
        ]

    monkeypatch.setattr(auth_actions, "fetch_bind_devices", bind)
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", bind)
    return TestClient(build_app(runtime=runtime)), runtime


def mask_serial_of(serial: str) -> str:
    return auth_actions.mask_serial(serial)


def test_picker_shows_masked_devices_and_never_a_raw_serial(monkeypatch) -> None:
    client, _runtime = _fleet_client(monkeypatch)
    page = client.get("/auth").text
    assert "One &lt;x&gt;" in page and "H2D" in page and "Offline" in page
    assert mask_serial_of(S1) in page
    assert S1 not in page and S2 not in page
    assert f'name="printer_{printer_id_for(S1)}"' in page


def test_picker_ticks_the_selected_cloud_printers(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S2, transport="cloud_mqtt")]
    page = client.get("/auth").text
    assert f'name="printer_{printer_id_for(S2)}" checked' in page
    assert f'name="printer_{printer_id_for(S1)}" checked' not in page


def test_picker_needs_no_token(monkeypatch) -> None:
    client, _runtime = _fleet_client(monkeypatch)
    monkeypatch.delenv("BAMBULAB_CLOUD_ACCESS_TOKEN")
    assert 'action="/auth/printers/select"' not in client.get("/auth").text


def test_select_route_updates_the_list(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    client.get("/auth")
    client.post("/auth/printers/select", data={f"printer_{printer_id_for(S2)}": "on"})
    assert [c.serial for c in runtime.list] == [S2]


def test_select_route_rejects_a_forged_id(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    client.get("/auth")
    response = client.post("/auth/printers/select", data={"printer_000000000000": "on"})
    assert runtime.updates == []
    assert "no longer on this account" in response.text


def test_select_route_needs_no_page_view_first(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    client.post("/auth/printers/select", data={f"printer_{printer_id_for(S2)}": "on"})
    assert [c.serial for c in runtime.list] == [S2]


def test_printer_gone_from_the_account_cannot_be_added_again(monkeypatch) -> None:
    listing = [{"dev_id": S1}, {"dev_id": S2}]
    monkeypatch.setattr(api, "CloudDeviceList", lambda: CloudDeviceList(ttl_seconds=0.0))
    client, runtime = _fleet_client(monkeypatch, devices=listing)
    client.get("/auth")
    listing[:] = [{"dev_id": S2}]
    response = client.post(
        "/auth/printers/select", data={f"printer_{printer_id_for(S1)}": "on"}, headers=_JSON
    )
    assert response.json()["ok"] is False
    assert "no longer on this account" in response.json()["message"]
    assert runtime.updates == []


def test_select_route_refuses_when_the_account_became_empty(monkeypatch) -> None:
    listing = [{"dev_id": S1}]
    monkeypatch.setattr(api, "CloudDeviceList", lambda: CloudDeviceList(ttl_seconds=0.0))
    client, runtime = _fleet_client(monkeypatch, devices=listing)
    client.get("/auth")
    listing.clear()
    response = client.post("/auth/printers/select", headers=_JSON)
    assert "not available" in response.json()["message"] and runtime.updates == []


def test_select_route_refuses_an_empty_device_list(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    runtime.list = [PrinterConfig(serial=S1, transport="cloud_mqtt")]
    client.get("/auth")
    response = client.post("/auth/printers/select", headers=_JSON)
    assert response.json()["ok"] is False and "not available" in response.json()["message"]
    assert runtime.updates == [] and [c.serial for c in runtime.list] == [S1]


def test_cloud_printer_missing_from_the_account_stays_and_can_be_removed(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S3, transport="cloud_mqtt", name="Gone")]
    client.get("/auth")
    client.post("/auth/printers/select", data={f"printer_{printer_id_for(S1)}": "on"})
    assert [c.serial for c in runtime.list] == [S3, S1]
    assert "Gone" in client.get("/auth").text
    client.post("/auth/printers/remove", data={"printer_id": printer_id_for(S3)})
    assert [c.serial for c in runtime.list] == [S1]


def test_full_selection_fits_in_the_form_cap(monkeypatch) -> None:
    serials = [f"FAKE00CLOUD{i:05d}" for i in range(MAX_PRINTERS)]
    client, runtime = _fleet_client(monkeypatch, devices=[{"dev_id": s} for s in serials])
    client.get("/auth")
    response = client.post(
        "/auth/printers/select",
        data={f"printer_{printer_id_for(s)}": "on" for s in serials},
        headers=_JSON,
    )
    assert response.status_code == 200 and response.json()["ok"] is True
    assert sorted(c.serial for c in runtime.list) == serials


def test_add_and_remove_local_routes(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    client.post(
        "/auth/printers/add-local",
        data={"host": "192.0.2.25", "serial": S3, "access_code": "fake-access-code", "name": "Garage"},
    )
    assert [c.serial for c in runtime.list] == [S3]
    page = client.get("/auth").text
    assert "Garage" in page and S3 not in page and "fake-access-code" not in page
    client.post("/auth/printers/remove", data={"printer_id": printer_id_for(S3)})
    assert runtime.list == []


def test_add_local_route_passes_the_port(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    client.post(
        "/auth/printers/add-local",
        data={"host": "192.0.2.25", "serial": S3, "access_code": "fake-access-code", "port": "8884"},
    )
    assert runtime.list[0].port == 8884


def test_add_local_input_error_is_shown_and_changes_nothing(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    response = client.post(
        "/auth/printers/add-local",
        data={"host": "192.0.2.25", "serial": "bad", "access_code": "fake-access-code"},
        headers=_JSON,
    )
    assert response.json()["ok"] is False and runtime.updates == []
    assert "fake-access-code" not in response.text


def test_failed_save_is_shown_instead_of_500(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])

    def unwritable(_configs: list[PrinterConfig]) -> bool:
        raise PermissionError(13, "Permission denied")

    runtime.update = unwritable
    response = client.post(
        "/auth/printers/add-local",
        data={"host": "192.0.2.25", "serial": S3, "access_code": "fake-access-code"},
        headers=_JSON,
    )
    assert response.status_code == 200 and response.json()["ok"] is False
    assert "Could not save the settings: Permission denied" in response.json()["message"]


_PRINTER_ROUTES = {
    "/auth/printers/select": lambda: {f"printer_{printer_id_for(S2)}": "on"},
    "/auth/printers/add-local": lambda: {
        "host": "192.0.2.25", "serial": S3, "access_code": ACCESS_CODE, "name": "Garage",
    },
    "/auth/printers/remove": lambda: {"printer_id": printer_id_for(S1)},
}


@pytest.mark.parametrize("path", list(_PRINTER_ROUTES))
def test_printer_routes_answer_json_without_a_redirect_or_flash(monkeypatch, path: str) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S1, transport="cloud_mqtt")]
    client.get("/auth")
    response = client.post(path, data=_PRINTER_ROUTES[path](), headers=_JSON, follow_redirects=False)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["ok"] is True and "Kept after restarts" in body["note"]
    assert runtime.reconfigured == 0
    for secret in (S1, S2, S3, ACCESS_CODE, EMAIL, "192.0.2.25"):
        assert secret not in response.text
    assert body["message"] not in client.get("/auth").text


@pytest.mark.parametrize("path", list(_PRINTER_ROUTES))
def test_printer_routes_redirect_without_the_json_header(monkeypatch, path: str) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S1, transport="cloud_mqtt")]
    client.get("/auth")
    response = client.post(path, data=_PRINTER_ROUTES[path](), follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/auth"
    assert "bme_auth" in response.cookies
    other_visitor = TestClient(client.app)
    assert "Kept after restarts" not in other_visitor.get("/auth").text
    assert "Kept after restarts" in client.get("/auth").text


@pytest.mark.parametrize(
    "path", ["/auth/printers/select", "/auth/printers/add-local", "/auth/printers/remove"]
)
def test_new_routes_keep_the_protections(monkeypatch, path: str) -> None:
    client, runtime = _fleet_client(monkeypatch)
    assert client.post(path, headers={"origin": "http://evil.invalid"}).status_code == 403
    assert client.post(path, headers={"host": "evil.example.com"}).status_code == 403
    oversized = client.post(path, content=b"a=" + b"x" * 9000)
    assert oversized.status_code == 413
    assert runtime.updates == []


def test_new_routes_absent_without_a_fleet() -> None:
    client, _runtime = _client()
    assert client.post("/auth/printers/remove", data={"printer_id": "x"}).status_code == 404


def test_page_with_no_printers(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    assert runtime.list == []
    assert client.get("/auth").status_code == 200


def test_page_without_a_fleet_keeps_the_local_form() -> None:
    page = _client()[0].get("/auth").text
    assert 'action="/auth/local"' in page and "Connect locally" in page
    assert "/auth/printers" not in page.split("<script>")[0]


def test_fleet_page_posts_the_local_form_to_add_local(monkeypatch) -> None:
    page = _fleet_client(monkeypatch, devices=[])[0].get("/auth").text
    assert 'action="/auth/printers/add-local"' in page and "Add printer" in page
    assert 'action="/auth/local"' not in page and "Connect locally" not in page
    for name in ("host", "serial", "access_code", "port", "name"):
        assert f'name="{name}"' in page


def test_serial_field_left_the_cloud_form(monkeypatch) -> None:
    page = _fleet_client(monkeypatch, devices=[])[0].get("/auth").text
    assert "Serial number (optional)" not in page
    cloud = page[page.index('class="card panel panel-cloud"'):page.index("<script>")]
    assert 'name="serial"' not in cloud


def test_printer_blocks_are_always_rendered_empty_capable(monkeypatch) -> None:
    for client in (_client()[0], _fleet_client(monkeypatch, devices=[])[0]):
        page = client.get("/auth").text
        assert '<div id="printers-live" data-live></div>' in page
        assert '<div id="cloud-picker" data-live></div>' in page
    page = _fleet_client(monkeypatch)[0].get("/auth").text
    assert '<div id="cloud-picker" data-live><form' in page


def test_printer_table_sits_right_after_the_status_card(monkeypatch) -> None:
    page = _client()[0].get("/auth").text
    assert page.index('id="status-card"') < page.index('id="printers-live"')
    assert page.index('id="printers-live"') < page.index('id="page-notice"')
    cloud = page.index("panel-cloud\">")
    assert cloud < page.index('id="cloud-picker"') < page.index('action="/auth/reset"')
    assert page.index("</form>", cloud) < page.index('id="cloud-picker"')


def test_printer_table_escapes_and_shows_state_message_and_transport(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    runtime.message = "Could not <b>connect</b>"
    runtime.list = [
        PrinterConfig(serial=S3, transport="local_mqtt", name="<img src=x>"),
        PrinterConfig(serial=S1, transport="cloud_mqtt", name="Cloudy"),
    ]
    table = client.get("/auth").text.split('id="printers-live"')[1].split('id="page-notice"')[0]
    assert "&lt;img src=x&gt;" in table and "<img" not in table
    assert "Could not &lt;b&gt;connect&lt;/b&gt;" in table
    assert "LAN" in table and "Cloud" in table and "Connected" in table
    assert S3 not in table and S1 not in table
    assert f'name="printer_id" value="{printer_id_for(S3)}"' in table


def test_template_placeholders_in_names_are_not_expanded(monkeypatch) -> None:
    client, runtime = _fleet_client(
        monkeypatch, devices=[{"dev_id": S1, "name": "{{CLOUD_EMAIL}}", "dev_product_name": "{{FLASH}}"}]
    )
    runtime.list = [PrinterConfig(serial=S3, transport="local_mqtt", name="{{VERSION}}")]
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client.post("/auth/cloud/send-code", data={"email": EMAIL}, follow_redirects=False)
    page = client.get("/auth").text
    assert page.count(EMAIL) == 1  # only the form field, not the device name
    assert "{{" not in page.split("<script>")[0].replace("&#123;", "")


def test_login_clears_the_device_list(monkeypatch) -> None:
    listing = [{"dev_id": S1, "name": "Old"}, {"dev_id": S2, "name": "Older"}]
    client, _runtime = _fleet_client(monkeypatch, devices=listing)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    assert "Old" in client.get("/auth").text
    listing[:] = [{"dev_id": S3, "name": "New"}, {"dev_id": S2, "name": "Newer"}]
    client.post("/auth/cloud/login", data={"email": EMAIL, "code": "123456"}, headers=_JSON)
    page = client.get("/auth").text
    assert "New" in page and "Old" not in page


def test_failed_login_keeps_the_device_list(monkeypatch) -> None:
    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    calls: list[int] = []
    client, _runtime = _fleet_client(monkeypatch)
    real = auth_actions.fetch_bind_devices
    monkeypatch.setattr(
        auth_actions, "fetch_bind_devices", lambda token, **k: (calls.append(1), real(token, **k))[1]
    )
    monkeypatch.setattr(auth_actions, "login_with_code", reject)
    client.get("/auth")
    client.post("/auth/cloud/login", data={"email": EMAIL, "code": "123456"}, headers=_JSON)
    client.get("/auth")
    assert len(calls) == 1


def test_login_with_no_printers_succeeds_on_the_page(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    response = client.post(
        "/auth/cloud/login", data={"email": EMAIL, "code": "123456"}, headers=_JSON
    )
    assert response.json()["ok"] is True and "no printers" in response.json()["message"]
    assert runtime.cloud_reconfigured == 1


def test_reset_clears_the_printer_list(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    client.post("/auth/reset")
    assert runtime.reset_called is True


def test_reset_reports_a_removed_printer_list(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch, devices=[])
    assert "Page settings removed" in client.post("/auth/reset", headers=_JSON).json()["message"]
    runtime.saved = False
    assert "already using env vars" in client.post("/auth/reset", headers=_JSON).json()["message"]


def test_reset_clears_the_device_list(monkeypatch) -> None:
    listing = [{"dev_id": S1, "name": "Old"}]
    client, _runtime = _fleet_client(monkeypatch, devices=listing)
    assert "Old" in client.get("/auth").text
    listing[:] = [{"dev_id": S2, "name": "New"}]
    client.post("/auth/reset", headers=_JSON)
    page = client.get("/auth").text
    assert "New" in page and "Old" not in page


def _script(page: str) -> str:
    return page.split("<script>")[1].split("</script>")[0]


def test_page_script_keeps_ticks_and_one_poll_timer() -> None:
    script = _script(_client()[0].get("/auth").text)
    assert 'hasAttribute("data-dirty")' in script
    assert 'setAttribute("data-dirty"' in script
    assert 'removeAttribute("data-dirty")' in script
    assert 'addEventListener("change"' in script
    assert script.count("setTimeout(") == 2  # the send-code countdown and schedulePoll
    assert "setInterval" not in script and "location" not in script


def test_page_script_resets_the_add_form_on_success() -> None:
    script = _script(_client()[0].get("/auth").text)
    assert '"/auth/printers/add-local"' in script and "form.reset()" in script


# ---------------------------------------------------------------------------
# the page on a real PrinterFleet
# ---------------------------------------------------------------------------

def _real_fleet(monkeypatch) -> tuple[TestClient, PrinterFleet]:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)

    def no_client(_settings: Settings):
        raise AssertionError("the fleet is not started in these tests")

    fleet = PrinterFleet(PrinterStore(), validate=lambda _s: None, client_factory=no_client)
    return TestClient(build_app(runtime=fleet)), fleet


def test_reset_on_a_real_fleet_takes_the_lock_again_without_hanging(monkeypatch) -> None:
    """The route holds overrides.lock and reset_to_env takes it from the same thread."""
    client, fleet = _real_fleet(monkeypatch)
    fleet.update([LAN3])
    answers: list = []
    worker = threading.Thread(
        target=lambda: answers.append(client.post("/auth/reset", headers=_JSON)), daemon=True
    )
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "reset deadlocked on overrides.lock"
    assert "Page settings removed" in answers[0].json()["message"]
    assert fleet.saved is False and fleet.configs() == []


def test_env_printer_can_be_removed_from_a_real_fleet(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SERIAL", S3)
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.3")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "fake-access-code")
    client, fleet = _real_fleet(monkeypatch)
    page = client.get("/auth").text
    assert 'name="printer_id" value="env"' in page and S3 not in page
    response = client.post("/auth/printers/remove", data={"printer_id": "env"}, headers=_JSON)
    assert response.json()["ok"] is True
    assert fleet.configs() == [] and fleet.saved is True


def test_add_local_on_a_real_fleet_keeps_the_env_printer(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SERIAL", S1)
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.1")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "fake-access-code")
    client, fleet = _real_fleet(monkeypatch)
    response = client.post(
        "/auth/printers/add-local",
        data={"host": "192.0.2.3", "serial": S3, "access_code": "another-fake-code", "name": "Two"},
        headers=_JSON,
    )
    assert response.json()["ok"] is True
    assert [c.serial for c in fleet.configs()] == [S1, S3]
    page = client.get("/auth").text
    assert page.count('action="/auth/printers/remove"') == 2
    assert S1 not in page and S3 not in page and "another-fake-code" not in page


def test_page_on_an_empty_real_fleet(monkeypatch) -> None:
    client, fleet = _real_fleet(monkeypatch)
    fleet.update([])
    page = client.get("/auth")
    assert page.status_code == 200 and "No printers selected." in page.text
    assert '<div id="printers-live" data-live></div>' in page.text


def test_empty_real_fleet_keeps_the_allowed_hosts(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ALLOWED_HOSTS", "exporter.example.invalid")
    client, fleet = _real_fleet(monkeypatch)
    fleet.update([])
    assert client.get("/auth", headers={"Host": "exporter.example.invalid"}).status_code == 200
    assert client.get("/auth", headers={"Host": "other.example.invalid"}).status_code == 403


def test_reset_on_an_empty_real_fleet_uses_the_configured_config_dir(monkeypatch, tmp_path) -> None:
    client, fleet = _real_fleet(monkeypatch)
    fleet.update([])
    credentials = tmp_path / "credentials.enc.json"
    credentials.write_bytes(b"from the container")
    overrides.backup_credentials(credentials)
    credentials.write_bytes(b"from the page login")
    assert client.post("/auth/reset", headers=_JSON).json()["ok"] is True
    assert credentials.read_bytes() == b"from the container"


# ---------------------------------------------------------------------------
# one-printer login with a saved list
# ---------------------------------------------------------------------------

_LOGIN = {"email": EMAIL, "code": "123456"}


def _login_client(monkeypatch, serial: str = S1):
    client, runtime = _fleet_client(
        monkeypatch, devices=[{"dev_id": serial, "name": "Solo", "dev_product_name": "H2D"}]
    )
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    return client, runtime


def test_one_printer_login_adds_it_to_the_saved_list(monkeypatch) -> None:
    client, runtime = _login_client(monkeypatch)
    runtime.list = [LAN3]
    response = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON)
    body = response.json()
    assert body["ok"] is True and "added" in body["message"]
    assert mask_serial_of(S1) in body["message"] and S1 not in response.text
    assert "Kept after restarts" in body["note"]
    assert runtime.list[0] == LAN3
    assert [(c.serial, c.transport, c.name, c.model) for c in runtime.list[1:]] == [
        (S1, "cloud_mqtt", "Solo", "H2D")
    ]
    assert runtime.cloud_reconfigured == 1


def test_one_printer_login_note_says_when_the_list_is_session_only(monkeypatch) -> None:
    client, runtime = _login_client(monkeypatch)
    runtime.update = lambda configs: False
    body = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()
    assert body["ok"] is True and "until the next restart" in body["note"]


def test_one_printer_login_leaves_a_lan_printer_on_lan(monkeypatch) -> None:
    client, runtime = _login_client(monkeypatch, serial=S3)
    runtime.list = [LAN3]
    body = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()
    assert body["ok"] is True and runtime.updates == []
    assert "added" not in body["message"].replace("already added", "")
    assert "LAN" in body["message"]
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_one_printer_login_with_the_printer_already_listed_changes_nothing(monkeypatch) -> None:
    client, runtime = _login_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S1, transport="cloud_mqtt", name="Mine")]
    body = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()
    assert body["ok"] is True and runtime.updates == []
    assert "added" not in body["message"]


def test_one_printer_login_with_a_full_list_keeps_the_login(monkeypatch) -> None:
    client, runtime = _login_client(monkeypatch)
    runtime.list = [
        PrinterConfig(serial=f"FAKE00LAN{i:07d}", transport="local_mqtt", host="192.0.2.9")
        for i in range(MAX_PRINTERS)
    ]
    body = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()
    assert body["ok"] is True and str(MAX_PRINTERS) in body["message"]
    assert "not added" in body["message"] and runtime.updates == []
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


@pytest.mark.parametrize("error", [PermissionError(13, "Permission denied"), RuntimeError("x")])
def test_one_printer_login_survives_a_failed_list_save(monkeypatch, error: Exception) -> None:
    client, runtime = _login_client(monkeypatch)

    def unwritable(_configs: list[PrinterConfig]) -> bool:
        raise error

    runtime.update = unwritable
    response = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and "could not be added" in body["message"]
    assert S1 not in response.text and runtime.cloud_reconfigured == 1


def test_one_printer_login_in_env_mode_stays_as_today(monkeypatch) -> None:
    client, runtime = _login_client(monkeypatch)
    runtime.saved = False
    body = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()
    assert body["ok"] is True and "Signed in to Bambu Cloud for printer" in body["message"]
    assert runtime.updates == [] and os.environ["BAMBULAB_SERIAL"] == S1


def test_several_printers_login_with_a_saved_list_adds_nothing(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    body = client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()
    assert body["ok"] is True and runtime.updates == []


def test_one_printer_login_on_a_real_fleet(monkeypatch) -> None:
    client, fleet = _real_fleet(monkeypatch)
    fleet.update([LAN3])
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token: [{"dev_id": S1}])
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token, **_k: [{"dev_id": S1}])
    assert client.post("/auth/cloud/login", data=_LOGIN, headers=_JSON).json()["ok"] is True
    assert [c.serial for c in fleet.configs()] == [S3, S1]
    assert f'name="printer_{printer_id_for(S1)}" checked' in client.get("/auth").text


def test_page_says_when_the_saved_list_could_not_be_read(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    assert "saved printer list could not be read" not in client.get("/auth").text
    runtime.list_unreadable = True
    assert "saved printer list could not be read" in client.get("/auth").text


def test_login_reconnects_only_the_cloud_side(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    client.post("/auth/cloud/login", data={"email": EMAIL, "code": "123456"})
    assert runtime.cloud_reconfigured == 1 and runtime.reconfigured == 0


def test_login_answering_json_reconnects_only_the_cloud_side(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    client.post("/auth/cloud/login", data={"email": EMAIL, "code": "123456"}, headers=_JSON)
    assert runtime.cloud_reconfigured == 1 and runtime.reconfigured == 0


_LOCAL = {"host": "192.0.2.25", "serial": S2, "access_code": "fake-access-code"}


@pytest.mark.parametrize("headers", [{}, _JSON])
def test_post_local_with_a_saved_list_adds_the_printer(monkeypatch, headers) -> None:
    client, runtime = _fleet_client(monkeypatch)
    keep = PrinterConfig(serial=S1, transport="cloud_mqtt", name="Keep")
    runtime.list = [keep]
    client.post("/auth/local", data=_LOCAL, headers=headers)
    assert runtime.list[0] == keep
    assert [(c.serial, c.transport, c.host) for c in runtime.list[1:]] == [
        (S2, "local_mqtt", "192.0.2.25")
    ]
    assert "BAMBULAB_HOST" not in os.environ
    assert runtime.reconfigured == 0  # The update applied it; other printers stay connected.


def test_post_local_with_a_saved_list_reports_a_saved_printer(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S1, transport="cloud_mqtt")]
    body = client.post("/auth/local", data=_LOCAL, headers=_JSON).json()
    assert body["ok"] is True and body["message"] == "LAN printer saved."


def test_post_local_with_a_saved_list_refuses_a_cloud_printer(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.list = [PrinterConfig(serial=S2, transport="cloud_mqtt")]
    body = client.post("/auth/local", data=_LOCAL, headers=_JSON).json()
    assert body["ok"] is False and "already added through the cloud" in body["message"]
    assert runtime.updates == [] and runtime.reconfigured == 0


def test_post_local_without_a_saved_list_keeps_configuring_the_env_printer(monkeypatch) -> None:
    client, runtime = _fleet_client(monkeypatch)
    runtime.saved = False
    client.post("/auth/local", data=_LOCAL)
    assert os.environ["BAMBULAB_HOST"] == "192.0.2.25"
    assert runtime.updates == [] and runtime.reconfigured == 1


# ---------------------------------------------------------------------------
# device list failures
# ---------------------------------------------------------------------------

def _bind_fails(token: str, **_k: object) -> list[dict]:
    raise CloudAuthError("fake-response-body")


def test_failed_device_fetch_after_login_is_told_apart_from_an_empty_account(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", _bind_fails)
    with caplog.at_level(logging.WARNING):
        result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok
    assert result.message == (
        "Signed in, but Bambu Cloud did not return your printers. Reload the page to retry."
    )
    assert "CloudAuthError" in caplog.text and "fake-response-body" not in caplog.text
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_empty_account_after_login_says_so(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", lambda token: [])
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert result.ok and result.message == "Signed in. This account has no printers."


def test_refresh_records_a_failure_and_keeps_the_last_list(monkeypatch, caplog) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    now = [0.0]
    devices = CloudDeviceList(ttl_seconds=60.0, clock=lambda: now[0])
    monkeypatch.setattr(
        auth_actions, "fetch_bind_devices", lambda *_a, **_k: [{"dev_id": S1}]
    )
    devices.refresh()
    assert devices.refresh_failed is False

    now[0] = 100.0
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", _bind_fails)
    with caplog.at_level(logging.WARNING):
        devices.refresh()
    assert devices.refresh_failed is True
    assert [device.serial for device in devices.peek()] == [S1]
    assert "CloudAuthError" in caplog.text and "fake-response-body" not in caplog.text

    now[0] = 200.0
    monkeypatch.setattr(
        auth_actions, "fetch_bind_devices", lambda *_a, **_k: [{"dev_id": S2}]
    )
    devices.refresh()
    assert devices.refresh_failed is False


def test_clear_forgets_a_failed_refresh(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", _bind_fails)
    devices = CloudDeviceList()
    devices.refresh()
    devices.clear()
    assert devices.refresh_failed is False


_STALE_NOTE = "could not be refreshed"


def _failed_refresh_client(monkeypatch):
    """A page that has a list, then a device fetch that fails once the TTL is over."""
    monkeypatch.setattr(api, "CloudDeviceList", lambda: CloudDeviceList(ttl_seconds=0.0))
    client, runtime = _fleet_client(monkeypatch)
    client.get("/auth")
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", _bind_fails)
    return client, runtime


def test_picker_says_the_list_is_the_last_known_one(monkeypatch) -> None:
    client, _runtime = _failed_refresh_client(monkeypatch)
    page = client.get("/auth").text
    assert _STALE_NOTE in page and "last known" in page
    assert f'name="printer_{printer_id_for(S1)}"' in page


def test_picker_has_no_note_after_a_good_refresh(monkeypatch) -> None:
    client, _runtime = _fleet_client(monkeypatch)
    assert _STALE_NOTE not in client.get("/auth").text


def test_picker_reports_a_failure_with_no_list_at_all(monkeypatch) -> None:
    client, _runtime = _fleet_client(monkeypatch)
    monkeypatch.setattr(auth_actions, "fetch_bind_devices", _bind_fails)
    page = client.get("/auth").text
    assert _STALE_NOTE in page and 'action="/auth/printers/select"' not in page


def test_select_is_refused_when_the_latest_refresh_failed(monkeypatch) -> None:
    client, runtime = _failed_refresh_client(monkeypatch)
    body = client.post(
        "/auth/printers/select", data={f"printer_{printer_id_for(S2)}": "on"}, headers=_JSON
    ).json()
    assert body["ok"] is False and _STALE_NOTE in body["message"]
    assert "Nothing was changed" in body["message"]
    assert runtime.updates == []


def test_add_login_printer_logs_the_failure_class(monkeypatch, caplog) -> None:
    def unwritable(_configs: list[PrinterConfig]) -> bool:
        raise PermissionError(13, "fake-sensitive-detail")

    device = CloudDevice(printer_id_for(S1), S1, "One", "H2D", True)
    with caplog.at_level(logging.WARNING):
        result = auth_actions.add_login_printer(
            [], device, unwritable, auth_actions.ActionResult(True, "ok")
        )
    assert result.ok
    assert "PermissionError" in caplog.text and "fake-sensitive-detail" not in caplog.text


def test_select_keeps_the_env_printer_name_and_model() -> None:
    env = PrinterConfig(
        serial=S1, transport="cloud_mqtt", name="Env name", model="X1C", env_printer=True
    )
    listed = CloudDevice(printer_id_for(S1), S1, "Renamed in the app", "H2D", True)
    other = CloudDevice(printer_id_for(S2), S2, "Two", "P1S", True)
    chosen = auth_actions.select_cloud_printers(
        [env], [listed, other], {listed.printer_id, other.printer_id}
    )
    assert chosen == [
        env,
        PrinterConfig(serial=S2, transport="cloud_mqtt", name="Two", model="P1S"),
    ]


def test_select_keeps_an_unnamed_env_printer_unnamed() -> None:
    env = PrinterConfig(serial=S1, transport="cloud_mqtt", env_printer=True)
    listed = CloudDevice(printer_id_for(S1), S1, "Named", "H2D", True)
    chosen = auth_actions.select_cloud_printers([env], [listed], {listed.printer_id})
    assert chosen == [env]


def test_select_does_not_carry_lan_values_into_the_env_printer() -> None:
    env = PrinterConfig(
        serial=S1, transport="cloud_mqtt", host="192.0.2.25", access_code="fake-access-code",
        name="Env", env_printer=True,
    )
    listed = CloudDevice(printer_id_for(S1), S1, "Named", "H2D", True)
    chosen = auth_actions.select_cloud_printers([env], [listed], {listed.printer_id})
    assert chosen[0].host == "" and chosen[0].access_code == ""
