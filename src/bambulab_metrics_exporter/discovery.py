"""Opt-in LAN discovery (`BAMBULAB_HOST=auto`): one shared listener for every printer.

The listener opens UDP 2021 on the first lookup, so an exporter without an `auto` printer
never listens. It keeps, for each watched serial only, the addresses that announced it in
the last FRESH_SECONDS. Two addresses for one serial are a conflict and give no address:
either a DHCP change in progress (it clears once the old address goes quiet) or another
device announcing the same serial, which must not receive the access code.

Packets are untrusted and identifying: nothing from them is logged.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from bambulab_metrics_exporter import ssdp

logger = logging.getLogger(__name__)

FOUND = "found"
WAITING = "waiting"
CONFLICT = "conflict"
UNAVAILABLE = "unavailable"
FRESH_SECONDS = 90.0
REOPEN_SECONDS = 30.0
_MAX_ADDRESSES = 8


@dataclass(frozen=True, slots=True)
class Lookup:
    """`reason`: found, waiting, conflict or unavailable (`error` names the errno)."""

    reason: str
    address: str | None = None
    error: str = ""


class LanDiscovery:
    def __init__(
        self,
        open_socket: Callable[[int], ssdp.Datagrams] | None = None,
        clock: Callable[[], float] = time.monotonic,
        poll_seconds: float = 1.0,
    ) -> None:
        self._open_socket = open_socket
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._cond = threading.Condition()
        self._watched: set[str] = set()
        self._seen: dict[str, dict[str, float]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._error = ""
        self._last_open: float | None = None

    @property
    def listening(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def lookup(self, serial: str) -> Lookup:
        """Current answer for a serial; starts watching it (and the listener) if needed."""
        wanted = serial.strip().upper()
        with self._cond:
            self._watched.add(wanted)
            self._ensure_listening()
            return self._current(wanted)

    def wait_for(self, serial: str, timeout: float, cancel: threading.Event) -> Lookup:
        """Like lookup, but waits up to `timeout` while the answer is `waiting`."""
        wanted = serial.strip().upper()
        deadline = time.monotonic() + timeout
        result = self.lookup(wanted)
        with self._cond:
            while result.reason == WAITING and not cancel.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(min(remaining, self._poll_seconds))
                result = self._current(wanted)
        return result

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._poll_seconds + 2.0)

    # -- internals (callers hold self._cond) -------------------------------

    def _current(self, serial: str) -> Lookup:
        if not self.listening and self._error:
            return Lookup(UNAVAILABLE, error=self._error)
        now = self._clock()
        fresh = [
            address
            for address, seen_at in self._seen.get(serial, {}).items()
            if now - seen_at <= FRESH_SECONDS
        ]
        if len(fresh) == 1:
            return Lookup(FOUND, fresh[0])
        if len(fresh) > 1:
            return Lookup(CONFLICT)
        return Lookup(WAITING)

    def _ensure_listening(self) -> None:
        if self.listening:
            return
        now = self._clock()
        if self._last_open is not None and now - self._last_open < REOPEN_SECONDS:
            return
        self._last_open = now
        # Looked up at call time, so the test guard on ssdp._open_socket applies.
        opener = self._open_socket or ssdp._open_socket
        try:
            sock = opener(ssdp.PORT)
        except OSError as exc:
            self._error = ssdp._errno_name(exc)
            logger.warning(
                "LAN discovery: UDP port %d could not be opened (%s)", ssdp.PORT, self._error
            )
            return
        self._error = ""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._listen, args=(sock,), name="lan-discovery", daemon=True
        )
        self._thread.start()

    def _listen(self, sock: ssdp.Datagrams) -> None:
        try:
            sock.settimeout(self._poll_seconds)
            while not self._stop.is_set():
                try:
                    data, address = sock.recvfrom(ssdp.MAX_PACKET)
                except TimeoutError:
                    continue
                except OSError as exc:
                    with self._cond:
                        self._error = ssdp._errno_name(exc)
                    logger.warning("LAN discovery stopped listening (%s)", self._error)
                    return
                source = str(address[0]) if isinstance(address, tuple) and address else ""
                self._record(data, source)
        except Exception as exc:  # noqa: BLE001 - the listener must not take the process down
            with self._cond:
                self._error = type(exc).__name__
            logger.warning("LAN discovery stopped listening (%s)", type(exc).__name__)
        finally:
            sock.close()
            with self._cond:
                self._cond.notify_all()

    def _record(self, data: bytes, source: str) -> None:
        packet = ssdp.parse(data, source, self._clock())
        if packet is None or not packet.is_bambu:
            return
        address = ssdp.announced_address(packet)
        if address is None:
            return
        with self._cond:
            for serial in self._watched:
                if not ssdp.announces_serial(packet, serial):
                    continue
                seen = self._seen.setdefault(serial, {})
                seen[address] = packet.received_at
                for old in [a for a, t in seen.items() if packet.received_at - t > FRESH_SECONDS]:
                    del seen[old]
                while len(seen) > _MAX_ADDRESSES:
                    del seen[min(seen, key=seen.__getitem__)]
                self._cond.notify_all()
