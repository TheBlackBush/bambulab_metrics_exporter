from __future__ import annotations

import logging

import uvicorn

from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.logging_utils import configure_logging
from bambulab_metrics_exporter.metrics import ExporterMetrics

logger = logging.getLogger(__name__)


def run() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    settings.require_transport_config()

    metrics = ExporterMetrics(
        printer_name=settings.printer_name,
        site=settings.site,
        location=settings.location,
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
