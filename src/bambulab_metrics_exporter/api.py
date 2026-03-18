from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from bambulab_metrics_exporter import __version__
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.metrics import ExporterMetrics

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
_TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")


def _check_health(metrics: ExporterMetrics) -> tuple[bool, str]:
    """Return (is_healthy, status_string) based on exporter health checks.

    Centralises the health logic so both the /health endpoint and the
    landing page can reuse it without making an internal HTTP call.

    Currently this is a simple liveness check (the process is running →
    healthy). Future callers can extend this with last-scrape-age or other
    criteria without touching the two call-sites.
    """
    healthy = True
    status = "ok" if healthy else "error"
    return healthy, status


def build_app(metrics: ExporterMetrics, collector: PollingCollector) -> FastAPI:
    app = FastAPI(title="bambulab-metrics-exporter", version=__version__)

    @app.get("/", response_class=HTMLResponse)
    def root_handler() -> HTMLResponse:
        ready = collector.ready
        ready_status = "Connected" if ready else "Warming Up"
        ready_class = "ready" if ready else "warming"

        healthy, _ = _check_health(metrics)
        health_status = "Healthy" if healthy else "Unhealthy"
        health_class = "healthy" if healthy else "unhealthy"

        html = (
            _TEMPLATE
            .replace("{{VERSION}}", __version__)
            .replace("{{READY_STATUS}}", ready_status)
            .replace("{{READY_CLASS}}", ready_class)
            .replace("{{HEALTH_STATUS}}", health_status)
            .replace("{{HEALTH_CLASS}}", health_class)
        )
        return HTMLResponse(content=html)

    @app.get("/metrics")
    def metrics_handler() -> Response:
        data = generate_latest(metrics.registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health_handler() -> dict[str, str]:
        _, status = _check_health(metrics)
        return {"status": status}

    @app.get("/ready")
    def ready_handler() -> dict[str, str]:
        if collector.ready:
            return {"status": "ready"}
        raise HTTPException(status_code=503, detail="warming_up")

    return app
