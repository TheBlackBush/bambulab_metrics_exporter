from __future__ import annotations

import html
import ipaddress
import logging
import os
import re
import secrets
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.concurrency import run_in_threadpool

from bambulab_metrics_exporter import __version__
from bambulab_metrics_exporter.auth_actions import (
    ActionResult,
    AttemptLimiter,
    AuthInputError,
    CloudDevice,
    CloudDeviceList,
    CodeSender,
    add_local_printer,
    add_login_printer,
    configure_cloud,
    configure_local,
    mask_serial,
    persist_note,
    remove_printer,
    select_cloud_printers,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.overrides import (
    clear_overrides,
    restore_credentials_backup,
    restore_original_env,
)
from bambulab_metrics_exporter.overrides import lock as overrides_lock
from bambulab_metrics_exporter.printers import TRANSPORT_LOCAL, PrinterConfig
from bambulab_metrics_exporter.reauth import credentials_path


logger = logging.getLogger(__name__)

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

Reconnect = Callable[[], None]

_UNREADABLE_NOTE = (
    "The saved printer list could not be read, so it is not in use. Check BAMBULAB_SECRET_KEY."
)

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


def _send_code_button(seconds: int) -> tuple[str, str]:
    """Attributes and label for the Send code button. Only integers and fixed text."""
    if seconds <= 0:
        return "", "Send code"
    if seconds <= 60:
        label = f"{seconds}s"
    else:
        label = f"{seconds // 60}m {seconds % 60}s"
    return f' disabled data-wait="{seconds}"', f"Send code ({label})"


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


class _Backend(Protocol):
    """What the app needs from an ExporterRuntime or a PrinterFleet."""

    @property
    def settings(self) -> Settings: ...

    @property
    def metrics(self) -> ExporterMetrics: ...

    @property
    def ready(self) -> bool: ...

    def status(self) -> dict[str, str]: ...

    def reconfigure(self) -> None: ...


class _Fleet(_Backend, Protocol):
    @property
    def saved(self) -> bool: ...

    @property
    def list_unreadable(self) -> bool: ...

    def configs(self) -> list[PrinterConfig]: ...

    def printers_status(self) -> list[dict[str, str]]: ...

    def reconfigure_cloud(self) -> None: ...

    def update(self, configs: list[PrinterConfig]) -> bool: ...

    def reset_to_env(self) -> None: ...


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


_MAX_FORM_BYTES = 8192
_FLASH_COOKIE = "bme_auth"
_FLASH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_FLASH_LIMIT = 64


@dataclass(slots=True)
class _Flash:
    """What one visitor sees once after a page action.

    The email is held in memory only (never on disk), and the store of these is capped by
    ``_FLASH_LIMIT``. A flash with ``show_send_wait`` is shown for a single page view; a
    plain result flash may be shown again by the auto-reloads while connecting.
    """

    result: ActionResult
    email: str = ""
    show_send_wait: bool = False


# Names that only resolve on a local network. A DNS-rebinding attacker needs a public
# domain they control, so these (plus IP addresses) are safe to accept without config.
_LOCAL_HOST_SUFFIXES = (
    ".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa", ".localhost",
)

# Ask browsers not to show the pages inside frames on other sites (clickjacking).
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def _host_allowed(host_header: str, extra: set[str]) -> bool:
    """Accept the Host header for /auth only when it names this machine on the local
    network: an IP address, localhost, a single-label or local-domain name, or a name the
    operator listed in AUTH_ALLOWED_HOSTS. Blocks DNS rebinding from public domains."""
    host = host_header.strip().lower()
    if host.startswith("["):
        name = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:
        name = host.split(":", 1)[0]
    else:
        name = host
    name = name.rstrip(".")
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    if name in extra or name == "localhost" or "." not in name:
        return True
    return name.endswith(_LOCAL_HOST_SUFFIXES)


def _short_error(exc: Exception) -> str:
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc)[:200]


