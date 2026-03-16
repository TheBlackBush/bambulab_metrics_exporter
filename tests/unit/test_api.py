from fastapi.testclient import TestClient

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.metrics import ExporterMetrics


class _CollectorStub:
    def __init__(self, ready: bool) -> None:
        self.ready = ready


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
