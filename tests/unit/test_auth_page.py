"""Tests for the /auth page: saved overrides, page actions, and HTTP routes."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bambulab_metrics_exporter import auth_actions, overrides
from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.auth_actions import AuthInputError, CodeSender
from bambulab_metrics_exporter.cloud_auth import CloudAuthError, LoginResult
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics

SECRET = "fake-development-key-never-use"
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
    sender = CodeSender(interval_seconds=60)
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


def test_configure_cloud_multiple_printers_needs_serial(monkeypatch) -> None:
    monkeypatch.setattr(auth_actions, "login_with_code", lambda email, code: _login())
    monkeypatch.setattr(
        auth_actions, "get_bind_devices", lambda token: [{"dev_id": "A" * 15}, {"dev_id": "B" * 15}]
    )
    result = auth_actions.configure_cloud("operator@example.invalid", "000000")
    assert not result.ok and "2 printers" in result.message
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


def test_post_response_does_not_auto_refresh(monkeypatch) -> None:
    """The echoed email must not be wiped by a refresh while the runtime is connecting."""
    monkeypatch.setattr(auth_actions, "send_code", lambda email: None)
    client, runtime = _client()
    runtime.status = lambda: {"state": "connecting", "message": "", "transport": "local_mqtt"}
    page = client.post("/auth/cloud/send-code", data={"email": "operator@example.invalid"}).text
    assert 'http-equiv="refresh"' not in page
    assert 'value="operator@example.invalid"' in page


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
