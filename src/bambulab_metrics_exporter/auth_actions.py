"""Actions behind the /auth page: configure local or cloud mode.

Shared by the web page; ``bambulab-reauth`` covers the same cloud login from a shell.
Every action validates its input, applies it to the process environment, persists it
encrypted when BAMBULAB_SECRET_KEY is set, and never returns secrets to the caller.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any

from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthError,
    get_bind_devices,
    login_with_code,
    send_code,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.overrides import (
    DEFAULT_CONFIG_DIR,
    backup_credentials,
    remember_original,
    save_overrides,
    set_env,
)
from bambulab_metrics_exporter.printers import (
    MAX_PRINTERS,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL,
    PrinterConfig,
    printer_id_for,
)
from bambulab_metrics_exporter.printers import mask_serial as mask_serial
from bambulab_metrics_exporter.reauth import (
    CREDENTIAL_KEYS,
    apply_credentials,
    credentials_path,
    save_login_result,
)
from bambulab_metrics_exporter.security import ensure_parent

logger = logging.getLogger(__name__)

_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,253}$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9]{8,32}$")
_ACCESS_CODE_RE = re.compile(r"^\S{4,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,253}$")
_CODE_RE = re.compile(r"^[0-9A-Za-z]{4,12}$")
_NAME_RE = re.compile(r"^[^\x00-\x1f]{0,64}$")
_PORT_RE = re.compile(r"[0-9]{1,5}")

SEND_CODE_INTERVAL_SECONDS = 60.0
SEND_CODE_MAX_PER_ROUND = 5
SEND_CODE_FIRST_LOCK_SECONDS = 600.0
SEND_CODE_LATER_LOCK_SECONDS = 3600.0
SEND_CODE_STATE_FILE = "send-code-limit.json"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    message: str
    note: str = ""


class AuthInputError(ValueError):
    """Invalid user input; the message is safe to show on the page."""


def _persist(values: dict[str, str]) -> bool:
    for key, value in values.items():
        set_env(key, value)
    return save_overrides(values)


def persist_note(persisted: bool) -> str:
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
        True, f"Local connection saved for printer {mask_serial(serial)}.", persist_note(persisted)
    )


class SendCodeLimiter:
    """Ladder for verification emails: the page is unauthenticated, so one global limit
    applies. Timestamps are wall clock because they must survive a restart."""

    def __init__(
        self, path: Path | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._loaded = False
        self._round = 1
        self._sends = 0
        self._last_send = 0.0
        self._locked_until = 0.0

    def _state_path(self) -> Path:
        if self._path is not None:
            return self._path
        config_dir = os.getenv("BAMBULAB_CONFIG_DIR", DEFAULT_CONFIG_DIR)
        return Path(config_dir) / SEND_CODE_STATE_FILE

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._state_path().read_text(encoding="utf-8"))
            values = (raw["round"], raw["sends"], raw["last_send"], raw["locked_until"])
            round_, sends = int(values[0]), int(values[1])
            last_send, locked_until = float(values[2]), float(values[3])
        except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
            return  # Missing or damaged: start a fresh ladder.
        self._round = max(round_, 1)
        self._sends = max(sends, 0)
        self._last_send = last_send
        self._locked_until = locked_until

    def _save(self) -> None:
        path = self._state_path()
        payload = {
            "round": self._round,
            "sends": self._sends,
            "last_send": self._last_send,
            "locked_until": self._locked_until,
        }
        temp = path.with_name(path.name + ".tmp")
        try:
            ensure_parent(path)
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(temp, path)
        except OSError:
            logger.warning("Could not save the send-code limit; it applies until a restart")

    def wait_seconds(self) -> int:
        """Seconds until the next send is allowed, 0 when it is. Read-only: it never counts
        a send and never saves, but applies the same caps as ``check_and_record``."""
        with self._lock:
            self._load()
            now = self._clock()
            last_send = min(self._last_send, now)
            locked_until = min(self._locked_until, now + SEND_CODE_LATER_LOCK_SECONDS)
            if locked_until > now:
                return math.ceil(locked_until - now)
            if self._sends >= SEND_CODE_MAX_PER_ROUND:
                return 0  # The finished round is over; the next send starts a new one.
            wait = SEND_CODE_INTERVAL_SECONDS - (now - last_send)
            if self._sends and wait > 0:
                return math.ceil(wait)
            return 0

    def check_and_record(self) -> None:
        """Count one send, or raise AuthInputError saying how long to wait."""
        with self._lock:
            self._load()
            now = self._clock()
            # A clock change must not extend the wait past the longest step; the caps are
            # applied on every call and written back so a restart cannot renew them.
            capped_send = min(self._last_send, now)
            capped_lock = min(self._locked_until, now + SEND_CODE_LATER_LOCK_SECONDS)
            if (capped_send, capped_lock) != (self._last_send, self._locked_until):
                self._last_send, self._locked_until = capped_send, capped_lock
                self._save()
            if self._locked_until > now:
                minutes = math.ceil((self._locked_until - now) / 60)
                raise AuthInputError(f"Too many codes requested. Try again in {minutes} minutes.")
            if self._sends >= SEND_CODE_MAX_PER_ROUND:
                self._round += 1
                self._sends = 0
            wait = SEND_CODE_INTERVAL_SECONDS - (now - self._last_send)
            if self._sends and wait > 0:
                raise AuthInputError(
                    f"A code was just sent. Try again in {math.ceil(wait)} seconds."
                )
            self._sends += 1
            self._last_send = now
            if self._sends >= SEND_CODE_MAX_PER_ROUND:
                step = (
                    SEND_CODE_FIRST_LOCK_SECONDS
                    if self._round == 1
                    else SEND_CODE_LATER_LOCK_SECONDS
                )
                self._locked_until = now + step
                logger.warning(
                    "Send-code limit reached; verification emails are paused for %d minutes",
                    step // 60,
                )
            self._save()

    def reset(self) -> None:
        with self._lock:
            self._loaded = True
            self._round, self._sends = 1, 0
            self._last_send = self._locked_until = 0.0
            self._save()


class CodeSender:
    """Sends verification emails within the limits of ``SendCodeLimiter``."""

    def __init__(self, limiter: SendCodeLimiter | None = None) -> None:
        self._limiter = limiter or SendCodeLimiter()

    def send(self, email: str) -> ActionResult:
        email = email.strip()
        if not _EMAIL_RE.match(email):
            raise AuthInputError("Enter the email address of your Bambu account.")
        self._limiter.check_and_record()
        try:
            send_code(email)
        except CloudAuthError as exc:
            return ActionResult(False, f"Could not send the code: {exc}")
        return ActionResult(True, "Verification code sent. Check your email.")

    def wait_seconds(self) -> int:
        return self._limiter.wait_seconds()

    def reset(self) -> None:
        self._limiter.reset()


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

    login_only = False
    if not serial:
        try:
            devices = get_bind_devices(result.access_token)
        except CloudAuthError as exc:
            return ActionResult(False, f"Logged in, but the printer list failed: {exc}")
        serials = [str(d["dev_id"]) for d in devices if d.get("dev_id")]
        if not serials:
            return ActionResult(False, "This account has no printers.")
        if len(serials) == 1:
            serial = serials[0]
        else:
            login_only = True  # The page lists the printers; nothing else changes yet.

    # Record what the container had, so "Reset to env vars" can undo this login.
    for key in CREDENTIAL_KEYS:
        remember_original(key)
    values = {"BAMBULAB_TRANSPORT": "cloud_mqtt", "BAMBULAB_SERIAL": serial}
    persisted = save_overrides({}) if login_only else _persist(values)
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
    if login_only:
        return ActionResult(True, "Signed in. Select your printers below.", persist_note(persisted))
    return ActionResult(
        True,
        f"Signed in to Bambu Cloud for printer {mask_serial(serial)}.",
        persist_note(persisted),
    )


@dataclass(frozen=True, slots=True)
class CloudDevice:
    printer_id: str
    serial: str
    name: str
    model: str
    online: bool


class CloudDeviceList:
    """Printers on the signed-in account, cached so page reloads do not hit Bambu Cloud.
    ``refresh`` does network I/O; ``peek`` is safe on the event loop.

    ``_fetch_lock`` makes concurrent refreshes share one fetch per TTL. ``_lock`` guards only
    the cached values and is never held across the network call, so a slow Bambu response
    cannot block ``peek`` or ``clear``.
    """

    def __init__(
        self, ttl_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._expires = float("-inf")
        self._devices: list[CloudDevice] = []
        self._generation = 0
        self._lock = threading.Lock()
        self._fetch_lock = threading.Lock()

    def refresh(self) -> None:
        with self._fetch_lock:
            token = os.getenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "")
            if not token:
                return
            with self._lock:
                if self._clock() < self._expires:
                    return
                generation = self._generation
            devices = _fetch_devices(token)
            with self._lock:
                # A clear() during the fetch means this answer may be the previous account's.
                if generation == self._generation:
                    self._devices = devices
                    self._expires = self._clock() + self._ttl

    def peek(self) -> list[CloudDevice]:
        with self._lock:
            return list(self._devices)

    def clear(self) -> None:
        with self._lock:
            self._devices = []
            self._expires = float("-inf")
            self._generation += 1


def _fetch_devices(token: str) -> list[CloudDevice]:
    """Never raises for a bad response: this runs on page load. The errors can carry
    response content, so none of it reaches the log."""
    try:
        raw = get_bind_devices(token, timeout_seconds=5.0, retries=1)
        unique: dict[str, CloudDevice] = {}
        for device in map(_device, raw):
            if device is not None:
                unique.setdefault(device.serial, device)
    except (CloudAuthError, OSError, ValueError, AttributeError, RecursionError, HTTPException):
        logger.warning("Could not read the printer list from Bambu Cloud")
        return []
    return list(unique.values())


def _text(value: Any, limit: int) -> str:
    """Bounded plain text. JSON can carry lone surrogates, which UTF-8 output cannot."""
    return str(value or "").encode("utf-8", "replace").decode("utf-8")[:limit]


def _device(item: object) -> CloudDevice | None:
    """Payload is untrusted: skip anything without a usable serial."""
    if not isinstance(item, dict):
        return None
    serial = str(item.get("dev_id") or "")
    if not _SERIAL_RE.fullmatch(serial):  # match would allow a trailing newline
        return None
    return CloudDevice(
        printer_id=printer_id_for(serial),
        serial=serial,
        name=_text(item.get("name"), 64),
        model=_text(item.get("dev_product_name") or item.get("model"), 32),
        online=item.get("online") is True,
    )


def _check_limit(count: int) -> None:
    if count > MAX_PRINTERS:
        raise AuthInputError(f"An exporter can monitor at most {MAX_PRINTERS} printers.")


def select_cloud_printers(
    current: list[PrinterConfig], devices: list[CloudDevice], selected: set[str]
) -> list[PrinterConfig]:
    """Replace the cloud part of the list with ``selected``; LAN printers stay."""
    by_id = {device.printer_id: device for device in devices}
    if not selected <= by_id.keys():
        raise AuthInputError("A selected printer is no longer on this account. Reload the page.")
    lan = [config for config in current if config.transport == TRANSPORT_LOCAL]
    lan_serials = {config.serial for config in lan}
    env_serials = {config.serial for config in current if config.env_printer}
    chosen: list[PrinterConfig] = []
    for device in by_id.values():
        if device.printer_id not in selected:
            continue
        if device.serial in lan_serials:
            raise AuthInputError(
                f"Printer {mask_serial(device.serial)} is already added as a LAN printer."
            )
        chosen.append(
            PrinterConfig(
                serial=device.serial, transport=TRANSPORT_CLOUD, name=device.name,
                model=device.model, env_printer=device.serial in env_serials,
            )
        )
    _check_limit(len(lan) + len(chosen))
    return [*lan, *chosen]


def add_local_printer(
    current: list[PrinterConfig],
    host: str,
    serial: str,
    access_code: str,
    port: str = "",
    name: str = "",
) -> list[PrinterConfig]:
    """Add a LAN printer, or update the LAN printer with the same serial."""
    host, serial = host.strip(), serial.strip().upper()
    access_code, port, name = access_code.strip(), port.strip(), name.strip()
    if not _HOST_RE.match(host):
        raise AuthInputError("Enter the printer IP address or host name.")
    if not _SERIAL_RE.match(serial):
        raise AuthInputError("The serial number must be 8 to 32 letters or digits.")
    if not _ACCESS_CODE_RE.match(access_code):
        raise AuthInputError("Enter the LAN access code shown on the printer.")
    if not _NAME_RE.match(name):
        raise AuthInputError("The printer name can have at most 64 characters.")
    if port and (not _PORT_RE.fullmatch(port) or not 0 < int(port) < 65536):
        raise AuthInputError("The port must be a number between 1 and 65535.")
    existing = next((config for config in current if config.serial == serial), None)
    if existing is not None and existing.transport != TRANSPORT_LOCAL:
        raise AuthInputError(f"Printer {mask_serial(serial)} is already added through the cloud.")
    config = PrinterConfig(
        serial=serial, transport=TRANSPORT_LOCAL, host=host, port=int(port or 8883),
        access_code=access_code, name=name or (existing.name if existing else ""),
        env_printer=existing.env_printer if existing else False,
    )
    updated = [config if item.serial == serial else item for item in current]
    if existing is None:
        updated.append(config)
    _check_limit(len(updated))
    return updated


def remove_printer(current: list[PrinterConfig], printer_id: str) -> list[PrinterConfig]:
    updated = [config for config in current if config.printer_id != printer_id]
    if len(updated) == len(current):
        raise AuthInputError("That printer is not in the list. Reload the page.")
    return updated
