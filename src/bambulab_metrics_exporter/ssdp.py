"""Passive listener for Bambu Lab LAN announcements (SSDP on UDP 2021).

Printers announce themselves on the LAN with SSDP-style NOTIFY packets. The diagnostic
report listens for a few seconds to show whether those packets reach the exporter and what
they carry, so LAN discovery can be built from real packets. Listening sends nothing to printers or other devices (the system joins the multicast group, as any listener does).

This module only receives and parses. Packets hold serials, addresses and printer names:
`diagnostics.py` sanitizes them before anything leaves the process, and they are never
logged.
"""

from __future__ import annotations

import contextlib
import errno
import re
import socket
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

PORT = 2021
MULTICAST_GROUP = "239.255.255.250"
LISTEN_SECONDS = 8.0
MAX_PACKET = 4096
MAX_PACKETS = 64
MAX_HEADERS = 40
MAX_VALUE = 256
_MIN_WAIT = 0.05
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# The report route is unauthenticated: one capture at a time keeps requests from piling up
# threads that each wait the whole window.
_LOCK = threading.Lock()


class Datagrams(Protocol):
    """The part of a UDP socket the listener uses (a fake in tests)."""

    def settimeout(self, value: float | None, /) -> None: ...

    def recvfrom(self, bufsize: int, /) -> tuple[bytes, Any]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Packet:
    """One received announcement, unsanitized."""

    received_at: float
    source: str
    start_line: str
    headers: tuple[tuple[str, str], ...]

    def header(self, name: str) -> str:
        """First value of a header, matched without case; empty when absent."""
        wanted = name.lower()
        for key, value in self.headers:
            if key.lower() == wanted:
                return value
        return ""

    @property
    def is_bambu(self) -> bool:
        """Bambu packets carry `*.bbl` headers or a bambulab NT. Other SSDP on the port is
        counted but not kept, so the report holds nothing about unrelated devices."""
        if any(key.lower().endswith(".bbl") for key, _ in self.headers):
            return True
        return "bambulab" in self.header("NT").lower()


@dataclass(frozen=True, slots=True)
class Capture:
    """Result of one listening window. `status`: received, none, unavailable or busy."""

    status: str
    listen_seconds: float
    waited_seconds: float
    packets: tuple[Packet, ...]
    ignored: int
    error: str = ""


def parse(data: bytes, source: str, received_at: float) -> Packet | None:
    """Start line plus `Name: value` headers. None when no header is readable."""
    text = data[:MAX_PACKET].decode("utf-8", errors="replace")
    lines = text.replace("\r\n", "\n").split("\n")
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        name = name.strip()
        if not sep or not _HEADER_NAME_RE.match(name):
            continue
        headers.append((name, value.strip()[:MAX_VALUE]))
        if len(headers) == MAX_HEADERS:
            break
    if not headers:
        return None
    return Packet(received_at, source, lines[0].strip()[:MAX_VALUE], tuple(headers))


def _errno_name(exc: OSError) -> str:
    if exc.errno is None:
        return "OSError"
    return errno.errorcode.get(exc.errno, "OSError")


def _open_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
    except OSError:
        sock.close()
        raise
    # Multicast announcements need the group joined; broadcast ones arrive without it.
    with contextlib.suppress(OSError):
        membership = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    return sock


def _announced_enough(serials: set[str], seen: dict[str, int]) -> bool:
    return bool(serials) and all(seen.get(serial, 0) >= 2 for serial in serials)


def capture(
    wanted: Iterable[str],
    *,
    open_socket: Callable[[int], Datagrams] | None = None,
    clock: Callable[[], float] = time.monotonic,
    window: float = LISTEN_SECONDS,
) -> Capture:
    """Listen up to `window` seconds. Stops early once every wanted serial was heard twice
    (two packets give the interval). A capture already running makes this one `busy`."""
    serials = {serial.upper() for serial in wanted if serial}
    if not _LOCK.acquire(blocking=False):
        return Capture("busy", window, 0.0, (), 0)
    try:
        return _listen(serials, open_socket or _open_socket, clock, window)
    finally:
        _LOCK.release()


def _listen(
    serials: set[str],
    opener: Callable[[int], Datagrams],
    clock: Callable[[], float],
    window: float,
) -> Capture:
    start = clock()
    try:
        sock = opener(PORT)
    except OSError as exc:
        return Capture("unavailable", window, 0.0, (), 0, _errno_name(exc))
    packets: list[Packet] = []
    ignored = 0
    error = ""
    seen: dict[str, int] = {}
    try:
        while not _announced_enough(serials, seen):
            remaining = start + window - clock()
            if remaining <= 0:
                break
            sock.settimeout(max(remaining, _MIN_WAIT))
            try:
                data, address = sock.recvfrom(MAX_PACKET)
            except TimeoutError:
                continue
            except OSError as exc:
                error = _errno_name(exc)
                break
            source = str(address[0]) if isinstance(address, tuple) and address else ""
            packet = parse(data, source, clock())
            if packet is None or not packet.is_bambu:
                ignored += 1
                continue
            if len(packets) < MAX_PACKETS:
                packets.append(packet)
            usn = packet.header("USN").upper()
            for serial in serials:
                if serial in usn:
                    seen[serial] = seen.get(serial, 0) + 1
    finally:
        sock.close()
    status = "received" if packets else "none"
    return Capture(status, window, round(clock() - start, 1), tuple(packets), ignored, error)
