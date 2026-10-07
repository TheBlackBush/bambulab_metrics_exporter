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
    assert "Saved page settings removed" in page.text

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
