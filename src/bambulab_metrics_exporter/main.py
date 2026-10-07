from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import load_encrypted_credentials
from bambulab_metrics_exporter.logging_utils import configure_logging
from bambulab_metrics_exporter.overrides import apply_overrides_to_env
from bambulab_metrics_exporter.runtime import ExporterRuntime

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


def run() -> None:
    _safe_load_dotenv()
    apply_overrides_to_env()
    _bootstrap_cloud_credentials()
    settings = Settings()
    configure_logging(settings.log_level)

    # The web server starts immediately; connecting, waiting for credentials and retries
    # happen in the background so /health and /auth stay reachable.
    runtime = ExporterRuntime()
    runtime.start()

    app = build_app(runtime=runtime)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        logger.info("Shutting down collector")
        runtime.stop()

    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    run()
