"""Connection lifecycle that runs behind the web server.

The HTTP server starts first so /health, /auth and /metrics are reachable while the
exporter connects, waits for credentials, or retries after an outage. A background thread
validates the configuration, starts the collector, and restarts it whenever the /auth page
saves new settings or ``bambulab-reauth`` writes new credentials.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.cloud_auth import get_bind_devices
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.env_sync import sync_env_file
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.overrides import overridden_keys
from bambulab_metrics_exporter.reauth import (
    apply_credentials,
    credentials_path,
    load_stored_credentials,
    log_reauth_banner,
)
from bambulab_metrics_exporter.startup import ReauthRequiredError, startup_validate

logger = logging.getLogger(__name__)

STATE_STARTING = "starting"
STATE_CONNECTING = "connecting"
STATE_RUNNING = "running"
STATE_SETUP_REQUIRED = "setup_required"
STATE_AUTH_REQUIRED = "auth_required"
STATE_ERROR = "error"

RETRY_SECONDS = 60.0
# While waiting for a login, still re-check periodically: a broker outage can look like a
# rejection, and it should clear by itself once the broker is back.
AUTH_RETRY_SECONDS = 300.0
STORE_POLL_SECONDS = 5.0


def printer_label(settings: Settings) -> str:
    return settings.printer_name_label or settings.bambulab_printer_name or "bambulab"


def missing_settings(settings: Settings) -> list[str]:
    """Settings that must be provided (env or /auth page) before connecting."""
    if settings.bambulab_transport == "local_mqtt":
        required = {
            "BAMBULAB_HOST": settings.bambulab_host,
            "BAMBULAB_SERIAL": settings.bambulab_serial,
            "BAMBULAB_ACCESS_CODE": settings.bambulab_access_code,
        }
    else:
        required = {"BAMBULAB_SERIAL": settings.bambulab_serial}
    return [key for key, value in required.items() if not value]


def discover_cloud_metadata(settings: Settings) -> None:
    """Fill printer name/model from the cloud device list (best effort, in place)."""
    if settings.bambulab_transport != "cloud_mqtt" or not settings.bambulab_cloud_access_token:
        return
    try:
        devices = get_bind_devices(
            settings.bambulab_cloud_access_token, timeout_seconds=settings.request_timeout_seconds
        )
        device = next(
            (
                d
                for d in devices
                if isinstance(d, dict) and d.get("dev_id") == settings.bambulab_serial
            ),
            None,
        )
    except Exception:  # noqa: BLE001 - metadata is optional, payload is untrusted
        logger.warning("Metadata discovery from cloud failed (non-fatal)")
        return
    if not device:
        return
    name = str(device.get("name") or "")
    model = str(device.get("model") or device.get("dev_product_name") or "")
    if name:
        os.environ["BAMBULAB_PRINTER_NAME"] = name
        if not settings.printer_name_label:
            settings.bambulab_printer_name = name
    if model:
        os.environ["BAMBULAB_PRINTER_MODEL"] = model
        settings.bambulab_printer_model = model


def _store_fingerprint(path: Path) -> tuple[float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


class ExporterRuntime:
    """Owns settings, metrics registry, client and collector for one printer."""

    def __init__(
        self,
        settings_factory: Callable[[], Settings] = Settings,
        validate: Callable[[Settings], None] = startup_validate,
        client_factory: Callable[[Settings], BambuClient] = build_client,
        discover: Callable[[Settings], None] = discover_cloud_metadata,
        retry_seconds: float = RETRY_SECONDS,
        store_poll_seconds: float = STORE_POLL_SECONDS,
        auth_retry_seconds: float = AUTH_RETRY_SECONDS,
    ) -> None:
        self._settings_factory = settings_factory
        self._validate = validate
        self._client_factory = client_factory
        self._discover = discover
        self._retry_seconds = retry_seconds
        self._store_poll_seconds = store_poll_seconds
        self._auth_retry_seconds = auth_retry_seconds

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.state = STATE_STARTING
        self.message = ""
        try:
            self.settings = settings_factory()
        except Exception as exc:  # noqa: BLE001 - invalid env must not stop the web server
            self.settings = Settings.model_construct()
            self.state = STATE_SETUP_REQUIRED
            self.message = f"Invalid configuration: {exc}"
        self._metrics_identity = ("", "")
        self.metrics = ExporterMetrics(printer_name="", serial="")
        self._ensure_metrics(self.settings)
        self.collector: PollingCollector | None = None
        self._ever_ready = False
        # One immediate retry when the store changes during validation (see _run_once).
        self._store_retry_used = False

    # -- public API -------------------------------------------------------

    @property
    def ready(self) -> bool:
        """Sticky: true once data has arrived, as /ready always was. Reset only when the
        printer identity changes (new metrics registry)."""
        collector = self.collector
        if collector is not None and collector.ready:
            self._ever_ready = True
        return self._ever_ready

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="exporter-runtime", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._stop_collector()

    def reconfigure(self) -> None:
        """Re-read settings (env + saved overrides) and reconnect."""
        logger.info("Configuration changed; reconnecting")
        # Report the new state right away, so a page rendered before the runtime thread
        # wakes does not still show the old error.
        self._set_state(STATE_CONNECTING)
        self._wake.set()

    def _on_auth_rejected(self) -> None:
        """Called from the collector thread when the broker rejects running credentials:
        re-run validation (token refresh, then re-authentication) like a settings change."""
        self.reconfigure()

    def status(self) -> dict[str, str]:
        with self._lock:
            return {
                "state": self.state,
                "message": self.message,
                "transport": str(self.settings.bambulab_transport),
            }

    # -- lifecycle --------------------------------------------------------

    def _set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            self.state = state
            self.message = message

    def _stop_collector(self) -> None:
        with self._lock:
            collector, self.collector = self.collector, None
        if collector is not None:
            try:
                collector.stop()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                logger.exception("Collector shutdown failed")

    def _wait(self, timeout: float | None) -> bool:
        """Wait for a wake-up (settings changed) or timeout. Returns True when woken.

        The event is only cleared after a wake-up, so a reconfigure() that arrives just as
        a timeout expires is not lost.
        """
        woken = self._wake.wait(timeout)
        if woken:
            self._wake.clear()
        return woken

    def _wait_for_credentials(self) -> None:
        """Wait for the page (wake-up), a change of the encrypted store (CLI), or the
        periodic retry, which also recovers from outages that looked like rejections."""
        path = credentials_path(self.settings)
        seen = _store_fingerprint(path)
        deadline = time.monotonic() + self._auth_retry_seconds
        while not self._stop.is_set():
            if self._wait(self._store_poll_seconds):
                return
            if _store_fingerprint(path) != seen:
                # Use the new file right away: the env tokens were already rejected, so
                # retrying them first would only add failed connection attempts.
                payload = load_stored_credentials(self.settings)
                if payload:
                    apply_credentials(self.settings, payload)
                    logger.info("New encrypted credentials found; connecting with them")
                else:
                    logger.info("Encrypted credentials changed; retrying connection")
                return
            if time.monotonic() >= deadline:
                logger.info("Retrying the cloud connection")
                return

    def _ensure_metrics(self, settings: Settings) -> None:
        """Rebuild the registry when the printer label or serial (series identity) changed,
        for example after cloud discovery fills in the printer name."""
        identity = (printer_label(settings), str(settings.bambulab_serial))
        if identity != self._metrics_identity:
            self.metrics = ExporterMetrics(printer_name=identity[0], serial=identity[1])
            self._metrics_identity = identity
            self._ever_ready = False

    def _load_settings(self) -> Settings:
        settings = self._settings_factory()
        self.settings = settings
        self._ensure_metrics(settings)
        return settings

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_once()
            except Exception as exc:  # noqa: BLE001 - the runtime thread must never die
                logger.exception("Unexpected runtime error; retrying in %.0fs", self._retry_seconds)
                self._stop_collector()
                self._set_state(STATE_ERROR, f"Unexpected error: {exc}")
                self._wait(self._retry_seconds)
        self._stop_collector()

    def _run_once(self) -> None:
        self._stop_collector()
        try:
            settings = self._load_settings()
        except Exception as exc:  # noqa: BLE001 - invalid env must not kill the server
            self._set_state(STATE_SETUP_REQUIRED, f"Invalid configuration: {exc}")
            logger.error("Invalid configuration; fix it on the /auth page or in env vars")
            self._wait(None)
            return

        missing = missing_settings(settings)
        if missing:
            self._set_state(STATE_SETUP_REQUIRED, "Missing settings: " + ", ".join(missing))
            logger.error(
                "Missing settings (%s); open the /auth page to configure the printer",
                ", ".join(missing),
            )
            self._wait(None)
            return

        self._set_state(STATE_CONNECTING)
        self._discover(settings)
        self._ensure_metrics(settings)
        store = credentials_path(settings)
        store_before = _store_fingerprint(store)
        try:
            self._validate(settings)
        except ReauthRequiredError as exc:
            if self._stop.is_set():
                return
            log_reauth_banner(str(exc), port=settings.listen_port)
            self._set_state(STATE_AUTH_REQUIRED, f"Re-authentication required: {exc}")
            if _store_fingerprint(store) != store_before and not self._store_retry_used:
                # `bambulab-reauth` wrote new credentials while validation ran; use them
                # now instead of waiting for the next periodic retry. Only once in a row,
                # since a token refresh during validation also writes the store.
                self._store_retry_used = True
                payload = load_stored_credentials(self.settings)
                if payload:
                    apply_credentials(self.settings, payload)
                logger.info("Encrypted credentials changed during validation; retrying")
                return
            self._wait_for_credentials()
            return
        except Exception as exc:  # noqa: BLE001 - retry later instead of exiting
            self._set_state(STATE_ERROR, str(exc))
            logger.error("Connection failed: %s. Retrying in %.0fs", exc, self._retry_seconds)
            self._wait(self._retry_seconds)
            return

        if self._stop.is_set():
            return
        # Validation may have refreshed tokens or discovered metadata.
        self._ensure_metrics(settings)
        try:
            # Values saved on the /auth page stay out of .env, so "Reset to env vars" is
            # not undone by the next restart.
            sync_env_file(Path(".env"), exclude=overridden_keys())
        except (OSError, UnicodeError):
            logger.warning("Skipping .env sync (not writable or not UTF-8)")

        if self._stop.is_set():
            return
        collector = PollingCollector(
            client=self._client_factory(settings),
            metrics=self.metrics,
            settings=settings,
            on_auth_rejected=self._on_auth_rejected,
        )
        try:
            collector.start()
        except Exception as exc:  # noqa: BLE001
            self._set_state(STATE_ERROR, f"Could not start collector: {exc}")
            logger.exception("Collector start failed; retrying in %.0fs", self._retry_seconds)
            self._wait(self._retry_seconds)
            return
        with self._lock:
            self.collector = collector
        self._store_retry_used = False
        self._set_state(STATE_RUNNING)
        logger.info("Exporter connected (%s)", settings.bambulab_transport)
        self._wait(None)  # until reconfigure() or stop()
