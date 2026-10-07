from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics

logger = logging.getLogger(__name__)


class PollingCollector:
    def __init__(
        self,
        client: BambuClient,
        metrics: ExporterMetrics,
        settings: Settings,
        on_auth_rejected: Callable[[], None] | None = None,
    ) -> None:
        self._client = client
        self._on_auth_rejected = on_auth_rejected
        self._auth_reported = False
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
            # A fetch can wait up to request_timeout_seconds for the first report.
            self._thread.join(timeout=max(5.0, self._settings.request_timeout_seconds + 2.0))
        self._client.disconnect()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            success = False
            try:
                snapshot = self._client.fetch_snapshot(self._settings.request_timeout_seconds)
                if self._stop.is_set():
                    # Stopped (reconfigure/shutdown) during the fetch: the registry may
                    # already belong to the next collector.
                    return
                self._metrics.update_from_snapshot(snapshot)
                success = True
                if snapshot.raw:
                    self._ready = True
            except Exception:
                logger.exception("Polling cycle failed")
            finally:
                elapsed = time.monotonic() - started
                if not self._stop.is_set():
                    self._metrics.mark_scrape(
                        duration_seconds=elapsed, success=success, now_ts=time.time()
                    )

            self._check_auth_rejected()
            wait = max(self._settings.polling_interval_seconds - elapsed, 0.1)
            self._stop.wait(wait)

    def _check_auth_rejected(self) -> None:
        """Report a credential rejection seen while running (expired or revoked cloud token,
        changed access code) once, so the runtime can refresh or ask for a new login
        instead of reconnecting with rejected credentials forever."""
        if self._auth_reported or self._on_auth_rejected is None:
            return
        if not getattr(self._client, "auth_rejected", False):
            return
        self._auth_reported = True
        logger.warning("The broker rejected the credentials while running; re-validating")
        try:
            self._on_auth_rejected()
        except Exception:  # noqa: BLE001 - the polling loop must keep running
            logger.exception("Credential rejection handler failed")
