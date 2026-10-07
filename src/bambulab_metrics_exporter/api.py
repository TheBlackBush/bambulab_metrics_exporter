from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.concurrency import run_in_threadpool

from bambulab_metrics_exporter import __version__
from bambulab_metrics_exporter.auth_actions import (
    ActionResult,
    AuthInputError,
    CodeSender,
    configure_cloud,
    configure_local,
    mask_serial,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.overrides import clear_overrides, restore_original_env

if TYPE_CHECKING:
    from bambulab_metrics_exporter.runtime import ExporterRuntime

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE = (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
_AUTH_TEMPLATE = (_TEMPLATE_DIR / "auth.html").read_text(encoding="utf-8")
_STATIC_PATH = Path(__file__).parent / "static"

_STATE_LABELS: dict[str, tuple[str, str]] = {
    "starting": ("Starting", "wait"),
    "connecting": ("Connecting", "wait"),
    "running": ("Connected", "ok"),
    "setup_required": ("Setup required", "bad"),
    "auth_required": ("Login required", "bad"),
    "error": ("Connection error", "bad"),
}


class _ReadyFlag(Protocol):
    @property
    def ready(self) -> bool: ...


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


def _same_origin(request: Request) -> bool:
    """Reject cross-site form posts (CSRF) while allowing same-page posts and non-browser
    clients that send no Origin header."""
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin is None
    return urlsplit(origin).netloc == request.headers.get("host", "")


async def _form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def build_app(
    metrics: ExporterMetrics | None = None,
    collector: _ReadyFlag | None = None,
    settings: Settings | None = None,
    runtime: ExporterRuntime | None = None,
) -> FastAPI:
    """Build the HTTP app. Pass ``runtime`` in production; the /auth page needs it to
    reconnect. ``metrics``/``collector``/``settings`` remain for static wiring in tests."""
    if runtime is None and (metrics is None or collector is None):
        raise ValueError("build_app needs either runtime or metrics and collector")

    def get_metrics() -> ExporterMetrics:
        if runtime is not None:
            return runtime.metrics
        assert metrics is not None
        return metrics

    def is_ready() -> bool:
        if runtime is not None:
            return runtime.ready
        assert collector is not None
        return collector.ready

    def get_settings() -> Settings | None:
        return runtime.settings if runtime is not None else settings

    app = FastAPI(title="bambulab-metrics-exporter", version=__version__)

    # Mount static files for serving the logo and other assets
    if _STATIC_PATH.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_PATH)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def root_handler() -> HTMLResponse:
        ready = is_ready()
        ready_status = "Connected" if ready else "Warming Up"
        ready_class = "ready" if ready else "warming"

        healthy, _ = _check_health(get_metrics())
        health_status = "Healthy" if healthy else "Unhealthy"
        health_class = "healthy" if healthy else "unhealthy"

        # Resolve printer name from settings; fall back to empty string
        current = get_settings()
        raw_printer_name = ""
        if current is not None:
            raw_printer_name = current.printer_name_label or current.bambulab_printer_name or ""
        # Render as a separate badge element when set, or empty string when not set
        printer_badge = (
            f'<span class="printer-badge">🖨 {html.escape(raw_printer_name)}</span>'
            if raw_printer_name
            else ""
        )

        page = (
            _TEMPLATE
            .replace("{{VERSION}}", __version__)
            .replace("{{READY_STATUS}}", ready_status)
            .replace("{{READY_CLASS}}", ready_class)
            .replace("{{HEALTH_STATUS}}", health_status)
            .replace("{{HEALTH_CLASS}}", health_class)
            .replace("{{PRINTER_BADGE}}", printer_badge)
        )
        return HTMLResponse(content=page)

    @app.get("/metrics")
    def metrics_handler() -> Response:
        data = generate_latest(get_metrics().registry)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health_handler() -> dict[str, str]:
        _, status = _check_health(get_metrics())
        return {"status": status}

    @app.get("/ready")
    def ready_handler() -> dict[str, str]:
        if is_ready():
            return {"status": "ready"}
        raise HTTPException(status_code=503, detail="warming_up")

    if runtime is not None:
        _add_auth_routes(app, runtime)

    return app


def _add_auth_routes(app: FastAPI, runtime: ExporterRuntime) -> None:
    code_sender = CodeSender()
    # Last action result, shown once. Kept server-side so the page never renders text
    # taken from the URL.
    flash: dict[str, ActionResult] = {}

    def render() -> HTMLResponse:
        status = runtime.status()
        label, css = _STATE_LABELS.get(status["state"], (status["state"], "wait"))
        current = runtime.settings
        if current.bambulab_transport == "cloud_mqtt":
            where = "Bambu Cloud"
        else:
            where = f"Local, {current.bambulab_host or 'no host set'}"
        printer = mask_serial(current.bambulab_serial) or "no printer set"
        message = (
            f'<div class="detail">{html.escape(status["message"])}</div>'
            if status["message"]
            else ""
        )
        result = flash.pop("last", None)
        flash_html = (
            f'<div class="flash {"ok" if result.ok else "bad"}">{html.escape(result.message)}</div>'
            if result
            else ""
        )
        cloud = current.bambulab_transport == "cloud_mqtt"
        page = (
            _AUTH_TEMPLATE
            .replace("{{VERSION}}", __version__)
            .replace("{{STATE_LABEL}}", html.escape(label))
            .replace("{{STATE_CLASS}}", css)
            .replace("{{CURRENT}}", html.escape(f"{where}, printer {printer}"))
            .replace("{{STATE_MESSAGE}}", message)
            .replace("{{FLASH}}", flash_html)
            .replace("{{LOCAL_CHECKED}}", "" if cloud else "checked")
            .replace("{{CLOUD_CHECKED}}", "checked" if cloud else "")
        )
        return HTMLResponse(content=page, headers={"Cache-Control": "no-store"})

    def done(result: ActionResult, reconnect: bool) -> RedirectResponse:
        flash["last"] = result
        if reconnect and result.ok:
            runtime.reconfigure()
        return RedirectResponse("/auth", status_code=303)

    async def handle(
        request: Request, action: Callable[[dict[str, str]], ActionResult], reconnect: bool
    ) -> RedirectResponse:
        if not _same_origin(request):
            raise HTTPException(status_code=403, detail="cross_origin_form_post")
        form = await _form(request)
        try:
            result = await run_in_threadpool(action, form)
        except AuthInputError as exc:
            result = ActionResult(False, str(exc))
        return done(result, reconnect)

    @app.get("/auth", response_class=HTMLResponse)
    def auth_page() -> HTMLResponse:
        return render()

    @app.get("/auth/status")
    def auth_status() -> dict[str, str]:
        return runtime.status()

    @app.post("/auth/local")
    async def auth_local(request: Request) -> RedirectResponse:
        return await handle(
            request,
            lambda f: configure_local(
                f.get("host", ""), f.get("serial", ""), f.get("access_code", ""), f.get("port", "")
            ),
            reconnect=True,
        )

    @app.post("/auth/cloud/send-code")
    async def auth_send_code(request: Request) -> RedirectResponse:
        return await handle(request, lambda f: code_sender.send(f.get("email", "")), reconnect=False)

    @app.post("/auth/cloud/login")
    async def auth_cloud_login(request: Request) -> RedirectResponse:
        return await handle(
            request,
            lambda f: configure_cloud(f.get("email", ""), f.get("code", ""), f.get("serial", "")),
            reconnect=True,
        )

    @app.post("/auth/reset")
    async def auth_reset(request: Request) -> RedirectResponse:
        def reset(_form: dict[str, str]) -> ActionResult:
            removed = clear_overrides()
            restore_original_env()
            if removed:
                return ActionResult(True, "Saved page settings removed; using env vars.")
            return ActionResult(True, "No saved page settings; already using env vars.")

        return await handle(request, reset, reconnect=True)
