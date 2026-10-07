"""Actions behind the /auth page: configure local or cloud mode.

Shared by the web page; ``bambulab-reauth`` covers the same cloud login from a shell.
Every action validates its input, applies it to the process environment, persists it
encrypted when BAMBULAB_SECRET_KEY is set, and never returns secrets to the caller.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthError,
    get_bind_devices,
    login_with_code,
    send_code,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.overrides import (
    backup_credentials,
    remember_original,
    save_overrides,
    set_env,
)
from bambulab_metrics_exporter.reauth import (
    CREDENTIAL_KEYS,
    apply_credentials,
    credentials_path,
    save_login_result,
)

_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,253}$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9]{8,32}$")
_ACCESS_CODE_RE = re.compile(r"^\S{4,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,253}$")
_CODE_RE = re.compile(r"^[0-9A-Za-z]{4,12}$")

SEND_CODE_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class ActionResult:
    ok: bool
    message: str
    note: str = ""


class AuthInputError(ValueError):
    """Invalid user input; the message is safe to show on the page."""


def mask_serial(serial: str) -> str:
    """Show only the model prefix of a serial on the unauthenticated page."""
    return f"{serial[:3]}{'*' * max(len(serial) - 3, 0)}" if serial else ""


def _persist(values: dict[str, str]) -> bool:
    for key, value in values.items():
        set_env(key, value)
    return save_overrides(values)


def _persist_note(persisted: bool) -> str:
    if persisted:
        return "Kept after restarts; overrides the container's env vars."
    return "Applies until the next restart. Set BAMBULAB_SECRET_KEY to keep it."



def configure_local(host: str, serial: str, access_code: str, port: str = "") -> ActionResult:
    host, serial, access_code, port = host.strip(), serial.strip().upper(), access_code.strip(), port.strip()
    if not _HOST_RE.match(host):
        raise AuthInputError("Enter the printer IP address or host name.")
    if not _SERIAL_RE.match(serial):
        raise AuthInputError("The serial number must be 8 to 32 letters or digits.")
    if not _ACCESS_CODE_RE.match(access_code):
        raise AuthInputError("Enter the LAN access code shown on the printer.")
    values = {
        "BAMBULAB_TRANSPORT": "local_mqtt",
        "BAMBULAB_HOST": host,
        "BAMBULAB_SERIAL": serial,
        "BAMBULAB_ACCESS_CODE": access_code,
    }
    if port:
        if not port.isdigit() or not 0 < int(port) < 65536:
            raise AuthInputError("The port must be a number between 1 and 65535.")
        values["BAMBULAB_PORT"] = port
    persisted = _persist(values)
    return ActionResult(
        True, f"Local connection saved for printer {mask_serial(serial)}.", _persist_note(persisted)
    )


class CodeSender:
    """Sends verification emails at most once per interval (the page is unauthenticated)."""

    def __init__(self, interval_seconds: float = SEND_CODE_INTERVAL_SECONDS) -> None:
        self._interval = interval_seconds
        self._last = float("-inf")
        self._lock = threading.Lock()

    def send(self, email: str) -> ActionResult:
        email = email.strip()
        if not _EMAIL_RE.match(email):
            raise AuthInputError("Enter the email address of your Bambu account.")
        with self._lock:
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                raise AuthInputError(f"A code was just sent. Try again in {int(wait) + 1} seconds.")
            self._last = time.monotonic()
        try:
            send_code(email)
        except CloudAuthError as exc:
            return ActionResult(False, f"Could not send the code: {exc}")
        return ActionResult(True, "Verification code sent. Check your email.")


class AttemptLimiter:
    """Caps login attempts relayed to Bambu Cloud (the page is unauthenticated)."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._attempts: list[float] = []
        self._lock = threading.Lock()

    def check(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._attempts = [t for t in self._attempts if now - t < self._window]
            if len(self._attempts) >= self._max:
                wait = int(self._window - (now - self._attempts[0])) + 1
                raise AuthInputError(f"Too many login attempts. Try again in {wait} seconds.")
            self._attempts.append(now)


def configure_cloud(email: str, code: str, serial: str = "") -> ActionResult:
    email, code, serial = email.strip(), code.strip(), serial.strip().upper()
    if not _EMAIL_RE.match(email):
        raise AuthInputError("Enter the email address of your Bambu account.")
    if not _CODE_RE.match(code):
        raise AuthInputError("Enter the verification code from the email.")
    if serial and not _SERIAL_RE.match(serial):
        raise AuthInputError("The serial number must be 8 to 32 letters or digits.")
    try:
        result = login_with_code(email=email, code=code)
    except CloudAuthError as exc:
        return ActionResult(False, f"Login failed (codes are single-use and expire): {exc}")

    if not serial:
        try:
            devices = get_bind_devices(result.access_token)
        except CloudAuthError as exc:
            return ActionResult(False, f"Logged in, but the printer list failed: {exc}")
        serials = [str(d["dev_id"]) for d in devices if d.get("dev_id")]
        if len(serials) != 1:
            return ActionResult(
                False,
                f"Your account has {len(serials)} printers; enter the serial of the one to "
                "monitor and log in again with a new code.",
            )
        serial = serials[0]

    # Record what the container had, so "Reset to env vars" can undo this login.
    for key in CREDENTIAL_KEYS:
        remember_original(key)
    persisted = _persist({"BAMBULAB_TRANSPORT": "cloud_mqtt", "BAMBULAB_SERIAL": serial})
    settings = Settings()
    if persisted:
        backup_credentials(credentials_path(settings))
        save_login_result(settings, result)
    else:
        apply_credentials(
            settings,
            {
                "BAMBULAB_CLOUD_USER_ID": result.user_id,
                "BAMBULAB_CLOUD_ACCESS_TOKEN": result.access_token,
                "BAMBULAB_CLOUD_REFRESH_TOKEN": result.refresh_token,
            },
        )
    return ActionResult(
        True,
        f"Signed in to Bambu Cloud for printer {mask_serial(serial)}.",
        _persist_note(persisted),
    )
