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
# / root endpoint — state and settings branches
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
