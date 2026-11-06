"""Tests for the multi-printer fleet."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.fleet import MergedCollector, PrinterFleet
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot
from bambulab_metrics_exporter.printers import PrinterConfig, PrinterStore

A = PrinterConfig(serial="FAKE00TEST000001", transport="local_mqtt", host="192.0.2.1",
                  access_code="fake-access-code", name="Alpha")
B = PrinterConfig(serial="FAKE00TEST000002", transport="local_mqtt", host="192.0.2.2",
                  access_code="fake-access-code", name="Beta")
C1 = PrinterConfig(serial="FAKE00TEST000003", transport="cloud_mqtt", name="Cloud One")
C2 = PrinterConfig(serial="FAKE00TEST000004", transport="cloud_mqtt", name="Cloud Two")


class _Client:
    def __init__(self, settings: Settings) -> None:
        self.serial = settings.bambulab_serial
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        return PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 5}})


def _wait_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached in time")


def _base() -> Settings:
    return Settings(polling_interval_seconds=0.05, request_timeout_seconds=0.05)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "fake-development-key-never-use")
    for key in ("BAMBULAB_SERIAL", "BAMBULAB_HOST", "BAMBULAB_ACCESS_CODE", "BAMBULAB_TRANSPORT"):
        monkeypatch.delenv(key, raising=False)


def _fleet(validate=lambda s: None, configs=None) -> PrinterFleet:
    store = PrinterStore()
    if configs is not None:
        store.save(configs)
    return PrinterFleet(store, settings_factory=_base, validate=validate, client_factory=_Client)


def _running(fleet: PrinterFleet) -> None:
    _wait_until(lambda: all(p["state"] == "running" for p in fleet.printers_status()))


def test_merged_collector_single_registry_is_identical() -> None:
    source = ExporterMetrics(printer_name="x", serial="y")
    merged = CollectorRegistry(auto_describe=False)
    merged.register(MergedCollector(lambda: [source.registry]))
    assert generate_latest(merged) == generate_latest(source.registry)


def test_merged_collector_one_help_per_family() -> None:
    one, two = ExporterMetrics("a", "1"), ExporterMetrics("b", "2")
    one.printer_up.labels(printer_name="a", serial="1").set(1)
    two.printer_up.labels(printer_name="b", serial="2").set(0)
    merged = CollectorRegistry(auto_describe=False)
    merged.register(MergedCollector(lambda: [one.registry, two.registry]))
    text = generate_latest(merged).decode()
    assert text.count("# HELP bambulab_printer_up ") == 1
    assert text.count("# TYPE bambulab_printer_up ") == 1
    assert 'bambulab_printer_up{printer_name="a",serial="1"} 1.0' in text
    assert 'bambulab_printer_up{printer_name="b",serial="2"} 0.0' in text


def test_merged_collector_skips_a_failing_registry(caplog) -> None:
    class Broken:
        def collect(self):
            raise RuntimeError("boom")

    good = CollectorRegistry()
    Gauge("bambulab_x", "x", registry=good).set(1)
    merged = CollectorRegistry(auto_describe=False)
    merged.register(MergedCollector(lambda: [Broken(), good]))  # type: ignore[list-item]
    assert b"bambulab_x 1.0" in generate_latest(merged)


def test_runs_every_printer_and_merges_metrics() -> None:
    fleet = _fleet(configs=[A, B])
    fleet.start()
    try:
        _running(fleet)
        text = generate_latest(fleet.scrape_registry).decode()
        assert 'serial="FAKE00TEST000001"' in text
        assert 'serial="FAKE00TEST000002"' in text
        assert fleet.saved is True
    finally:
        fleet.stop()


def test_one_failing_printer_does_not_stop_the_others() -> None:
    def validate(settings: Settings) -> None:
        if settings.bambulab_serial == A.serial:
            raise RuntimeError("printer offline")

    fleet = _fleet(validate=validate, configs=[A, B])
    fleet.start()
    try:
        _wait_until(lambda: {p["state"] for p in fleet.printers_status()} == {"error", "running"})
        assert fleet.status()["state"] == "error"
        _wait_until(lambda: fleet.ready)
    finally:
        fleet.stop()


def test_update_only_touches_changed_printers() -> None:
    fleet = _fleet(configs=[A, B])
    fleet.start()
    try:
        _running(fleet)
        before = fleet._runtimes[A.printer_id]
        fleet.update([A, C1])
        assert fleet._runtimes[A.printer_id] is before
        assert sorted(p["name"] for p in fleet.printers_status()) == ["Alpha", "Cloud One"]
        assert B.printer_id not in fleet._runtimes
        _wait_until(lambda: b"FAKE00TEST000002" not in generate_latest(fleet.scrape_registry))
    finally:
        fleet.stop()


def test_env_mode_runs_the_env_printer(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SERIAL", A.serial)
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.1")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "fake-access-code")
    fleet = _fleet()
    fleet.start()
    try:
        _running(fleet)
        assert fleet.saved is False
        configs = fleet.configs()
        assert [c.serial for c in configs] == [A.serial]
        assert configs[0].env_printer is True
        assert configs[0].access_code == "fake-access-code"
    finally:
        fleet.stop()


def test_saving_the_env_printer_keeps_its_exposition(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SERIAL", A.serial)
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.1")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "fake-access-code")
    fleet = _fleet()
    fleet.start()
    try:
        _running(fleet)
        _wait_until(lambda: fleet.ready)
        before = fleet.metrics._base_labels
        saved = fleet.configs()
        fleet.update(saved)
        _running(fleet)
        assert len(fleet._runtimes) == 1
        assert "env" not in fleet._runtimes
        assert fleet.configs() == saved
        assert len(fleet.printers_status()) == 1
        assert fleet.metrics._base_labels == before
        _wait_until(
            lambda: generate_latest(fleet.scrape_registry).decode().count("bambulab_printer_up{")
            == 1
        )
    finally:
        fleet.stop()


def test_update_after_stop_starts_nothing() -> None:
    fleet = _fleet(configs=[A, B])
    fleet.start()
    _running(fleet)
    fleet.stop()
    fleet.update([A, C1])
    fleet.reset_to_env()
    assert all(rt._thread is None or not rt._thread.is_alive() for rt in fleet._runtimes.values())
    fleet.stop()


def test_reset_returns_to_env_mode(monkeypatch, tmp_path: Path) -> None:
    # An env runtime without a serial is hidden from the list, so give it one.
    monkeypatch.setenv("BAMBULAB_SERIAL", A.serial)
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.1")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "fake-access-code")
    fleet = _fleet(configs=[A, B])
    fleet.start()
    try:
        _running(fleet)
        fleet.reset_to_env()
        assert fleet.saved is False
        assert not (tmp_path / "printers.enc.json").exists()
        assert len(fleet.printers_status()) == 1
    finally:
        fleet.stop()


def test_empty_fleet_serves_setup_state() -> None:
    fleet = _fleet(configs=[])
    fleet.start()
    try:
        assert fleet.status()["state"] == "setup_required"
        assert fleet.ready is False
        assert fleet.printers_status() == []
        generate_latest(fleet.scrape_registry)
        assert fleet.metrics is not None and fleet.settings is not None
    finally:
        fleet.stop()


def test_empty_fleet_settings_come_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_ALLOWED_HOSTS", "exporter.example.invalid")
    fleet = PrinterFleet(PrinterStore(), validate=lambda _s: None)
    fleet.update([])
    assert fleet.settings.auth_allowed_hosts == "exporter.example.invalid"
    assert fleet.settings.bambulab_config_dir == str(tmp_path)


def test_empty_fleet_settings_tolerate_invalid_env(monkeypatch) -> None:
    fleet = PrinterFleet(PrinterStore(), validate=lambda _s: None)
    fleet.update([])
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "carrier_pigeon")
    assert fleet.settings is not None
    assert fleet.status()["state"] == "setup_required"


def test_concurrent_cloud_validation_reuses_fresh_token(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "stale")
    refreshes: list[str] = []
    gate = threading.Lock()

    def validate(settings: Settings) -> None:
        import os

        assert gate.acquire(blocking=False), "cloud validation must be serialized"
        try:
            if settings.bambulab_cloud_access_token == "stale":
                refreshes.append(settings.bambulab_serial)
                time.sleep(0.02)
                os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] = "fresh"
                settings.bambulab_cloud_access_token = "fresh"
        finally:
            gate.release()

    fleet = _fleet(validate=validate, configs=[C1, C2])
    fleet.start()
    try:
        _running(fleet)
        assert len(refreshes) == 1
    finally:
        fleet.stop()


def test_lan_validation_is_not_serialized() -> None:
    entered = threading.Barrier(2, timeout=2)

    def validate(settings: Settings) -> None:
        entered.wait()

    fleet = _fleet(validate=validate, configs=[A, B])
    fleet.start()
    try:
        _running(fleet)
    finally:
        fleet.stop()


def test_status_keeps_single_printer_fields() -> None:
    fleet = _fleet(configs=[A])
    fleet.start()
    try:
        _running(fleet)
        assert fleet.status() == {"state": "running", "message": "", "transport": "local_mqtt"}
    finally:
        fleet.stop()
