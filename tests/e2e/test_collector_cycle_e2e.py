from __future__ import annotations

import time

from fastapi.testclient import TestClient

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


class _E2EClient:
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        assert timeout_seconds >= 0
        return PrinterSnapshot(
            connected=True,
            raw={
                "print": {
                    "gcode_state": "RUNNING",
                    "mc_percent": 42,
                    "nozzle_temper": 205,
                }
            },
        )


def test_e2e_collector_populates_metrics_and_readiness() -> None:
    settings = Settings.model_construct(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_port=8883,
        bambulab_serial="SN-E2E",
        bambulab_access_code="x",
        polling_interval_seconds=0.1,
        request_timeout_seconds=0.1,
        listen_host="127.0.0.1",
        listen_port=9109,
        log_level="INFO",
    )

    metrics = ExporterMetrics(printer_name="e2e", serial="SN-E2E")
    client = _E2EClient()
    collector = PollingCollector(client=client, metrics=metrics, settings=settings)

    collector.start()
    try:
        time.sleep(0.25)
        assert collector.ready is True

        app = build_app(metrics=metrics, collector=collector)
        http = TestClient(app)

        ready = http.get("/ready")
        assert ready.status_code == 200

        out = http.get("/metrics").text
        assert 'bambulab_print_progress_percent{printer_name="e2e",serial="SN-E2E"} 42.0' in out
        assert 'bambulab_nozzle_temperature_celsius{printer_name="e2e",serial="SN-E2E"} 205.0' in out
    finally:
        collector.stop()
        assert client.connected is False
