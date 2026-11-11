from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import load_encrypted_credentials
from bambulab_metrics_exporter.fleet import PrinterFleet
from bambulab_metrics_exporter.logging_utils import configure_logging, log_banner
from bambulab_metrics_exporter.overrides import apply_overrides_to_env, page_login_active, set_env
from bambulab_metrics_exporter.printers import TRANSPORT_CLOUD, PrinterStore

logger = logging.getLogger(__name__)


def _safe_load_dotenv() -> None:
    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return
    try:
        load_dotenv(dotenv_path=dotenv_path, override=False)
    except PermissionError:
        logger.warning("Skipping .env load due to permission error", extra={"path": str(dotenv_path)})


def _has_cloud_printer(store: PrinterStore) -> bool:
    return any(config.transport == TRANSPORT_CLOUD for config in store.load() or [])


def _bootstrap_cloud_credentials(force: bool = False) -> None:
    """``force``: the saved printer list has cloud printers, or a page login is active, even
    if the env transport is local, so the account tokens are needed anyway."""
    transport = os.getenv("BAMBULAB_TRANSPORT", "local_mqtt")
    if transport != "cloud_mqtt" and not force:
        return

    # A page cloud login wins over env tokens (they are the container's own), recorded
    # so "Reset to env vars" can restore them.
    page_login = page_login_active()
    has_uid = bool(os.getenv("BAMBULAB_CLOUD_USER_ID"))
    has_token = bool(os.getenv("BAMBULAB_CLOUD_ACCESS_TOKEN"))
    if has_uid and has_token and not page_login:
        return

    config_dir = Path(os.getenv("BAMBULAB_CONFIG_DIR", "/config/bambulab-metrics-exporter"))
    credentials_name = os.getenv("BAMBULAB_CREDENTIALS_FILE", "credentials.enc.json")
    credentials_path = config_dir / credentials_name
    secret = os.getenv("BAMBULAB_SECRET_KEY", "")

    if not secret or not credentials_path.exists():
        return

    try:
        payload = load_encrypted_credentials(credentials_path, secret)
    except Exception:  # noqa: BLE001 - startup must continue; the runtime reports it
        logger.warning(
            "Encrypted credentials could not be read (wrong BAMBULAB_SECRET_KEY or damaged "
            "file); continuing without them"
        )
        return
    for key in (
        "BAMBULAB_CLOUD_USER_ID",
        "BAMBULAB_CLOUD_ACCESS_TOKEN",
        "BAMBULAB_CLOUD_REFRESH_TOKEN",
        "BAMBULAB_CLOUD_MQTT_HOST",
        "BAMBULAB_CLOUD_MQTT_PORT",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            if page_login:
                set_env(key, value)
            else:
                os.environ[key] = value


_WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]"}


def base_url(settings: Settings) -> str:
    """Address to reach the web UI. Inside a container the Docker host's address and any
    remapped host port are unknown, so a wildcard bind is shown as <docker-host>."""
    host = settings.listen_host
    if host in _WILDCARD_HOSTS:
        host = "<docker-host>"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{settings.listen_port}"


def log_web_endpoints(settings: Settings) -> None:
    url = base_url(settings)
    lines = [
        "",
        f"    Status page:         {url}/",
        f"    Printer connection:  {url}/auth",
        f"    Prometheus metrics:  {url}/metrics",
        f"    Health:              {url}/health",
        f"    Readiness:           {url}/ready",
    ]
    if settings.listen_host in _WILDCARD_HOSTS:
        lines += [
            "",
            f"({settings.listen_port} is the container port; use the host port if you mapped "
            "a different one.)",
        ]
    log_banner(logger, "BAMBU LAB METRICS EXPORTER WEB UI", lines)


# Settings that were documented once but never had an effect. They are ignored; a warning
# tells operators they can remove them.
_REMOVED_SETTINGS: tuple[str, ...] = ("RECONNECT_INTERVAL_SECONDS",)


def _warn_removed_settings() -> None:
    for key in _REMOVED_SETTINGS:
        if key in os.environ:
            logger.warning("%s has no effect and is ignored; you can remove it", key)


def run() -> None:
    _safe_load_dotenv()
    # Configure logging before anything else logs (overrides, bootstrap).
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    _warn_removed_settings()
    apply_overrides_to_env()
    store = PrinterStore()
    # A page login with no printer ticked yet still needs its token: the picker uses it.
    _bootstrap_cloud_credentials(force=_has_cloud_printer(store) or page_login_active())
    try:
        settings = Settings()
    except Exception as exc:  # noqa: BLE001 - serve /auth even with invalid env values
        logger.error("Invalid configuration (%s); starting with defaults so /auth is reachable", exc)
        settings = Settings.model_construct()

    # The web server starts immediately; connecting, waiting for credentials and retries
    # happen in the background so /health and /auth stay reachable.
    runtime = PrinterFleet(store)
    runtime.start()

    app = build_app(runtime=runtime)
    log_web_endpoints(settings)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        logger.info("Shutting down collector")
        runtime.stop()

    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    run()
