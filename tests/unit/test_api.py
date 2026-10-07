"""Tests for bambulab_metrics_exporter.api."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.metrics import ExporterMetrics


class _CollectorStub:
    def __init__(self, ready: bool) -> None:
        self.ready = ready


# ---------------------------------------------------------------------------
# /health and /metrics
# ---------------------------------------------------------------------------

def test_health_and_metrics_endpoint() -> None:
    metrics = ExporterMetrics(printer_name="x1c", serial="SN123")
    # Set a value to ensure metrics have labels in output
    metrics.printer_up.labels(printer_name="x1c", serial="SN123").set(1.0)
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True))
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    m = client.get("/metrics")
    assert m.status_code == 200
    assert "bambulab_printer_up" in m.text
    assert 'serial="SN123"' in m.text


def test_ready_endpoint_warmup() -> None:
    metrics = ExporterMetrics(printer_name="x1c", serial="SN123")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=False))
    client = TestClient(app)

    ready = client.get("/ready")
    assert ready.status_code == 503


# ---------------------------------------------------------------------------
# / root endpoint: state and settings branches
# ---------------------------------------------------------------------------

def test_root_endpoint_warming_up_no_settings() -> None:
    """Root handler with collector NOT ready and no settings."""
    metrics = ExporterMetrics(printer_name="x1c", serial="SN001")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=False))
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Warming Up" in resp.text
    assert "warming" in resp.text


def test_root_endpoint_ready_no_settings() -> None:
    """Root handler with collector ready and no settings (settings=None)."""
    metrics = ExporterMetrics(printer_name="x1c", serial="SN002")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True))
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Connected" in resp.text


def test_root_endpoint_with_printer_name_in_settings() -> None:
    """Root handler with settings providing a printer name → badge shown."""
    from bambulab_metrics_exporter.config import Settings

    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SN003",
        bambulab_access_code="abc",
        bambulab_printer_name="MyPrinter",
    )
    metrics = ExporterMetrics(printer_name="x1c", serial="SN003")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True), settings=settings)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "MyPrinter" in resp.text
    assert "printer-badge" in resp.text


def test_root_endpoint_with_settings_no_printer_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Root handler with settings where printer name is empty → no badge span."""
    from bambulab_metrics_exporter.config import Settings

    # Clear any leaked env vars that might inject a printer name
    monkeypatch.delenv("BAMBULAB_PRINTER_NAME", raising=False)
    monkeypatch.delenv("BAMBULAB_PRINTER_NAME_LABEL", raising=False)

    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SN004",
        bambulab_access_code="abc",
    )
    metrics = ExporterMetrics(printer_name="x1c", serial="SN004")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True), settings=settings)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    # When no printer name, the badge span element should not appear (printer_badge == "")
    assert '<span class="printer-badge">' not in resp.text


def test_ready_endpoint_when_ready() -> None:
    """Ready endpoint returns 200 when collector is ready."""
    metrics = ExporterMetrics(printer_name="x1c", serial="SN005")
    app = build_app(metrics=metrics, collector=_CollectorStub(ready=True))
    client = TestClient(app)

    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# Landing page: printer state, attention banner, last update
# ---------------------------------------------------------------------------

class _StatusRuntime:
    def __init__(self, state: str, ready: bool = False, transport: str = "cloud_mqtt") -> None:
        from bambulab_metrics_exporter.config import Settings

        self.settings = Settings(
            bambulab_transport=transport, bambulab_serial="FAKE00TEST000001",
            polling_interval_seconds=10,
        )
        self.metrics = ExporterMetrics(printer_name="test", serial="FAKE00TEST000001")
        self.ready = ready
        self._state = state

    def status(self) -> dict[str, str]:
        return {"state": self._state, "message": "", "transport": self.settings.bambulab_transport}

    def reconfigure(self) -> None:
        pass


def _root(state: str, **kw) -> str:
    return TestClient(build_app(runtime=_StatusRuntime(state, **kw))).get("/").text


@pytest.mark.parametrize(
    ("state", "ready", "label", "alert"),
    [
        ("running", True, "Connected", None),
        ("running", False, "Warming Up", None),
        ("connecting", False, "Connecting", None),
        ("auth_required", False, "Login required", "Bambu Cloud login required"),
        ("setup_required", False, "Setup required", "Printer not configured"),
        ("error", False, "Connection error", "Cannot reach the printer"),
    ],
)
def test_root_printer_state_and_alert(state: str, ready: bool, label: str, alert: str | None) -> None:
    page = _root(state, ready=ready)
    assert f'<span class="pill-dot"></span>{label}</span>' in page
    if alert:
        assert alert in page and 'class="alert' in page and 'href="/auth"' in page
    else:
        assert 'class="alert' not in page


def test_root_shows_mode_badge() -> None:
    assert '<span class="badge">Bambu Cloud</span>' in _root("running", ready=True)
    assert '<span class="badge">Local (LAN)</span>' in _root("running", ready=True, transport="local_mqtt")


def test_root_refreshes_fast_only_while_connecting() -> None:
    assert 'content="3"' in _root("connecting")
    assert 'content="3"' in _root("running", ready=False)
    assert 'content="15"' in _root("running", ready=True)
    assert 'content="15"' in _root("auth_required")


def test_root_last_update_never_then_recent() -> None:
    import time as _time

    runtime = _StatusRuntime("running", ready=True)
    client = TestClient(build_app(runtime=runtime))
    page = client.get("/").text
    assert "Never" in page and "Polling every 10s" in page

    runtime.metrics.mark_scrape(duration_seconds=0.1, success=True, now_ts=_time.time() - 5)
    page = client.get("/").text
    assert 'class="card-value fresh"' in page and "s ago" in page


@pytest.mark.parametrize(
    ("age", "text", "css"),
    [(5, "5s ago", "fresh"), (29, "29s ago", "fresh"), (45, "45s ago", "stale"),
     (125, "2m ago", "stale"), (7300, "2h ago", "stale")],
)
def test_last_update_formatting(age: float, text: str, css: str) -> None:
    from bambulab_metrics_exporter.api import _last_update

    assert _last_update(1000.0 - age, 10.0, 1000.0) == (text, css)
    assert _last_update(None, 10.0, 1000.0) == ("Never", "none")


def test_metrics_last_success_timestamp() -> None:
    metrics = ExporterMetrics(printer_name="x", serial="FAKE00TEST000001")
    assert metrics.last_success_timestamp() is None
    metrics.mark_scrape(duration_seconds=0.1, success=False, now_ts=100.0)
    assert metrics.last_success_timestamp() is None
    metrics.mark_scrape(duration_seconds=0.1, success=True, now_ts=123.0)
    assert metrics.last_success_timestamp() == 123.0
