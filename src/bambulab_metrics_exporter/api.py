from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from bambulab_metrics_exporter import __version__
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
_TEMPLATE = _TEMPLATE_PATH.read_text(encoding="utf-8")
_STATIC_PATH = Path(__file__).parent / "static"


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


def build_app(metrics: ExporterMetrics, collector: PollingCollector, settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="bambulab-metrics-exporter", version=__version__)

    # Mount static files for serving the logo and other assets
    if _STATIC_PATH.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_PATH)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def root_handler() -> HTMLResponse:
        ready = collector.ready
        ready_status = "Connected" if ready else "Warming Up"
        ready_class = "ready" if ready else "warming"

        healthy, _ = _check_health(metrics)
        health_status = "Healthy" if healthy else "Unhealthy"
        health_class = "healthy" if healthy else "unhealthy"

        # Resolve printer name from settings; fall back to empty string
        raw_printer_name = ""
        if settings is not None:
            raw_printer_name = settings.printer_name_label or settings.bambulab_printer_name or ""
        # Render as a separate badge element when set, or empty string when not set
        printer_badge = (
            f'<span class="printer-badge">🖨 {raw_printer_name}</span>'
            if raw_printer_name
            else ""
        )

        html = (
            _TEMPLATE
            .replace("{{VERSION}}", __version__)
            .replace("{{READY_STATUS}}", ready_status)
            .replace("{{READY_CLASS}}", ready_class)
            .replace("{{HEALTH_STATUS}}", health_status)
            .replace("{{HEALTH_CLASS}}", health_class)
            .replace("{{PRINTER_BADGE}}", printer_badge)
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
