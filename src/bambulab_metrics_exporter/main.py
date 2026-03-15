from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.cloud_auth import get_bind_devices
from bambulab_metrics_exporter.credentials_store import load_encrypted_credentials
from bambulab_metrics_exporter.env_sync import sync_env_file
from bambulab_metrics_exporter.logging_utils import configure_logging
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.startup import startup_validate

logger = logging.getLogger(__name__)


def _safe_load_dotenv() -> None:
    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return
    try:
        load_dotenv(dotenv_path=dotenv_path, override=False)
    except PermissionError:
        logger.warning("Skipping .env load due to permission error", extra={"path": str(dotenv_path)})


def _bootstrap_cloud_credentials() -> None:
    transport = os.getenv("BAMBULAB_TRANSPORT", "local_mqtt")
    if transport != "cloud_mqtt":
        return

    has_uid = bool(os.getenv("BAMBULAB_CLOUD_USER_ID"))
    has_token = bool(os.getenv("BAMBULAB_CLOUD_ACCESS_TOKEN"))
    if has_uid and has_token:
        return

    config_dir = Path(os.getenv("BAMBULAB_CONFIG_DIR", "/config/bambulab-metrics-exporter"))
    credentials_name = os.getenv("BAMBULAB_CREDENTIALS_FILE", "credentials.enc.json")
    credentials_path = config_dir / credentials_name
    secret = os.getenv("BAMBULAB_SECRET_KEY", "")

    if not secret or not credentials_path.exists():
        return

    payload = load_encrypted_credentials(credentials_path, secret)
    for key in (
        "BAMBULAB_CLOUD_USER_ID",
        "BAMBULAB_CLOUD_ACCESS_TOKEN",
        "BAMBULAB_CLOUD_REFRESH_TOKEN",
        "BAMBULAB_CLOUD_MQTT_HOST",
        "BAMBULAB_CLOUD_MQTT_PORT",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            os.environ[key] = value


def _persist_runtime_env(env_file_path: Path) -> None:
    try:
        sync_env_file(env_file_path)
    except PermissionError:
        logger.warning("Skipping .env sync due to permission error", extra={"path": str(env_file_path)})


def _discover_metadata_from_cloud(settings: Settings) -> tuple[str, str]:
    """Fetch name and model from cloud API if available"""
    if settings.bambulab_transport != "cloud_mqtt":
        return "", ""
    
    token = settings.bambulab_cloud_access_token
    if not token:
        return "", ""
        
    try:
        devices = get_bind_devices(token, timeout_seconds=settings.request_timeout_seconds)
        device = next((d for d in devices if d.get("dev_id") == settings.bambulab_serial), None)
        if device:
            name = str(device.get("name", ""))
            model = str(device.get("model") or device.get("dev_product_name") or "")
            return name, model
    except Exception:
        logger.warning("Metadata discovery from cloud failed (non-fatal)")
    
    return "", ""


def run() -> None:
    _safe_load_dotenv()
    _bootstrap_cloud_credentials()
    settings = Settings()
    configure_logging(settings.log_level)
    settings.require_transport_config()

    # Initial metadata discovery from Cloud API (instead of MQTT probe)
    discovered_name, discovered_model = _discover_metadata_from_cloud(settings)

    if discovered_name:
        if os.getenv("BAMBULAB_PRINTER_NAME") != discovered_name:
            os.environ["BAMBULAB_PRINTER_NAME"] = discovered_name
            logger.info("Discovered printer name from Cloud: %s", discovered_name)
        if not settings.printer_name_label:
             settings.bambulab_printer_name = discovered_name

    if discovered_model:
        if os.getenv("BAMBULAB_PRINTER_MODEL") != discovered_model:
            os.environ["BAMBULAB_PRINTER_MODEL"] = discovered_model
            logger.info("Discovered printer model from Cloud: %s", discovered_model)
            settings.bambulab_printer_model = discovered_model

    startup_validate(settings)

    _persist_runtime_env(Path(".env"))

    # Final label resolution
    final_printer_name = settings.printer_name_label or settings.bambulab_printer_name or "bambulab"

    metrics = ExporterMetrics(
        printer_name=final_printer_name,
        serial=settings.bambulab_serial,
    )
    client = build_client(settings)
    collector = PollingCollector(client=client, metrics=metrics, settings=settings)
    collector.start()

    app = build_app(metrics=metrics, collector=collector)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        logger.info("Shutting down collector")
        collector.stop()

    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    run()
