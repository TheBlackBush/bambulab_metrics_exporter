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


def _settings() -> Settings:
    return Settings(
        bambulab_transport="local_mqtt", bambulab_host="h", bambulab_serial="s",
        bambulab_access_code="a", polling_interval_seconds=0.05, request_timeout_seconds=0.05,
    )


class _RejectedClient(_ClientStub):
    auth_rejected = True


def test_auth_rejection_while_running_is_reported_once() -> None:
    calls: list[int] = []
    client = _RejectedClient(PrinterSnapshot(connected=False, raw={}))
    collector = PollingCollector(
        client=client, metrics=ExporterMetrics(printer_name="x", serial="s"),
        settings=_settings(), on_auth_rejected=lambda: calls.append(1),
    )
    collector.start()
    deadline = time.monotonic() + 2
    while client.fetch_calls < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    collector.stop()
    assert calls == [1]


def test_rejection_handler_errors_do_not_stop_polling() -> None:
    def boom() -> None:
        raise RuntimeError("handler failed")

    client = _RejectedClient(PrinterSnapshot(connected=False, raw={}))
    collector = PollingCollector(
        client=client, metrics=ExporterMetrics(printer_name="x", serial="s"),
        settings=_settings(), on_auth_rejected=boom,
    )
    collector.start()
    deadline = time.monotonic() + 2
    while client.fetch_calls < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    collector.stop()
    assert client.fetch_calls >= 3


def test_stop_during_fetch_leaves_metrics_untouched() -> None:
    """Regression: a fetch that outlived stop() wrote into the next collector's registry."""
    import threading

    in_fetch = threading.Event()

    class _SlowClient(_ClientStub):
        collector: PollingCollector

        def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
            self.fetch_calls += 1
            in_fetch.set()
            while not self.collector._stop.is_set():
                time.sleep(0.01)
            return self.snapshot

    metrics = ExporterMetrics(printer_name="x", serial="s")
    client = _SlowClient(PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 42}}))
    collector = PollingCollector(client=client, metrics=metrics, settings=_settings())
    client.collector = collector
    collector.start()
    assert in_fetch.wait(2)
    collector.stop()
    names = {s.name for m in metrics.registry.collect() for s in m.samples}
    assert "bambulab_print_progress_percent" not in names
    assert "bambulab_exporter_scrape_success" not in names
