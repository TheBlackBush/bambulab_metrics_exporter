"""Passive SSDP listener: parsing, bounds and the capture loop, with a fake socket.

The packets are modeled on community descriptions of Bambu Lab announcements, not on a
capture: the real format is still to be confirmed from diagnostic reports.
"""
from __future__ import annotations

import errno
import socket
import threading
from typing import Any

import pytest

from bambulab_metrics_exporter import ssdp

REAL_OPEN_SOCKET = ssdp._open_socket  # conftest replaces it in every test
SERIAL = "030FAKE00000001"


def _packet(serial: str = SERIAL) -> bytes:
    headers = {
        "HOST": "239.255.255.250:1990", "Server": "UPnP/1.0", "Location": "192.168.1.50",
        "NT": "urn:bambulab-com:device:3dprinter:1", "USN": serial,
        "Cache-Control": "max-age=1800", "DevModel.bbl": "N1",
        "DevName.bbl": "Garage Workhorse", "DevSignal.bbl": "-52", "DevConnect.bbl": "lan",
        "DevBind.bbl": "free", "DevVersion.bbl": "01.04.00.00",
    }
    lines = ["NOTIFY * HTTP/1.1"] + [f"{key}: {value}" for key, value in headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Socket:
    """Delivers (time, data, source) events in order and times out like a real socket."""

    def __init__(self, clock: _Clock, events: list[tuple[float, bytes, str]],
                 fail: OSError | None = None) -> None:
        self.clock, self.events, self.fail = clock, list(events), fail
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def recvfrom(self, bufsize: int) -> tuple[bytes, Any]:
        assert self.timeout is not None and self.timeout > 0
        if self.events and self.events[0][0] <= self.clock.now + self.timeout:
            at, data, source = self.events.pop(0)
            self.clock.now = max(self.clock.now, at)
            return data[:bufsize], (source, ssdp.PORT)
        if self.fail is not None:
            raise self.fail
        self.clock.now += self.timeout
        raise TimeoutError

    def close(self) -> None:
        self.closed = True


def _capture(events: list[tuple[float, bytes, str]], wanted: frozenset[str] = frozenset({SERIAL}),
             fail: OSError | None = None) -> tuple[ssdp.Capture, _Socket]:
    clock = _Clock()
    sock = _Socket(clock, [(clock.now + at, data, src) for at, data, src in events], fail)

    def opener(port: int) -> _Socket:
        assert port == ssdp.PORT
        return sock

    return ssdp.capture(set(wanted), open_socket=opener, clock=clock, window=8.0), sock


# -- parser -------------------------------------------------------------------------------


def test_parse_reads_start_line_and_headers() -> None:
    packet = ssdp.parse(_packet(), "192.168.1.50", 1.0)
    assert packet is not None
    assert packet.start_line == "NOTIFY * HTTP/1.1"
    assert packet.source == "192.168.1.50" and packet.received_at == 1.0
    assert packet.headers[0] == ("HOST", "239.255.255.250:1990")
    assert packet.header("usn") == SERIAL
    assert packet.header("devname.BBL") == "Garage Workhorse"
    assert packet.header("missing") == ""
    assert packet.is_bambu


@pytest.mark.parametrize("data", [
    b"", b"\xff\xfe\x00", b"just text", b"NOTIFY * HTTP/1.1\r\n\r\n",
    b"NOTIFY\r\nbad header\r\n: novalue\r\n",
])
def test_parse_rejects_junk(data: bytes) -> None:
    assert ssdp.parse(data, "", 0.0) is None


def test_parse_bounds_names_values_and_count() -> None:
    lines = ["NOTIFY * HTTP/1.1", "Bad Name: x", "Ok.bbl: " + "v" * 1000]
    lines += [f"H{i}: {i}" for i in range(100)]
    packet = ssdp.parse("\r\n".join(lines).encode() + b"\xff", "", 0.0)
    assert packet is not None
    assert "Bad Name" not in [name for name, _ in packet.headers]
    assert len(packet.headers) == ssdp.MAX_HEADERS
    assert packet.header("Ok.bbl") == "v" * ssdp.MAX_VALUE


def test_only_bambu_packets_count_as_bambu() -> None:
    generic = ssdp.parse(b"NOTIFY * HTTP/1.1\r\nNT: upnp:rootdevice\r\nUSN: uuid:1234\r\n", "", 0)
    by_nt = ssdp.parse(b"NOTIFY * HTTP/1.1\r\nNT: urn:bambulab-com:device:3dprinter:1\r\n", "", 0)
    assert generic is not None and not generic.is_bambu
    assert by_nt is not None and by_nt.is_bambu


# -- capture loop ---------------------------------------------------------------------------


def test_capture_stops_once_each_wanted_printer_announced_twice() -> None:
    result, sock = _capture([(1.0, _packet(), "192.168.1.50"), (6.0, _packet(), "192.168.1.50"),
                             (7.0, _packet(), "192.168.1.50")])
    assert result.status == "received"
    assert len(result.packets) == 2
    assert result.waited_seconds == 6.0
    assert sock.closed


def test_capture_without_wanted_serials_listens_the_whole_window() -> None:
    generic = b"NOTIFY * HTTP/1.1\r\nNT: upnp:rootdevice\r\nUSN: uuid:1234\r\n"
    result, _ = _capture([(1.0, _packet(), "192.168.1.50"), (2.0, generic, "192.168.1.9"),
                          (3.0, b"\x00junk", "192.168.1.9")], wanted=frozenset())
    assert result.status == "received"
    assert len(result.packets) == 1 and result.ignored == 2
    assert result.waited_seconds == 8.0


def test_capture_with_nothing_heard_reports_none() -> None:
    result, sock = _capture([])
    assert result.status == "none" and result.packets == () and result.error == ""
    assert result.waited_seconds == 8.0 and sock.closed


def test_capture_reports_a_port_it_cannot_open() -> None:
    def opener(port: int) -> Any:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    result = ssdp.capture({SERIAL}, open_socket=opener, clock=_Clock(), window=8.0)
    assert result.status == "unavailable" and result.error == "EADDRINUSE"
    assert result.packets == ()


@pytest.mark.parametrize(("fail", "name"), [
    (OSError(errno.ENETDOWN, "Network is down"), "ENETDOWN"),
    (OSError("odd failure"), "OSError"),
])
def test_capture_keeps_what_arrived_before_a_socket_error(fail: OSError, name: str) -> None:
    result, sock = _capture([(1.0, _packet(), "192.168.1.50")], fail=fail)
    assert result.status == "received" and len(result.packets) == 1
    assert result.error == name and sock.closed


def test_capture_keeps_at_most_max_packets() -> None:
    flood = [(0.01 * i, _packet(f"01PFAKE{i:08d}"), "192.168.1.60") for i in range(500)]
    result, _ = _capture(flood)
    assert len(result.packets) == ssdp.MAX_PACKETS


def test_a_second_capture_while_one_runs_reports_busy() -> None:
    started, release = threading.Event(), threading.Event()
    clock = _Clock()

    class _Blocking(_Socket):
        def recvfrom(self, bufsize: int) -> tuple[bytes, Any]:
            started.set()
            release.wait(5)
            return super().recvfrom(bufsize)

    sock = _Blocking(clock, [])
    first: list[ssdp.Capture] = []
    worker = threading.Thread(target=lambda: first.append(
        ssdp.capture(set(), open_socket=lambda port: sock, clock=clock, window=1.0)))
    worker.start()
    assert started.wait(5)

    def must_not_open(port: int) -> Any:
        pytest.fail("a busy capture must not open a socket")

    second = ssdp.capture(set(), open_socket=must_not_open, clock=_Clock(), window=1.0)
    release.set()
    worker.join(5)
    assert second.status == "busy" and second.packets == ()
    assert first[0].status == "none"


# -- real socket -------------------------------------------------------------------------


def test_tests_never_listen_on_the_real_port() -> None:
    result = ssdp.capture({SERIAL}, window=0.1)
    assert result.status == "unavailable" and result.error == "EACCES"


def test_open_socket_binds_a_udp_port() -> None:
    sock = REAL_OPEN_SOCKET(0)
    try:
        assert sock.type == socket.SOCK_DGRAM
    finally:
        sock.close()
