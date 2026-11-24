"""Tests for the shared LAN discovery listener (fake sockets only)."""
from __future__ import annotations

import errno
import logging
import threading
import time

import pytest

from bambulab_metrics_exporter import discovery as dsc

SERIAL = "FAKE00TEST000001"
OTHER = "FAKE00TEST000002"


def _notify(serial: str = SERIAL, location: str = "192.168.1.50") -> bytes:
    return (
        "NOTIFY * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1990\r\n"
        f"Location: {location}\r\n"
        "NT: urn:bambulab-com:device:3dprinter:1\r\n"
        f"USN: {serial}\r\n"
        "DevModel.bbl: N1\r\n"
        "\r\n"
    ).encode()


class FakeSocket:
    """Blocks in recvfrom until a datagram is pushed or the timeout passes."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._queue: list[tuple[bytes, tuple[str, int]] | OSError] = []
        self._timeout = 1.0
        self.closed = False

    def push(self, data: bytes, source: str = "192.168.1.50") -> None:
        with self._cond:
            self._queue.append((data, (source, 2021)))
            self._cond.notify_all()

    def fail(self, exc: OSError) -> None:
        with self._cond:
            self._queue.append(exc)
            self._cond.notify_all()

    def settimeout(self, value: float | None, /) -> None:
        self._timeout = value or 1.0

    def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[str, int]]:
        with self._cond:
            if not self._queue:
                self._cond.wait(self._timeout)
            if not self._queue:
                raise TimeoutError
            item = self._queue.pop(0)
        if isinstance(item, OSError):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class Opener:
    def __init__(self, *results: FakeSocket | OSError) -> None:
        self._results = list(results)
        self.calls = 0

    def __call__(self, port: int) -> FakeSocket:
        assert port == 2021
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, OSError):
            raise result
        return result


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _wait_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached in time")


@pytest.fixture
def made() -> list[dsc.LanDiscovery]:
    items: list[dsc.LanDiscovery] = []
    yield items
    for item in items:
        item.stop()


def _discovery(made, opener, clock=None) -> dsc.LanDiscovery:
    item = dsc.LanDiscovery(open_socket=opener, clock=clock or time.monotonic, poll_seconds=0.02)
    made.append(item)
    return item


def test_nothing_opens_before_the_first_lookup(made) -> None:
    opener = Opener(FakeSocket())
    discovery = _discovery(made, opener)
    assert opener.calls == 0
    assert not discovery.listening


def test_wait_for_returns_the_announced_address(made) -> None:
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    assert discovery.lookup(SERIAL) == dsc.Lookup(dsc.WAITING)
    sock.push(_notify())
    result = discovery.wait_for(SERIAL, 2.0, threading.Event())
    assert result == dsc.Lookup(dsc.FOUND, "192.168.1.50")


def test_wait_for_times_out_while_waiting(made) -> None:
    discovery = _discovery(made, Opener(FakeSocket()))
    started = time.monotonic()
    assert discovery.wait_for(SERIAL, 0.1, threading.Event()).reason == dsc.WAITING
    assert time.monotonic() - started < 1.5


def test_wait_for_stops_when_cancelled(made) -> None:
    discovery = _discovery(made, Opener(FakeSocket()))
    cancel = threading.Event()
    threading.Timer(0.05, cancel.set).start()
    started = time.monotonic()
    assert discovery.wait_for(SERIAL, 5.0, cancel).reason == dsc.WAITING
    assert time.monotonic() - started < 1.5


def test_one_listener_serves_several_printers(made) -> None:
    sock = FakeSocket()
    opener = Opener(sock)
    discovery = _discovery(made, opener)
    discovery.lookup(SERIAL)
    discovery.lookup(OTHER)
    sock.push(_notify(SERIAL, "192.168.1.50"), "192.168.1.50")
    sock.push(_notify(OTHER, "192.168.1.60"), "192.168.1.60")
    assert discovery.wait_for(SERIAL, 2.0, threading.Event()).address == "192.168.1.50"
    assert discovery.wait_for(OTHER, 2.0, threading.Event()).address == "192.168.1.60"
    assert opener.calls == 1


def test_unwatched_serials_are_not_kept(made) -> None:
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    discovery.lookup(SERIAL)
    sock.push(_notify(OTHER, "192.168.1.60"), "192.168.1.60")
    sock.push(_notify(SERIAL), "192.168.1.50")
    assert discovery.wait_for(SERIAL, 2.0, threading.Event()).reason == dsc.FOUND
    assert discovery.lookup(OTHER).reason == dsc.WAITING


@pytest.mark.parametrize(
    ("data", "source"),
    [
        (_notify(location="192.168.1.51"), "192.168.1.50"),  # Location names another host
        (_notify(location="192.0.2.10"), "192.0.2.10"),  # not a LAN address
        (b"NOTIFY * HTTP/1.1\r\nUSN: FAKE00TEST000001\r\n\r\n", "192.168.1.50"),  # not Bambu
        (b"\xff\xfe garbage", "192.168.1.50"),
    ],
)
def test_untrusted_packets_are_ignored(made, data: bytes, source: str) -> None:
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    discovery.lookup(SERIAL)
    sock.push(data, source)
    assert discovery.wait_for(SERIAL, 0.2, threading.Event()).reason == dsc.WAITING


def test_two_addresses_for_one_serial_are_a_conflict(made) -> None:
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    discovery.lookup(SERIAL)
    sock.push(_notify(location="192.168.1.50"), "192.168.1.50")
    sock.push(_notify(location="192.168.1.66"), "192.168.1.66")
    _wait_until(lambda: discovery.lookup(SERIAL).reason == dsc.CONFLICT)
    assert discovery.lookup(SERIAL).address is None


def test_old_address_ages_out_after_a_dhcp_change(made) -> None:
    clock = Clock()
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock), clock)
    discovery.lookup(SERIAL)
    sock.push(_notify(location="192.168.1.50"), "192.168.1.50")
    _wait_until(lambda: discovery.lookup(SERIAL).address == "192.168.1.50")
    clock.now += dsc.FRESH_SECONDS + 1
    assert discovery.lookup(SERIAL).reason == dsc.WAITING
    sock.push(_notify(location="192.168.1.77"), "192.168.1.77")
    _wait_until(lambda: discovery.lookup(SERIAL).address == "192.168.1.77")


def test_port_unavailable_reports_errno_and_reopens_later(made) -> None:
    clock = Clock()
    sock = FakeSocket()
    opener = Opener(OSError(errno.EADDRINUSE, "in use"), sock)
    discovery = _discovery(made, opener, clock)
    assert discovery.lookup(SERIAL) == dsc.Lookup(dsc.UNAVAILABLE, error="EADDRINUSE")
    assert discovery.lookup(SERIAL).reason == dsc.UNAVAILABLE
    assert opener.calls == 1  # no retry before REOPEN_SECONDS
    clock.now += dsc.REOPEN_SECONDS
    assert discovery.lookup(SERIAL).reason == dsc.WAITING
    assert opener.calls == 2


def test_socket_error_while_listening_closes_and_reports(made) -> None:
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    discovery.lookup(SERIAL)
    sock.fail(OSError(errno.ENETDOWN, "down"))
    _wait_until(lambda: not discovery.listening)
    assert sock.closed
    assert discovery.lookup(SERIAL) == dsc.Lookup(dsc.UNAVAILABLE, error="ENETDOWN")


def test_stop_closes_the_socket(made) -> None:
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    discovery.lookup(SERIAL)
    assert discovery.listening
    discovery.stop()
    assert sock.closed
    assert not discovery.listening


def test_default_opener_is_the_guarded_ssdp_socket(made) -> None:
    # conftest replaces ssdp._open_socket with one that raises EACCES.
    discovery = dsc.LanDiscovery(poll_seconds=0.02)
    made.append(discovery)
    assert discovery.lookup(SERIAL) == dsc.Lookup(dsc.UNAVAILABLE, error="EACCES")


def test_nothing_from_packets_is_logged(made, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    sock = FakeSocket()
    discovery = _discovery(made, Opener(sock))
    discovery.lookup(SERIAL)
    sock.push(_notify())
    discovery.wait_for(SERIAL, 2.0, threading.Event())
    assert "192.168.1.50" not in caplog.text
    assert SERIAL not in caplog.text
