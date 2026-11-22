"""Printer scan for the /auth page: packets to printers, pick ids and limits (fake captures)."""
from __future__ import annotations

import threading

import pytest

from bambulab_metrics_exporter import lan_scan, ssdp
from bambulab_metrics_exporter.lan_scan import Found, PrinterScanner, found_printers, serial_of

X1C = "00MFAKETEST0001"
OTHER = "FAKE00TEST000002"


def packet(serial: str = X1C, source: str = "192.168.1.50", location: str | None = None,
           model: str = "", usn: str | None = None) -> ssdp.Packet:
    headers = [
        ("NT", "urn:bambulab-com:device:3dprinter:1"),
        ("USN", serial if usn is None else usn),
        ("Location", source if location is None else location),
    ]
    if model:
        headers.append(("DevModel.bbl", model))
    return ssdp.Packet(0.0, source, "NOTIFY * HTTP/1.1", tuple(headers))


def capture(*packets: ssdp.Packet, status: str = "received", error: str = "") -> ssdp.Capture:
    return ssdp.Capture(status, 8.0, 8.0, tuple(packets), 0, error)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _scanner(*results: ssdp.Capture, clock: Clock | None = None, **options: float):
    calls: list[tuple[str, ...]] = []
    answers = list(results)

    def fake(wanted):
        calls.append(tuple(wanted))
        return answers.pop(0) if len(answers) > 1 else answers[0]

    return PrinterScanner(capture=fake, clock=clock or Clock(), **options), calls


@pytest.mark.parametrize(
    ("usn", "expected"),
    [
        (X1C, X1C),
        (f"uuid:{X1C}", X1C),
        (f"{X1C}::urn:bambulab-com:device:3dprinter:1", X1C),
        ("", None),
        ("notaserial", None),
        (f"{X1C} {OTHER}", None),
        ("ABCDEFGH", None),
    ],
)
def test_serial_of_takes_the_one_serial_shaped_token(usn: str, expected: str | None) -> None:
    assert serial_of(packet(usn=usn)) == expected


def test_found_printers_keeps_trusted_announcements_once_each() -> None:
    found = found_printers(capture(
        packet(), packet(),
        packet(OTHER, source="10.0.0.7", model="N1"),
        packet("FAKE00TEST000003", source="203.0.113.5"),
        packet("FAKE00TEST000004", source="192.168.1.60", location="192.168.1.99"),
    ))
    assert found == [Found(X1C, "192.168.1.50", "X1C"), Found(OTHER, "10.0.0.7", "A1MINI")]


def test_two_addresses_for_one_serial_cannot_be_picked() -> None:
    found = found_printers(capture(packet(), packet(source="192.168.1.51")))
    assert found == [Found(X1C, "", "X1C")]


def test_unknown_or_hostile_model_text_never_becomes_the_model() -> None:
    found = found_printers(capture(packet(OTHER, model="<script>alert(1)</script>")))
    assert found == [Found(OTHER, "192.168.1.50", "")]


def test_found_printers_is_bounded() -> None:
    packets = [
        packet(f"FAKE00TEST{index:06d}", source=f"192.168.1.{index + 1}")
        for index in range(lan_scan.MAX_FOUND + 5)
    ]
    assert len(found_printers(capture(*packets))) == lan_scan.MAX_FOUND


def test_scan_listens_for_everyone_and_remembers_picks() -> None:
    scanner, calls = _scanner(capture(
        packet(), packet(OTHER, source="192.168.1.51"), packet(OTHER, source="192.168.1.52")
    ))
    result = scanner.scan()
    assert calls == [()]
    assert result.status == "received"
    (pick, first), (no_pick, second) = result.printers
    assert first == Found(X1C, "192.168.1.50", "X1C") and len(pick) == 16
    assert second.address == "" and no_pick == ""
    assert scanner.pick(pick) == first
    assert scanner.pick("") is None
    assert scanner.pick("x" * 15) is None
    assert scanner.pick(pick + "\n") is None


def test_picks_expire() -> None:
    clock = Clock()
    scanner, _ = _scanner(capture(packet()), clock=clock)
    pick = scanner.scan().printers[0][0]
    clock.now += lan_scan.PICK_SECONDS - 1
    assert scanner.pick(pick) is not None
    clock.now += 2
    assert scanner.pick(pick) is None


def test_old_picks_make_room_for_new_ones() -> None:
    scanner, _ = _scanner(capture(packet()), cooldown_seconds=0.0)
    first = scanner.scan().printers[0][0]
    for _ in range(lan_scan.MAX_PICKS):
        scanner.scan()
    assert scanner.pick(first) is None
    assert len(scanner._picks) == lan_scan.MAX_PICKS


def test_a_scan_after_a_scan_waits_for_the_cooldown() -> None:
    clock = Clock()
    scanner, calls = _scanner(capture(status="none"), clock=clock)
    assert scanner.scan().status == "none"
    clock.now += 4
    again = scanner.scan()
    assert again.status == lan_scan.COOLDOWN and again.wait_seconds == 6 and len(calls) == 1
    clock.now += 6
    assert scanner.scan().status == "none" and len(calls) == 2


def test_a_diagnostics_capture_makes_the_scan_busy_without_a_cooldown() -> None:
    scanner, calls = _scanner(capture(status="busy"), capture(status="none"))
    assert scanner.scan().status == lan_scan.BUSY
    assert scanner.scan().status == "none" and len(calls) == 2


def test_only_one_scan_runs_at_a_time() -> None:
    started, release = threading.Event(), threading.Event()

    def slow(wanted):
        started.set()
        release.wait(5)
        return capture(status="none")

    scanner = PrinterScanner(capture=slow)
    worker = threading.Thread(target=scanner.scan, daemon=True)
    worker.start()
    assert started.wait(5)
    assert scanner.scan().status == lan_scan.BUSY
    release.set()
    worker.join(5)
    assert not worker.is_alive()


def test_unavailable_port_is_passed_on() -> None:
    scanner, _ = _scanner(capture(status="unavailable", error="EACCES"))
    result = scanner.scan()
    assert (result.status, result.error, result.printers) == ("unavailable", "EACCES", ())


def test_a_failing_capture_does_not_leave_the_scanner_busy() -> None:
    clock = Clock()

    def broken(wanted):
        raise RuntimeError("boom")

    scanner = PrinterScanner(capture=broken, clock=clock)
    with pytest.raises(RuntimeError):
        scanner.scan()
    clock.now += lan_scan.COOLDOWN_SECONDS
    with pytest.raises(RuntimeError):
        scanner.scan()


def test_default_capture_is_looked_up_at_call_time() -> None:
    result = PrinterScanner().scan()  # conftest blocks UDP 2021 with EACCES
    assert (result.status, result.error) == ("unavailable", "EACCES")
