from __future__ import annotations

import time

from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


class _ClientStub:
    def __init__(self, snapshot: PrinterSnapshot) -> None:
        self.snapshot = snapshot
        self.connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.fetch_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        self.fetch_calls += 1
        return self.snapshot


def test_collector_start_stop_and_ready() -> None:
    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="h",
        bambulab_serial="s",
        bambulab_access_code="a",
        polling_interval_seconds=0.1,
    )
    metrics = ExporterMetrics(printer_name="x", serial="s")
    snapshot = PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 10}})
    client = _ClientStub(snapshot)

    collector = PollingCollector(client=client, metrics=metrics, settings=settings)
    collector.start()
    time.sleep(0.25)
    collector.stop()

    assert client.connect_calls == 1
    assert client.disconnect_calls == 1
    assert client.fetch_calls >= 1
    assert collector.ready is True
