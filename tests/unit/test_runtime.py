"""Tests for bambulab_metrics_exporter.runtime."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bambulab_metrics_exporter import runtime as rt
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.models import PrinterSnapshot
from bambulab_metrics_exporter.startup import ReauthRequiredError


def _wait_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached in time")


class _Client:
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        return PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 5}})


def _local(**overrides) -> Settings:
    values: dict = dict(
        bambulab_transport="local_mqtt",
        bambulab_host="192.0.2.25",
        bambulab_serial="FAKE00TEST000001",
        bambulab_access_code="fake-access-code",
        polling_interval_seconds=0.05,
        request_timeout_seconds=0.05,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)


def _runtime(settings_seq, validate, clients=None, **kw) -> rt.ExporterRuntime:
    settings_iter = iter(settings_seq)
    last: dict = {}

    def factory() -> Settings:
        try:
            last["s"] = next(settings_iter)
        except StopIteration:
            pass
        return last["s"]

    made: list[_Client] = clients if clients is not None else []

    def client_factory(_s: Settings) -> _Client:
        c = _Client()
        made.append(c)
        return c

    return rt.ExporterRuntime(
        settings_factory=factory,
        validate=validate,
        client_factory=client_factory,
        discover=lambda s: None,
        retry_seconds=kw.get("retry_seconds", 60.0),
        store_poll_seconds=kw.get("store_poll_seconds", 0.02),
    )


def test_runs_collector_after_successful_validation() -> None:
    clients: list[_Client] = []
    runtime = _runtime([_local()], validate=lambda s: None, clients=clients)
    runtime.start()
    try:
        _wait_until(lambda: runtime.ready)
        assert runtime.status()["state"] == rt.STATE_RUNNING
        assert clients[0].connected is True
    finally:
        runtime.stop()
    assert clients[0].connected is False


def test_missing_settings_wait_for_setup_then_reconfigure() -> None:
    validated: list[str] = []
    runtime = _runtime(
        # __init__ reads settings once, the first loop pass once more, reconfigure once.
        [_local(bambulab_host="", bambulab_access_code="")] * 2 + [_local()],
        validate=lambda s: validated.append(s.bambulab_host),
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_SETUP_REQUIRED)
        assert "BAMBULAB_HOST" in runtime.status()["message"]
        assert validated == []

        runtime.reconfigure()
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
        assert validated == ["192.0.2.25"]
    finally:
        runtime.stop()


def test_invalid_settings_do_not_kill_the_runtime() -> None:
    calls = {"n": 0}

    def factory() -> Settings:
        calls["n"] += 1
        if calls["n"] <= 2:  # first construction in __init__ succeeds
            if calls["n"] == 2:
                raise ValueError("bad transport")
        return _local()

    runtime = rt.ExporterRuntime(
        settings_factory=factory,
        validate=lambda s: None,
        client_factory=lambda s: _Client(),
        discover=lambda s: None,
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_SETUP_REQUIRED)
        assert "bad transport" in runtime.status()["message"]
        runtime.reconfigure()
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
    finally:
        runtime.stop()


def test_auth_required_resumes_when_credentials_file_changes(tmp_path: Path, caplog) -> None:
    attempts = {"n": 0}

    def validate(_s: Settings) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ReauthRequiredError("token expired")

    settings = _local(
        bambulab_transport="cloud_mqtt",
        bambulab_config_dir=str(tmp_path),
        bambulab_credentials_file="credentials.enc.json",
    )
    runtime = _runtime([settings], validate=validate)
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_AUTH_REQUIRED)
        assert "RE-AUTHENTICATION REQUIRED" in caplog.text
        assert attempts["n"] == 1

        (tmp_path / "credentials.enc.json").write_bytes(b"written by bambulab-reauth")
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
        assert attempts["n"] == 2
    finally:
        runtime.stop()


def test_auth_required_resumes_on_reconfigure() -> None:
    attempts = {"n": 0}

    def validate(_s: Settings) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ReauthRequiredError("token expired")

    runtime = _runtime([_local(bambulab_transport="cloud_mqtt")], validate=validate)
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_AUTH_REQUIRED)
        runtime.reconfigure()
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
    finally:
        runtime.stop()


def test_connection_error_retries_after_delay() -> None:
    attempts = {"n": 0}

    def validate(_s: Settings) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("printer unreachable")

    runtime = _runtime([_local()], validate=validate, retry_seconds=0.05)
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
        assert attempts["n"] == 2
    finally:
        runtime.stop()


def test_error_state_exposes_message_without_exiting() -> None:
    runtime = _runtime(
        [_local()], validate=lambda s: (_ for _ in ()).throw(RuntimeError("printer unreachable"))
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_ERROR)
        assert runtime.status()["message"] == "printer unreachable"
        assert runtime.ready is False
    finally:
        runtime.stop()


def test_reconfigure_restarts_collector_and_relabels_metrics() -> None:
    clients: list[_Client] = []
    runtime = _runtime(
        [_local(), _local(), _local(bambulab_serial="FAKE00TEST000002")],
        validate=lambda s: None,
        clients=clients,
    )
    first_metrics = runtime.metrics
    runtime.start()
    try:
        _wait_until(lambda: runtime.ready)
        runtime.reconfigure()
        _wait_until(lambda: len(clients) == 2 and runtime.ready)
        assert clients[0].connected is False
        assert runtime.metrics is not first_metrics
        assert runtime.settings.bambulab_serial == "FAKE00TEST000002"
    finally:
        runtime.stop()


def test_collector_start_failure_retries() -> None:
    class _Broken(_Client):
        def connect(self) -> None:
            raise OSError("connection refused")

    made = {"n": 0}

    def client_factory(_s: Settings):
        made["n"] += 1
        return _Broken() if made["n"] == 1 else _Client()

    runtime = rt.ExporterRuntime(
        settings_factory=_local,
        validate=lambda s: None,
        client_factory=client_factory,
        discover=lambda s: None,
        retry_seconds=0.05,
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
        assert made["n"] == 2
    finally:
        runtime.stop()


def test_stop_while_waiting_returns_promptly() -> None:
    runtime = _runtime([_local(bambulab_host="")], validate=lambda s: None)
    runtime.start()
    _wait_until(lambda: runtime.status()["state"] == rt.STATE_SETUP_REQUIRED)
    started = time.monotonic()
    runtime.stop()
    assert time.monotonic() - started < 2
    assert not any(t.name == "exporter-runtime" and t.is_alive() for t in threading.enumerate())


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_missing_settings_per_transport() -> None:
    assert rt.missing_settings(_local()) == []
    assert rt.missing_settings(_local(bambulab_access_code="")) == ["BAMBULAB_ACCESS_CODE"]
    cloud = _local(bambulab_transport="cloud_mqtt", bambulab_host="", bambulab_access_code="")
    assert rt.missing_settings(cloud) == []
    assert rt.missing_settings(_local(bambulab_transport="cloud_mqtt", bambulab_serial="")) == [
        "BAMBULAB_SERIAL"
    ]


def test_printer_label_prefers_label_override() -> None:
    assert rt.printer_label(_local(printer_name_label="lab", bambulab_printer_name="x")) == "lab"
    assert rt.printer_label(_local(bambulab_printer_name="x")) == "x"
    assert rt.printer_label(_local()) == "bambulab"


def test_discover_cloud_metadata_sets_name_and_model(monkeypatch) -> None:
    monkeypatch.delenv("PRINTER_NAME_LABEL", raising=False)
    settings = _local(bambulab_transport="cloud_mqtt", bambulab_cloud_access_token="fake-token")
    devices = [{"dev_id": "FAKE00TEST000001", "name": "Test Printer", "model": "P1S"}]
    with patch("bambulab_metrics_exporter.runtime.get_bind_devices", return_value=devices):
        rt.discover_cloud_metadata(settings)
    assert settings.bambulab_printer_name == "Test Printer"
    assert settings.bambulab_printer_model == "P1S"
    assert os.environ["BAMBULAB_PRINTER_MODEL"] == "P1S"


def test_discover_cloud_metadata_failure_is_non_fatal(caplog) -> None:
    settings = _local(bambulab_transport="cloud_mqtt", bambulab_cloud_access_token="fake-token")
    with patch("bambulab_metrics_exporter.runtime.get_bind_devices", side_effect=Exception("API")):
        rt.discover_cloud_metadata(settings)
    assert "Metadata discovery from cloud failed (non-fatal)" in caplog.text


def test_discover_cloud_metadata_skips_local_and_missing_token() -> None:
    with patch("bambulab_metrics_exporter.runtime.get_bind_devices") as bind:
        rt.discover_cloud_metadata(_local())
        rt.discover_cloud_metadata(_local(bambulab_transport="cloud_mqtt"))
    bind.assert_not_called()


def test_new_store_credentials_are_used_on_first_retry(tmp_path: Path, monkeypatch, caplog) -> None:
    """After bambulab-reauth writes the store, the first attempt must use the new token
    instead of re-probing the already rejected env token."""
    from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials

    caplog.set_level(logging.INFO)
    secret = "fake-development-key-never-use"
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", secret)
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_SERIAL", "FAKE00TEST000001")
    monkeypatch.setenv("BAMBULAB_CLOUD_USER_ID", "u")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "stale_token")
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LISTEN_PORT", "9110")
    seen_tokens: list[str] = []

    def validate(s: Settings) -> None:
        seen_tokens.append(s.bambulab_cloud_access_token)
        if s.bambulab_cloud_access_token != "fresh_token":
            raise ReauthRequiredError("token expired")

    runtime = rt.ExporterRuntime(
        settings_factory=Settings,
        validate=validate,
        client_factory=lambda s: _Client(),
        discover=lambda s: None,
        store_poll_seconds=0.02,
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_AUTH_REQUIRED)
        assert "http://<docker-host>:9110/auth" in caplog.text
        save_encrypted_credentials(
            tmp_path / "credentials.enc.json",
            secret,
            {
                "BAMBULAB_CLOUD_USER_ID": "u",
                "BAMBULAB_CLOUD_ACCESS_TOKEN": "fresh_token",
                "BAMBULAB_CLOUD_REFRESH_TOKEN": "fresh_refresh",
            },
        )
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
    finally:
        runtime.stop()

    assert seen_tokens == ["stale_token", "fresh_token"]
    assert "New encrypted credentials found" in caplog.text
    assert "fresh_token" not in caplog.text


# ---------------------------------------------------------------------------
# Review fixes
# ---------------------------------------------------------------------------

def test_metrics_relabelled_after_cloud_discovery() -> None:
    """Regression: the registry was built before discovery, labelling every series
    printer_name="bambulab" for cloud users without PRINTER_NAME_LABEL."""

    def discover(s: Settings) -> None:
        s.bambulab_printer_name = "Test Printer"

    runtime = rt.ExporterRuntime(
        settings_factory=lambda: _local(bambulab_transport="cloud_mqtt"),
        validate=lambda s: None,
        client_factory=lambda s: _Client(),
        discover=discover,
    )
    assert runtime.metrics._base_labels["printer_name"] == "bambulab"
    runtime.start()
    try:
        _wait_until(lambda: runtime.ready)
        assert runtime.metrics._base_labels["printer_name"] == "Test Printer"
        runtime.reconfigure()
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING and runtime.ready)
        assert runtime.metrics._base_labels["printer_name"] == "Test Printer"
    finally:
        runtime.stop()


def test_runtime_survives_unexpected_errors() -> None:
    calls = {"n": 0}

    def flaky_discover(_s: Settings) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise AttributeError("'str' object has no attribute 'get'")

    runtime = rt.ExporterRuntime(
        settings_factory=_local,
        validate=lambda s: None,
        client_factory=lambda s: _Client(),
        discover=flaky_discover,
        retry_seconds=0.05,
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
        assert calls["n"] == 2
        assert runtime._thread is not None and runtime._thread.is_alive()
    finally:
        runtime.stop()


def test_client_factory_error_is_retried() -> None:
    made = {"n": 0}

    def client_factory(_s: Settings) -> _Client:
        made["n"] += 1
        if made["n"] == 1:
            raise ValueError("bad settings")
        return _Client()

    runtime = rt.ExporterRuntime(
        settings_factory=_local, validate=lambda s: None, client_factory=client_factory,
        discover=lambda s: None, retry_seconds=0.05,
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
    finally:
        runtime.stop()


def test_auth_wait_retries_periodically() -> None:
    """An outage that looked like a rejection must clear by itself once the broker is back."""
    attempts = {"n": 0}

    def validate(_s: Settings) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ReauthRequiredError("token expired")

    runtime = rt.ExporterRuntime(
        settings_factory=lambda: _local(bambulab_transport="cloud_mqtt"),
        validate=validate, client_factory=lambda s: _Client(), discover=lambda s: None,
        store_poll_seconds=0.01, auth_retry_seconds=0.05,
    )
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_RUNNING)
        assert attempts["n"] == 2
    finally:
        runtime.stop()


def test_invalid_settings_at_construction_do_not_raise() -> None:
    def broken() -> Settings:
        raise ValueError("Unsupported transport 'lan'")

    runtime = rt.ExporterRuntime(settings_factory=broken, validate=lambda s: None)
    status = runtime.status()
    assert status["state"] == rt.STATE_SETUP_REQUIRED
    assert "Unsupported transport" in status["message"]


def test_ready_is_sticky_across_reconfigure() -> None:
    runtime = _runtime([_local()], validate=lambda s: None)
    runtime.start()
    try:
        _wait_until(lambda: runtime.ready)
        runtime.reconfigure()
        assert runtime.ready is True  # stays ready while reconnecting, as /ready always was
    finally:
        runtime.stop()


def test_reconfigure_reports_connecting_immediately() -> None:
    runtime = _runtime([_local(bambulab_host="")], validate=lambda s: None)
    runtime.start()
    try:
        _wait_until(lambda: runtime.status()["state"] == rt.STATE_SETUP_REQUIRED)
        runtime.reconfigure()
        assert runtime.status()["state"] in {rt.STATE_CONNECTING, rt.STATE_SETUP_REQUIRED}
        assert runtime.status()["message"] in {"", "Missing settings: BAMBULAB_HOST"}
    finally:
        runtime.stop()


def test_wait_keeps_a_wakeup_that_arrives_after_timeout() -> None:
    runtime = _runtime([_local()], validate=lambda s: None)
    assert runtime._wait(0.0) is False
    runtime._wake.set()  # reconfigure() just after the timeout expired
    assert runtime._wait(0.0) is True  # not lost
    assert runtime._wait(0.0) is False


def test_page_overrides_do_not_leak_into_env_file(tmp_path: Path, monkeypatch) -> None:
    """Regression: saved /auth values (incl. the access code) were written to .env, so
    "Reset to env vars" came back after a restart."""
    from bambulab_metrics_exporter import overrides

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("BAMBULAB_HOST=192.0.2.10\n")
    overrides.set_env("BAMBULAB_HOST", "192.0.2.99")
    overrides.set_env("BAMBULAB_ACCESS_CODE", "page-access-code")

    runtime = _runtime([_local(bambulab_host="192.0.2.99")], validate=lambda s: None)
    runtime.start()
    try:
        _wait_until(lambda: runtime.ready)
    finally:
        runtime.stop()

    env_text = (tmp_path / ".env").read_text()
    assert "BAMBULAB_HOST=192.0.2.10" in env_text
    assert "page-access-code" not in env_text
