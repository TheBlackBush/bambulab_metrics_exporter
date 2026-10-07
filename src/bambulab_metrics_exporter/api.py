from __future__ import annotations

import html
import time
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


_REFRESH_STATES = {"starting", "connecting"}

_PRINTER_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<polyline points="6 9 6 2 18 2 18 9"/>'
    '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>'
    '<rect x="6" y="14" width="12" height="8"/></svg>'
)

_ALERT_ICON = (
    '<svg class="alert-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
    '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
)


def _alert(kind: str, title: str, detail: str) -> str:
    return (
        f'<a class="alert {kind}" href="/auth">{_ALERT_ICON}'
        f'<span class="alert-text"><strong>{title}</strong><span>{detail}</span></span>'
        '<span class="alert-cta">Open &rarr;</span></a>'
    )


# Shown on the landing page when the runtime needs the operator. Fixed text only.
_ALERTS: dict[str, str] = {
    "auth_required": _alert(
        "bad", "Bambu Cloud login required", "The cloud session expired. Sign in again to resume."
    ),
    "setup_required": _alert(
        "", "Printer not configured", "Choose local or cloud mode and enter the printer details."
    ),
    "error": _alert(
        "bad", "Cannot reach the printer", "Retrying automatically. Check the connection settings."
    ),
}

# Runtime state -> (label, pill class) for the landing page "Printer" card.
_PRINTER_STATES: dict[str, tuple[str, str]] = {
    "starting": ("Starting", "warming"),
    "connecting": ("Connecting", "warming"),
    "auth_required": ("Login required", "attention"),
    "setup_required": ("Setup required", "attention"),
    "error": ("Connection error", "attention"),
}


def _printer_state(state: str, ready: bool) -> tuple[str, str]:
    if state in _PRINTER_STATES:
        return _PRINTER_STATES[state]
    return ("Connected", "ready") if ready else ("Warming Up", "warming")


def _last_update(last: float | None, poll: float | None, now: float) -> tuple[str, str]:
    """Human age of the last successful poll and a freshness class."""
    if last is None:
        return "Never", "none"
    age = max(now - last, 0.0)
    if age < 60:
        text = f"{int(age)}s ago"
    elif age < 3600:
        text = f"{int(age // 60)}m ago"
    else:
        text = f"{int(age // 3600)}h ago"
    fresh = age <= 3 * (poll or 10.0)
    return text, "fresh" if fresh else "stale"


def _notice_html(result: ActionResult) -> str:
    kind, icon = ("ok", "&#10003;") if result.ok else ("bad", "!")
    note = (
        f'<span class="notice-note">{html.escape(result.note)}</span>' if result.note else ""
    )
    return (
        f'<div class="notice {kind}" role="status">'
        f'<span class="notice-icon" aria-hidden="true">{icon}</span>'
        f'<span class="notice-text">{html.escape(result.message)}{note}</span></div>'
    )


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
        status = runtime.status() if runtime is not None else None
        state = status["state"] if status else ""
        current = get_settings()

        healthy, _ = _check_health(get_metrics())
        health_status = "Healthy" if healthy else "Unhealthy"
        health_class = "healthy" if healthy else "unhealthy"

        ready_status, ready_class = _printer_state(state, is_ready())
        mode = ""
        if current is not None:
            mode = "Bambu Cloud" if current.bambulab_transport == "cloud_mqtt" else "Local (LAN)"

        last = get_metrics().last_success_timestamp()
        poll = current.polling_interval_seconds if current is not None else None
        last_text, last_class = _last_update(last, poll, time.time())

        raw_printer_name = ""
        if current is not None:
            raw_printer_name = current.printer_name_label or current.bambulab_printer_name or ""
        printer_badge = (
            f'<span class="printer-badge">{_PRINTER_ICON}{html.escape(raw_printer_name)}</span>'
            if raw_printer_name
            else ""
        )
        mode_badge = f'<span class="badge">{html.escape(mode)}</span>' if mode else ""

        # Refresh quickly while connecting, slowly otherwise (read-only page, safe to reload).
        refresh = 3 if state in _REFRESH_STATES or (state == "running" and not is_ready()) else 15

        page = (
            _TEMPLATE
            .replace("{{REFRESH}}", f'<meta http-equiv="refresh" content="{refresh}">')
            .replace("{{VERSION}}", __version__)
            .replace("{{PRINTER_BADGE}}", printer_badge)
            .replace("{{MODE_BADGE}}", mode_badge)
            .replace("{{ALERT}}", _ALERTS.get(state, ""))
            .replace("{{HEALTH_STATUS}}", health_status)
            .replace("{{HEALTH_CLASS}}", health_class)
            .replace("{{READY_STATUS}}", ready_status)
            .replace("{{READY_CLASS}}", ready_class)
            .replace("{{READY_DETAIL}}", html.escape(mode) or "Printer data")
            .replace("{{LAST_UPDATE}}", last_text)
            .replace("{{LAST_UPDATE_CLASS}}", last_class)
            .replace(
                "{{POLL_DETAIL}}", f"Polling every {poll:g}s" if poll is not None else "Polling"
            )
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

    def render(email: str = "", cloud_tab: bool | None = None) -> HTMLResponse:
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
        # While connecting, reload every few seconds so the status updates by itself, and
        # keep the last result visible until the state settles.
        refreshing = status["state"] in _REFRESH_STATES
        result = flash.get("last") if refreshing else flash.pop("last", None)
        flash_html = _notice_html(result) if result else ""
        cloud = current.bambulab_transport == "cloud_mqtt" if cloud_tab is None else cloud_tab
        page = (
            _AUTH_TEMPLATE
            .replace("{{VERSION}}", __version__)
            .replace("{{STATE_LABEL}}", html.escape(label))
            .replace("{{STATE_CLASS}}", css)
            .replace("{{CURRENT}}", html.escape(f"{where}, printer {printer}"))
            .replace("{{STATE_MESSAGE}}", message)
            .replace("{{FLASH}}", flash_html)
            .replace(
                "{{REFRESH}}",
                '<meta http-equiv="refresh" content="3;url=/auth">' if refreshing else "",
            )
            .replace("{{LOCAL_CHECKED}}", "" if cloud else "checked")
            .replace("{{CLOUD_CHECKED}}", "checked" if cloud else "")
            # Echo only the email the visitor just submitted; it is never stored.
            .replace("{{CLOUD_EMAIL}}", html.escape(email, quote=True))
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

    async def cloud_action(
        request: Request, action: Callable[[dict[str, str]], ActionResult], reconnect: bool
    ) -> Response:
        """Cloud steps answer with the page itself (not a redirect) while the visitor still
        has to act, so the email they typed stays filled in for the next step."""
        if not _same_origin(request):
            raise HTTPException(status_code=403, detail="cross_origin_form_post")
        form = await _form(request)
        try:
            result = await run_in_threadpool(action, form)
        except AuthInputError as exc:
            result = ActionResult(False, str(exc))
        if reconnect and result.ok:
            return done(result, reconnect)
        flash["last"] = result
        return render(email=form.get("email", "").strip(), cloud_tab=True)

    @app.post("/auth/cloud/send-code")
    async def auth_send_code(request: Request) -> Response:
        return await cloud_action(
            request, lambda f: code_sender.send(f.get("email", "")), reconnect=False
        )

    @app.post("/auth/cloud/login")
    async def auth_cloud_login(request: Request) -> Response:
        return await cloud_action(
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
