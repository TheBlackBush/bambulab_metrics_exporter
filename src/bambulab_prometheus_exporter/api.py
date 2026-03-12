from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from bambulab_prometheus_exporter.collector import PollingCollector
from bambulab_prometheus_exporter.metrics import ExporterMetrics


def build_app(metrics: ExporterMetrics, collector: PollingCollector) -> FastAPI:
    app = FastAPI(title="bambulab-prometheus-exporter", version="0.1.0")

    @app.get("/metrics")
    def metrics_handler() -> Response:
        data = generate_latest(metrics.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health_handler() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready_handler() -> dict[str, str]:
        if collector.ready:
            return {"status": "ready"}
        raise HTTPException(status_code=503, detail="warming_up")

    return app
