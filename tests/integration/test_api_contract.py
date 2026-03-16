from __future__ import annotations

from fastapi.testclient import TestClient

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.metrics import ExporterMetrics


class _CollectorStub:
    def __init__(self, ready: bool) -> None:
        self.ready = ready


def test_ready_and_metrics_contract() -> None:
    metrics = ExporterMetrics(printer_name="integration", serial="SN-I")
    collector = _CollectorStub(ready=False)
    app = build_app(metrics=metrics, collector=collector)  # type: ignore[arg-type]
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    not_ready = client.get("/ready")
    assert not_ready.status_code == 503
    assert not_ready.json()["detail"] == "warming_up"

    collector.ready = True
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}

    metrics_text = client.get("/metrics").text
    assert "bambulab_printer_up" in metrics_text
