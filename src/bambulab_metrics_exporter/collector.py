from __future__ import annotations

import logging
import threading
import time

from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics

logger = logging.getLogger(__name__)


class PollingCollector:
    def __init__(self, client: BambuClient, metrics: ExporterMetrics, settings: Settings) -> None:
        self._client = client
        self._metrics = metrics
        self._settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        self._client.connect()
        self._thread = threading.Thread(target=self._run_loop, name="collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._client.disconnect()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            success = False
            try:
                snapshot = self._client.fetch_snapshot(self._settings.request_timeout_seconds)
                self._metrics.update_from_snapshot(snapshot)
                success = True
                if snapshot.raw:
                    self._ready = True
            except Exception:
                logger.exception("Polling cycle failed")
            finally:
                elapsed = time.monotonic() - started
                self._metrics.mark_scrape(duration_seconds=elapsed, success=success, now_ts=time.time())

            wait = max(self._settings.polling_interval_seconds - elapsed, 0.1)
            self._stop.wait(wait)
