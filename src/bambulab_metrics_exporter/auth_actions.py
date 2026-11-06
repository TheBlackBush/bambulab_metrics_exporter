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
from pathlib import Path

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