def _same_origin(request: Request) -> bool:
    """Reject cross-site form posts (CSRF) while allowing same-page posts and non-browser
    clients that send no Origin header."""
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin is None
    return urlsplit(origin).netloc == request.headers.get("host", "")


async def _form(request: Request) -> dict[str, str]:
    """Parse a small urlencoded form; refuse oversized bodies instead of buffering them."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="form_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_FORM_BYTES:
            raise HTTPException(status_code=413, detail="form_too_large")
        chunks.append(chunk)
    body = b"".join(chunks).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def _printers_html(printers: list[dict[str, str]]) -> str:
    """Per-printer rows for the landing page; names can come from the cloud account."""
    if len(printers) < 2:
        return ""
    rows = "".join(
        f'<div class="printer-row"><span>{html.escape(p["name"])}</span>'
        f'<span class="printer-state">'
        f'{html.escape(_STATE_LABELS.get(p["state"], (p["state"], ""))[0])}</span></div>'
        for p in printers
    )
    return f'<div class="printer-list">{rows}</div>'


def _page_text(text: str) -> str:
    """Escape untrusted text. The page is filled by a chain of replaces, so braces are
    escaped too: a printer name must not be able to expand a later placeholder."""
    return html.escape(text, quote=True).replace("{", "&#123;")


def _printer_table(printers: list[dict[str, str]]) -> str:
    """Monitored printers; only masked serials reach this unauthenticated page."""
    if not printers:
        return ""
    rows = []
    for printer in printers:
        label, css = _STATE_LABELS.get(printer["state"], (printer["state"], "wait"))
        where = "LAN" if printer["transport"] == TRANSPORT_LOCAL else "Cloud"
        message = (
            f'<span class="hint printer-message">{_page_text(printer["message"])}</span>'
            if printer["message"]
            else ""
        )
        rows.append(
            '<form method="post" action="/auth/printers/remove" class="printer-row">'
            f'<input type="hidden" name="printer_id" value="{_page_text(printer["id"])}">'
            f'<span class="step">{_page_text(printer["name"])} '
            f'<span class="hint">{_page_text(printer["serial"])}, {where}</span>{message}</span>'
            f'<span class="pill {css}">{_page_text(label)}</span>'
            '<button type="submit" class="danger small">Remove</button></form>'
        )
    return '<div class="card"><span class="label">Printers</span>' + "".join(rows) + "</div>"


def _cloud_picker(devices: list[CloudDevice], selected: set[str]) -> str:
    """Checkbox names carry the opaque id; the form parser keeps one value per key."""
    if not devices:
        return ""
    rows = []
    for device in devices:
        checked = " checked" if device.serial in selected else ""
        state = "Online" if device.online else "Offline"
        rows.append(
            '<label class="device-row">'
            f'<input type="checkbox" name="printer_{device.printer_id}"{checked}>'
            f'<span>{_page_text(device.name or "Printer")} '
            f'<span class="hint">{_page_text(device.model)}, '
            f'{_page_text(mask_serial(device.serial))}, {state}</span></span></label>'
        )
    return (
        '<form method="post" action="/auth/printers/select" class="device-list">'
        '<span class="label">Printers on this account</span>'
        + "".join(rows)
        + '<button type="submit">Save selection</button></form>'
    )


def build_app(
    metrics: ExporterMetrics | None = None,
    collector: _ReadyFlag | None = None,
    settings: Settings | None = None,
    runtime: _Backend | None = None,
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

    def printers() -> list[dict[str, str]]:
        lister = getattr(runtime, "printers_status", None)
        return lister() if lister is not None else []

    app = FastAPI(title="bambulab-metrics-exporter", version=__version__)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

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
        listed = printers()
        if len(listed) > 1:
            raw_printer_name = f"{len(listed)} printers"
            mode = ""
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
            .replace("{{PRINTERS}}", _printers_html(listed))
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
        registry = getattr(runtime, "scrape_registry", None) or get_metrics().registry
        data = generate_latest(registry)
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


def _add_auth_routes(app: FastAPI, runtime: _Backend) -> None:
    fleet = cast("_Fleet", runtime) if hasattr(runtime, "update") else None
    devices = CloudDeviceList()
    code_sender = CodeSender()
    login_limiter = AttemptLimiter(max_attempts=5, window_seconds=60.0)
    # Last action result per visitor (cookie), shown once. Kept server-side so the page
    # never renders text taken from the URL, and one visitor never sees another's result.
    flashes: OrderedDict[str, _Flash] = OrderedDict()

    def allowed_hosts() -> set[str]:
        raw = getattr(runtime.settings, "auth_allowed_hosts", "") or ""
        return {h.strip().lower() for h in str(raw).split(",") if h.strip()}

    def guard(request: Request) -> None:
        if not _host_allowed(request.headers.get("host", ""), allowed_hosts()):
            raise HTTPException(
                status_code=403,
                detail="host_not_allowed: add this host name to AUTH_ALLOWED_HOSTS",
            )

    def visitor(request: Request) -> str:
        token = request.cookies.get(_FLASH_COOKIE, "")
        return token if _FLASH_TOKEN_RE.match(token) else ""

    def set_flash(token: str, flash: _Flash) -> None:
        flashes[token] = flash
        flashes.move_to_end(token)
        while len(flashes) > _FLASH_LIMIT:
            flashes.popitem(last=False)

    def render(request: Request) -> HTMLResponse:
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
        if fleet and fleet.list_unreadable:
            message += f'<div class="detail">{_UNREADABLE_NOTE}</div>'
        # While connecting, reload every few seconds so the status updates by itself, and
        # keep the last result visible until the state settles. Every post redirects here
        # (so a refresh cannot submit a form again); the flash carries the email the visitor
        # typed and whether the Send code wait shows, for this one view.
        refreshing = status["state"] in _REFRESH_STATES
        token = visitor(request)
        flash = None
        if token:
            flash = flashes.get(token)
            # The page after a Send code or login press is a single view in any state: it
            # holds the typed email and the timer, so it is consumed and does not reload.
            if flash and (flash.show_send_wait or not refreshing):
                flashes.pop(token, None)
            if flash and flash.show_send_wait:
                refreshing = False
        result = flash.result if flash else None
        email = flash.email if flash else ""
        show_send_wait = flash.show_send_wait if flash else False
        flash_html = _notice_html(result) if result else ""
        cloud = show_send_wait or current.bambulab_transport == "cloud_mqtt"
        # The wait shows only right after a Send code or login post, never on a plain
        # load, so the button starts active and the timer follows a press.
        send_attrs, send_label = _send_code_button(
            code_sender.wait_seconds() if show_send_wait else 0
        )
        picker = ""
        if fleet and os.getenv("BAMBULAB_CLOUD_ACCESS_TOKEN"):
            selected = {
                config.serial for config in fleet.configs() if config.transport != TRANSPORT_LOCAL
            }
            picker = _cloud_picker(devices.peek(), selected)
        page = (
            _AUTH_TEMPLATE
            .replace("{{VERSION}}", __version__)
            .replace("{{STATE_LABEL}}", html.escape(label))
            .replace("{{STATE_CLASS}}", css)
            .replace("{{CURRENT}}", html.escape(f"{where}, printer {printer}"))
            .replace("{{STATE_MESSAGE}}", message)
            .replace("{{FLASH}}", flash_html)
            .replace("{{DATA_REFRESH}}", ' data-refresh="1"' if refreshing else "")
            .replace(
                "{{REFRESH}}",
                '<meta http-equiv="refresh" content="3;url=/auth">' if refreshing else "",
            )
            .replace("{{LOCAL_CHECKED}}", "" if cloud else "checked")
            .replace("{{CLOUD_CHECKED}}", "checked" if cloud else "")
            .replace("{{SEND_ATTRS}}", send_attrs)
            .replace("{{SEND_LABEL}}", send_label)
            .replace("{{PRINTERS}}", _printer_table(fleet.printers_status()) if fleet else "")
            .replace("{{CLOUD_PICKER}}", picker)
            .replace("{{LOCAL_ACTION}}", "/auth/printers/add-local" if fleet else "/auth/local")
            .replace("{{LOCAL_BUTTON}}", "Add printer" if fleet else "Connect locally")
            # Echo only the email from this visitor's last post, held in memory for one view.
            .replace("{{CLOUD_EMAIL}}", html.escape(email, quote=True))
        )
        return HTMLResponse(content=page, headers={"Cache-Control": "no-store"})

    def with_visitor(response: Response, token: str) -> Response:
        response.set_cookie(
            _FLASH_COOKIE, token, httponly=True, samesite="strict", path="/auth", max_age=3600
        )
        return response

    async def run_action(
        request: Request, action: Callable[[dict[str, str]], ActionResult]
    ) -> tuple[dict[str, str], ActionResult]:
        guard(request)
        if not _same_origin(request):
            raise HTTPException(status_code=403, detail="cross_origin_form_post")
        form = await _form(request)

        def locked() -> ActionResult:
            # One page change at a time: env writes and file saves must not interleave.
            with overrides_lock:
                return action(form)

        try:
            result = await run_in_threadpool(locked)
        except AuthInputError as exc:
            result = ActionResult(False, str(exc))
        except (OSError, RuntimeError) as exc:
            logger.warning("Saving /auth page settings failed: %s", exc)
            result = ActionResult(False, f"Could not save the settings: {_short_error(exc)}")
        return form, result

    def wants_json(request: Request) -> bool:
        return "application/json" in request.headers.get("accept", "")

    def apply_change(result: ActionResult, reconnect: Reconnect | None) -> None:
        if reconnect and result.ok and not result.applied:
            reconnect()

    def json_reply(
        result: ActionResult, reconnect: Reconnect | None, with_wait: bool
    ) -> Response:
        """Answer a background request from the page script: no redirect and no flash, and
        nothing the visitor typed is echoed (only the result message and the wait)."""
        apply_change(result, reconnect)
        body: dict[str, object] = {
            "ok": result.ok,
            "message": result.message,
            "note": result.note,
        }
        if with_wait:
            body["wait_seconds"] = code_sender.wait_seconds()
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    async def handle(
        request: Request,
        action: Callable[[dict[str, str]], ActionResult],
        reconnect: Reconnect | None,
    ) -> Response:
        _form_data, result = await run_action(request, action)
        if wants_json(request):
            return json_reply(result, reconnect, with_wait=False)
        token = visitor(request) or secrets.token_urlsafe(16)
        set_flash(token, _Flash(result))
        apply_change(result, reconnect)
        return with_visitor(RedirectResponse("/auth", status_code=303), token)

    async def cloud_action(
        request: Request,
        action: Callable[[dict[str, str]], ActionResult],
        reconnect: Reconnect | None,
        with_wait: bool = False,
    ) -> Response:
        """Cloud steps redirect like every other post (so a refresh cannot press Send code
        again); the flash keeps the typed email and the wait for the next page view."""
        form, result = await run_action(request, action)
        if wants_json(request):
            return json_reply(result, reconnect, with_wait)
        token = visitor(request) or secrets.token_urlsafe(16)
        if reconnect and result.ok:
            set_flash(token, _Flash(result))
            apply_change(result, reconnect)
        else:
            set_flash(
                token,
                _Flash(result, email=form.get("email", "").strip(), show_send_wait=True),
            )
        return with_visitor(RedirectResponse("/auth", status_code=303), token)

    @app.get("/auth", response_class=HTMLResponse)
    def auth_page(request: Request) -> HTMLResponse:
        guard(request)
        if fleet:
            devices.refresh()
        return render(request)

    @app.get("/auth/status")
    def auth_status(request: Request) -> dict[str, object]:
        guard(request)
        status: dict[str, object] = dict(runtime.status())
        lister = getattr(runtime, "printers_status", None)
        if lister is not None:
            status["printers"] = lister()
        return status

    def saved(persisted: bool, message: str) -> ActionResult:
        return ActionResult(True, message, persist_note(persisted), applied=True)

    @app.post("/auth/local")
    async def auth_local(request: Request) -> Response:
        def connect(f: dict[str, str]) -> ActionResult:
            host, serial = f.get("host", ""), f.get("serial", "")
            code, port = f.get("access_code", ""), f.get("port", "")
            if fleet and fleet.saved:
                # A saved list decides what runs, so the env printer would change nothing.
                configs = add_local_printer(fleet.configs(), host, serial, code, port)
                return saved(fleet.update(configs), "LAN printer saved.")
            return configure_local(host, serial, code, port)

        return await handle(request, connect, reconnect=runtime.reconfigure)

    @app.post("/auth/cloud/send-code")
    async def auth_send_code(request: Request) -> Response:
        return await cloud_action(
            request, lambda f: code_sender.send(f.get("email", "")), reconnect=None, with_wait=True
        )

    @app.post("/auth/cloud/login")
    async def auth_cloud_login(request: Request) -> Response:
        def login(f: dict[str, str]) -> ActionResult:
            login_limiter.check()
            result = configure_cloud(f.get("email", ""), f.get("code", ""), f.get("serial", ""))
            if result.ok:
                code_sender.reset()
                devices.clear()
                if fleet and fleet.saved and result.device:
                    return add_login_printer(fleet.configs(), result.device, fleet.update, result)
            return result

        # LAN printers do not use the account, so a login must not restart them.
        reconnect = fleet.reconfigure_cloud if fleet else runtime.reconfigure
        return await cloud_action(request, login, reconnect=reconnect)

    @app.post("/auth/reset")
    async def auth_reset(request: Request) -> Response:
        def reset(_form: dict[str, str]) -> ActionResult:
            had_list = fleet.saved if fleet else False
            removed = clear_overrides()
            restored = restore_credentials_backup(credentials_path(runtime.settings))
            restore_original_env()
            if fleet:
                devices.clear()  # It belongs to the page login, which is gone now.
                fleet.reset_to_env()
            if removed or restored or had_list:
                return ActionResult(True, "Page settings removed; using the container's env vars.")
            return ActionResult(True, "No saved page settings; already using env vars.")

        return await handle(request, reset, reconnect=runtime.reconfigure)

    if fleet is None:
        return

    @app.post("/auth/printers/select")
    async def auth_printers_select(request: Request) -> Response:
        def select(f: dict[str, str]) -> ActionResult:
            chosen = {k.removeprefix("printer_") for k in f if k.startswith("printer_")}
            devices.refresh()  # A printer gone from the account must not come back.
            configs = select_cloud_printers(fleet.configs(), devices.peek(), chosen)
            return saved(fleet.update(configs), "Printer selection saved.")

        return await handle(request, select, reconnect=None)

    @app.post("/auth/printers/add-local")
    async def auth_printers_add_local(request: Request) -> Response:
        def add(f: dict[str, str]) -> ActionResult:
            configs = add_local_printer(
                fleet.configs(), f.get("host", ""), f.get("serial", ""),
                f.get("access_code", ""), f.get("port", ""), f.get("name", ""),
            )
            return saved(fleet.update(configs), "LAN printer saved.")

        return await handle(request, add, reconnect=None)

    @app.post("/auth/printers/remove")
    async def auth_printers_remove(request: Request) -> Response:
        def remove(f: dict[str, str]) -> ActionResult:
            configs = remove_printer(fleet.configs(), f.get("printer_id", ""))
            return saved(fleet.update(configs), "Printer removed.")

        return await handle(request, remove, reconnect=None)
