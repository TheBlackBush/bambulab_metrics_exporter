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
from collections.abc import Callable
from pathlib import Path

from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.cloud_auth import get_bind_devices
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.env_sync import sync_env_file
from bambulab_metrics_exporter.metrics import ExporterMetrics
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
    except Exception:  # noqa: BLE001 - metadata is optional
        logger.warning("Metadata discovery from cloud failed (non-fatal)")
        return
    device = next((d for d in devices if d.get("dev_id") == settings.bambulab_serial), None)
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
    ) -> None:
        self._settings_factory = settings_factory
        self._validate = validate
        self._client_factory = client_factory
        self._discover = discover
        self._retry_seconds = retry_seconds
        self._store_poll_seconds = store_poll_seconds

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.settings = settings_factory()
        self.metrics = ExporterMetrics(
            printer_name=printer_label(self.settings), serial=self.settings.bambulab_serial
        )
        self.collector: PollingCollector | None = None
        self.state = STATE_STARTING
        self.message = ""

    # -- public API -------------------------------------------------------

    @property
    def ready(self) -> bool:
        collector = self.collector
        return collector is not None and collector.ready

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
        self._wake.set()

    def status(self) -> dict[str, str]:
        with self._lock:
            return {
                "state": self.state,
                "message": self.message,
                "transport": self.settings.bambulab_transport,
            }

    # -- lifecycle --------------------------------------------------------

    def _set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            self.state = state
            self.message = message

    def _stop_collector(self) -> None:
        collector, self.collector = self.collector, None
        if collector is not None:
            try:
                collector.stop()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                logger.exception("Collector shutdown failed")

    def _wait(self, timeout: float | None) -> bool:
        """Wait for a wake-up (settings changed) or timeout. Returns True when woken."""
        woken = self._wake.wait(timeout)
        self._wake.clear()
        return woken

    def _wait_for_credentials(self) -> None:
        """Wait until the page saves settings or the encrypted store changes (CLI)."""
        path = credentials_path(self.settings)
        seen = _store_fingerprint(path)
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

    def _load_settings(self) -> Settings:
        settings = self._settings_factory()
        if (
            printer_label(settings) != printer_label(self.settings)
            or settings.bambulab_serial != self.settings.bambulab_serial
        ):
            self.metrics = ExporterMetrics(
                printer_name=printer_label(settings), serial=settings.bambulab_serial
            )
        self.settings = settings
        return settings

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop_collector()
            try:
                settings = self._load_settings()
            except Exception as exc:  # noqa: BLE001 - invalid env must not kill the server
                self._set_state(STATE_SETUP_REQUIRED, f"Invalid configuration: {exc}")
                logger.error("Invalid configuration; fix it on the /auth page or in env vars")
                self._wait(None)
                continue

            missing = missing_settings(settings)
            if missing:
                self._set_state(
                    STATE_SETUP_REQUIRED, "Missing settings: " + ", ".join(missing)
                )
                logger.error(
                    "Missing settings (%s); open the /auth page to configure the printer",
                    ", ".join(missing),
                )
                self._wait(None)
                continue

            self._set_state(STATE_CONNECTING)
            self._discover(settings)
            try:
                self._validate(settings)
            except ReauthRequiredError as exc:
                self._set_state(STATE_AUTH_REQUIRED, f"Re-authentication required: {exc}")
                log_reauth_banner(str(exc), port=settings.listen_port)
                self._wait_for_credentials()
                continue
            except Exception as exc:  # noqa: BLE001 - retry later instead of exiting
                self._set_state(STATE_ERROR, str(exc))
                logger.error("Connection failed: %s. Retrying in %.0fs", exc, self._retry_seconds)
                self._wait(self._retry_seconds)
                continue

            try:
                sync_env_file(Path(".env"))
            except OSError:
                logger.warning("Skipping .env sync (not writable)")

            collector = PollingCollector(
                client=self._client_factory(settings), metrics=self.metrics, settings=settings
            )
            try:
                collector.start()
            except Exception as exc:  # noqa: BLE001
                self._set_state(STATE_ERROR, f"Could not start collector: {exc}")
                logger.exception("Collector start failed; retrying in %.0fs", self._retry_seconds)
                self._wait(self._retry_seconds)
                continue
            self.collector = collector
            self._set_state(STATE_RUNNING)
            logger.info("Exporter connected (%s)", settings.bambulab_transport)
            self._wait(None)  # until reconfigure() or stop()

        self._stop_collector()
