"""Printer scan for the /auth page: which printers announce themselves on the LAN now.

The page is unauthenticated and may be reached through a reverse proxy, so full serials never
leave the process: each printer found gets a short-lived random pick id, and the LAN form posts
that id instead of the serial. Listening sends nothing to printers (see `ssdp.py`). Packets are
untrusted: only a serial-shaped USN token, a trusted sender address
(`ssdp.announced_address`) and a model name the exporter knows are kept. Nothing from a packet
is logged.
"""

from __future__ import annotations

import math
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from bambulab_metrics_exporter import ssdp
from bambulab_metrics_exporter.models import PrinterSnapshot

COOLDOWN_SECONDS = 10.0
PICK_SECONDS = 300.0
MAX_FOUND = 32
MAX_PICKS = 64
BUSY = "busy"
COOLDOWN = "cooldown"
# Bambu serials are uppercase letters and digits with at least one digit; lowercase words in
# USN urns (such as `3dprinter`) are not serials.
_SERIAL_RE = re.compile(r"(?=[A-Z0-9]*[0-9])[A-Z0-9]{8,32}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_PICK_RE = re.compile(r"[A-Za-z0-9_-]{16}")


@dataclass(frozen=True, slots=True)
class Found:
    """One announcing printer. `address` is empty when more than one address announced the
    serial during the scan: it is listed, but cannot be picked."""

    serial: str
    address: str
    model: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    """`status`: received, none, unavailable (`error` names the errno), busy or cooldown.
    `printers` pairs each printer with its pick id (empty when it cannot be picked)."""

    status: str
    printers: tuple[tuple[str, Found], ...] = ()
    wait_seconds: int = 0
    error: str = ""


def serial_of(packet: ssdp.Packet) -> str | None:
    """The one serial-shaped token in `USN`. None when there is none or several, so a packet
    cannot make the page offer an arbitrary value."""
    serials = {t for t in _TOKEN_RE.findall(packet.header("USN")) if _SERIAL_RE.fullmatch(t)}
    return serials.pop() if len(serials) == 1 else None


def model_of(serial: str, hint: str) -> str:
    """Model from the serial prefix, else from the announced model code; empty when the
    exporter does not know it, so raw header text never reaches the page."""
    snapshot = PrinterSnapshot(
        connected=False, raw={}, configured_serial=serial, configured_model=hint or None
    )
    return snapshot.printer_type or ""


def found_printers(capture: ssdp.Capture) -> list[Found]:
    """One entry per serial in the order first heard, at most MAX_FOUND. Packets without a
    serial or a trusted address are skipped."""
    addresses: dict[str, set[str]] = {}
    models: dict[str, str] = {}
    for packet in capture.packets:
        serial = serial_of(packet)
        address = ssdp.announced_address(packet)
        if serial is None or address is None:
            continue
        if serial not in addresses and len(addresses) >= MAX_FOUND:
            continue
        addresses.setdefault(serial, set()).add(address)
        models[serial] = models.get(serial) or model_of(serial, packet.header("DevModel.bbl"))
    return [
        Found(serial, next(iter(seen)) if len(seen) == 1 else "", models[serial])
        for serial, seen in addresses.items()
    ]


class PrinterScanner:
    """Runs scans for the page: one at a time, then a short pause (the page is
    unauthenticated and a scan holds a worker thread for the whole window). Remembers each
    pick for PICK_SECONDS, at most MAX_PICKS."""

    def __init__(
        self,
        capture: Callable[[Iterable[str]], ssdp.Capture] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cooldown_seconds: float = COOLDOWN_SECONDS,
        pick_seconds: float = PICK_SECONDS,
    ) -> None:
        self._capture = capture
        self._clock = clock
        self._cooldown = cooldown_seconds
        self._pick_seconds = pick_seconds
        self._lock = threading.Lock()
        self._running = False
        self._next_scan = float("-inf")
        self._picks: OrderedDict[str, tuple[float, Found]] = OrderedDict()

    def scan(self) -> ScanResult:
        """Listen for announcements; blocks up to ssdp.LISTEN_SECONDS."""
        with self._lock:
            if self._running:
                return ScanResult(BUSY)
            wait = self._next_scan - self._clock()
            if wait > 0:
                return ScanResult(COOLDOWN, wait_seconds=math.ceil(wait))
            self._running = True
        try:
            # Looked up at call time, so the test guard on ssdp applies.
            capture = (self._capture or ssdp.capture)(())
        except BaseException:
            self._finish(pause=True)
            raise
        # A diagnostics capture held the window: nothing was heard, so no pause either.
        self._finish(pause=capture.status != BUSY)
        if capture.status == BUSY:
            return ScanResult(BUSY)
        printers = tuple(
            (self._remember(found) if found.address else "", found)
            for found in found_printers(capture)
        )
        return ScanResult(capture.status, printers, error=capture.error)

    def pick(self, pick_id: str) -> Found | None:
        """The printer behind a pick id; None when unknown, expired or malformed."""
        if not _PICK_RE.fullmatch(pick_id):
            return None
        with self._lock:
            self._prune()
            entry = self._picks.get(pick_id)
        return entry[1] if entry is not None else None

    def _finish(self, pause: bool) -> None:
        with self._lock:
            self._running = False
            if pause:
                self._next_scan = self._clock() + self._cooldown

    def _remember(self, found: Found) -> str:
        pick_id = secrets.token_urlsafe(12)
        with self._lock:
            self._prune()
            self._picks[pick_id] = (self._clock() + self._pick_seconds, found)
            while len(self._picks) > MAX_PICKS:
                self._picks.popitem(last=False)
        return pick_id

    def _prune(self) -> None:
        """Drop expired picks; the caller holds the lock."""
        now = self._clock()
        for pick_id in [key for key, (expires, _) in self._picks.items() if expires <= now]:
            del self._picks[pick_id]
