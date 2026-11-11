"""Diagnostic report: sanitizer, report content, log buffer, /diagnostics page and report."""
from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bambulab_metrics_exporter import diagnostics as diag
from bambulab_metrics_exporter.api import build_app
from bambulab_metrics_exporter.collector import PollingCollector
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.diagnostics import (
    PrinterDiagnostics,
    RecentLogHandler,
    build_report,
    sanitize,
    sanitize_payload,
    scrub_text,
)
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot

SERIAL = "01P00FAKE123456"
HOST = "printer-garage.example.invalid"
NAME = "Garage Workhorse"
SECRETS = [
    "fake-access-code-77", "fake-access-token-abcdef", "fake-refresh-token-abcdef",
    "fake-user-98765", "fake-secret-key-never-use", "owner@example.invalid",
]


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = dict(
        bambulab_serial=SERIAL, bambulab_host=HOST, printer_name_label=NAME,
        bambulab_printer_name=NAME, bambulab_access_code=SECRETS[0],
        bambulab_cloud_access_token=SECRETS[1], bambulab_cloud_refresh_token=SECRETS[2],
        bambulab_cloud_user_id=SECRETS[3], bambulab_secret_key=SECRETS[4],
    )
    base.update(kw)
    return Settings(**base)


def _raw() -> dict[str, Any]:
    return {
        "print": {
            "sn": SERIAL,
            "dev_name": NAME,
            "subtask_name": "secret_project_v3",
            "gcode_file": "/sdcard/secret_project_v3.gcode.3mf",
            "file": "secret_project_v3.3mf",
            "task_id": "123456789",
            "net": {"info": [{"ip": 1694607552, "mask": 16777215}]},
            "ipcam": {"rtsp_url": "rtsps://192.168.1.50/streaming/live/1"},
            "wifi_signal": "-52dBm",
            "nozzle_temper": 24.5,
            "bed_temper": float("nan"),
            "note": f"report topic device/{SERIAL}/report from {HOST}",
            "ams": {"ams": [{"id": "0", "humidity": "4", "tray": [
                {"id": "0", "tag_uid": "A1B2C3D4E5F60708", "tray_uuid": "F" * 32},
            ]}]},
            "upgrade_state": {"sn": SERIAL, "ahb_new_version_number": ""},
        },
        "info": {"module": [
            {"name": "ota", "product_name": "Bambu Lab P1S", "sw_ver": "01.08.00.00",
             "hw_ver": "OTA", "sn": SERIAL},
            {"name": "ams/0", "product_name": "AMS", "sw_ver": "00.00.06.49",
             "hw_ver": "AMS08", "sn": "006A0FAKE000001"},
        ]},
    }


def _item(snapshot: PrinterSnapshot | None = None, **kw: Any) -> PrinterDiagnostics:
    settings = _settings(**kw)
    metrics = ExporterMetrics(printer_name=NAME, serial=SERIAL)
    if snapshot is not None:
        metrics.update_from_snapshot(snapshot)
    return PrinterDiagnostics(
        settings=settings, state="running",
        message=f"Connection to {HOST} at 192.168.1.50 failed for {SERIAL}",
        ready=snapshot is not None, snapshot=snapshot, metrics=metrics,
    )


# -- sanitizer ----------------------------------------------------------------------


def test_sanitize_payload_replaces_identifiers_and_keeps_telemetry() -> None:
    out = sanitize_payload(_raw(), [SERIAL], [NAME, HOST])
    p = out["print"]
    assert p["sn"] == "01PFIXTURE00000"  # model prefix kept
    assert p["dev_name"] == "Fixture Printer"
    assert p["subtask_name"] == "fixture"
    assert p["gcode_file"] == "fixture.gcode.3mf"
    assert p["file"] == "fixture.3mf"
    assert p["task_id"] == "0"
    assert p["net"]["info"][0]["ip"] != 1694607552
    assert p["ipcam"]["rtsp_url"] == "rtsps://192.0.2.1/streaming/live/1"
    assert p["nozzle_temper"] == 24.5 and p["wifi_signal"] == "-52dBm"
    assert p["bed_temper"] is None  # NaN is not valid JSON
    assert p["note"] == "report topic device/01PFIXTURE00000/report from [redacted]"
    tray = p["ams"]["ams"][0]["tray"][0]
    assert tray["tag_uid"] == "0000000000000000" and set(tray["tray_uuid"]) == {"0"}
    modules = out["info"]["module"]
    assert modules[0]["sw_ver"] == "01.08.00.00"  # firmware versions are not addresses
    assert modules[1]["sn"] == "006FIXTURE00000"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("at 10.0.0.12:8883", "at 192.0.2.1:8883"),
        ("fw 01.12.00.00", "fw 01.12.00.00"),
        ("v6 fe80::1c2b:3cff:fe4d:5e6f here", "v6 2001:db8::1 here"),
        ("v6 2a02:1:2:3:4:5:6:7", "v6 2001:db8::1"),
        ("at 12:30:45", "at 12:30:45"),
        ("mac AA:BB:CC:DD:EE:FF", "mac 00:00:00:00:00:00"),
        ("mail me@home.example", "mail operator@example.invalid"),
    ],
)
def test_scrub_text(text: str, expected: str) -> None:
    assert scrub_text(text) == expected


def test_scrub_text_extras_are_case_insensitive_and_skip_short_values() -> None:
    assert scrub_text("garage WORKHORSE ok", extra=["Garage Workhorse"]) == "[redacted] ok"
    assert scrub_text("abc idle", extra=["abc"]) == "abc idle"


def test_credential_like_keys_are_blanked() -> None:
    out = sanitize_payload({"print": {"dev_access_code": "x1", "ipcam": {"token": "y2"}}})
    assert out == {"print": {"dev_access_code": "[redacted]", "ipcam": {"token": "[redacted]"}}}


def test_sanitize_fixture_form_wraps_a_bare_report() -> None:
    out = sanitize({"print": {"sn": SERIAL}})
    assert out == {"pushall": {"print": {"sn": "01PFIXTURE00000"}}, "get_version": {}}


# -- report -------------------------------------------------------------------------


def test_report_has_no_identifiers_or_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", SECRETS[5])
    logging.getLogger("bambulab_metrics_exporter.test").warning(
        "Probe %s with %s for %s via %s", HOST, SECRETS[0], SERIAL, SECRETS[5]
    )
    diag.install_log_handler()
    logging.getLogger("bambulab_metrics_exporter.test").warning(
        "Probe %s with %s for %s via %s", HOST, SECRETS[0], SERIAL, SECRETS[5]
    )
    snap = PrinterSnapshot(connected=True, raw=_raw(), configured_serial=SERIAL)
    report = build_report([_item(snap)], now=1_800_000_000.0)
    text = json.dumps(report, allow_nan=False)
    for needle in [SERIAL, HOST, NAME, "secret_project", "192.168.1.50", "1694607552",
                   "A1B2C3D4E5F60708", *SECRETS]:
        assert needle.lower() not in text.lower(), needle
    printer = report["printers"][0]
    assert printer["serial"] == "01PFIXTURE00000"
    assert printer["model"] == "P1S"
    assert printer["capabilities"]["chamber_heater"] is False
    assert printer["message"] == "Connection to [redacted] at 192.0.2.1 failed for 01PFIXTURE00000"
    assert printer["settings"]["request_pushall"] is True
    assert any("Probe [redacted]" in line for line in report["logs"])
    assert report["format"] == 1 and report["generated_at"] == "2027-01-15T08:00:00Z"


def test_report_lists_empty_metric_families() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"nozzle_temper": 30}})
    printer = build_report([_item(snap)])["printers"][0]
    assert "bambulab_chamber_temperature_celsius" in printer["empty_metrics"]
    assert "bambulab_nozzle_temperature_celsius" not in printer["empty_metrics"]


def test_report_without_data_yet_still_names_the_model_from_the_serial() -> None:
    printer = build_report([_item(None)])["printers"][0]
    assert printer["payload"] is None and printer["last_success_age_seconds"] is None
    assert printer["model"] == "P1S" and printer["model_source"] == "serial_or_setting"
    assert printer["empty_metrics"] is None  # no data, not "every metric missing"


def test_report_with_data_uses_the_printer_data() -> None:
    snap = PrinterSnapshot(connected=True, raw=_raw(), configured_serial=SERIAL)
    printer = build_report([_item(snap)])["printers"][0]
    assert printer["model_source"] == "printer_data"
    assert isinstance(printer["empty_metrics"], list)


@pytest.mark.parametrize(
    ("serial", "hint", "model", "source"),
    [
        ("", "", None, "none"),
        ("ZZZFAKE00000001", "", None, "serial_or_setting"),  # unknown prefix
        ("", "X1C", "X1C", "serial_or_setting"),  # configured or cloud model hint
        ("094FAKE00000001", "", "H2D", "serial_or_setting"),
    ],
)
def test_detect_model_without_printer_data(serial: str, hint: str, model: str | None,
                                           source: str) -> None:
    settings = Settings(bambulab_serial=serial, bambulab_printer_model=hint)
    assert diag.detect_model(settings, None) == (model, source)
    empty = PrinterSnapshot(connected=False, raw={})
    assert diag.detect_model(settings, empty) == (model, source)


# -- log buffer ---------------------------------------------------------------------


def test_recent_log_handler_keeps_the_last_lines_and_exception_names() -> None:
    handler = RecentLogHandler(capacity=2)
    log = logging.getLogger("bambulab_metrics_exporter.buffer_test")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        log.info("one")
        log.info("two")
        try:
            raise ValueError("payload text must not be kept")
        except ValueError:
            log.exception("three")
    finally:
        log.removeHandler(handler)
    lines = handler.lines()
    assert len(lines) == 2
    assert lines[0].endswith("two")
    assert lines[1].endswith("three [ValueError]")
    assert "payload text" not in "".join(lines)


def test_install_log_handler_is_idempotent() -> None:
    diag.install_log_handler()
    diag.install_log_handler()
    handlers = logging.getLogger("bambulab_metrics_exporter").handlers
    assert sum(isinstance(h, RecentLogHandler) for h in handlers) == 1


# -- collector, runtime and HTTP ----------------------------------------------------


class _Client:
    def __init__(self, snap: PrinterSnapshot) -> None:
        self.snap = snap

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        return self.snap


def test_collector_keeps_the_last_snapshot() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 5}})
    collector = PollingCollector(
        _Client(snap), ExporterMetrics(printer_name="t", serial="s"),  # type: ignore[arg-type]
        Settings(polling_interval_seconds=60),
    )
    assert collector.last_snapshot is None
    collector.start()
    try:
        for _ in range(200):
            if collector.last_snapshot is not None:
                break
            import time

            time.sleep(0.01)
    finally:
        collector.stop()
    assert collector.last_snapshot is snap


class _Runtime:
    def __init__(self, item: PrinterDiagnostics) -> None:
        self.settings = item.settings
        self.metrics = item.metrics
        self.ready = item.ready
        self._item = item

    def status(self) -> dict[str, str]:
        return {"state": "running", "message": "", "transport": "local_mqtt"}

    def reconfigure(self) -> None: ...

    def diagnostics_inputs(self) -> list[PrinterDiagnostics]:
        return [self._item]


def test_report_route_returns_a_sanitized_report() -> None:
    snap = PrinterSnapshot(connected=True, raw=_raw(), configured_serial=SERIAL)
    client = TestClient(build_app(runtime=_Runtime(_item(snap))))
    response = client.get("/diagnostics/report")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "content-disposition" not in response.headers  # shown on the page
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.json()["printers"][0]["model"] == "P1S"
    assert SERIAL not in response.text and HOST not in response.text


def test_report_route_download_sends_a_file() -> None:
    client = TestClient(build_app(runtime=_Runtime(_item(None))))
    response = client.get("/diagnostics/report?download=1")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="bambulab-exporter-diagnostics-')
    assert disposition.endswith('.json"')


@pytest.mark.parametrize("path", ["/diagnostics", "/diagnostics/report"])
def test_diagnostics_routes_check_the_host(path: str) -> None:
    client = TestClient(build_app(runtime=_Runtime(_item(None))))
    assert client.get(path, headers={"Host": "evil.example:9109"}).status_code == 403


def test_report_route_without_runtime_inputs() -> None:
    runtime = _Runtime(_item(None))
    runtime.diagnostics_inputs = None  # type: ignore[assignment,method-assign]
    report = TestClient(build_app(runtime=runtime)).get("/diagnostics/report").json()
    assert report["printers"] == []


def test_diagnostics_page_runs_and_shares_the_report() -> None:
    client = TestClient(build_app(runtime=_Runtime(_item(None))))
    response = client.get("/diagnostics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    page = response.text
    assert "{{" not in page
    for element in ('id="run"', 'id="copy"', 'id="download"', 'id="issue"', 'id="report"'):
        assert element in page
    assert 'fetch("/diagnostics/report"' in page
    # The issue link carries title, summary and fields, and the report when it fits.
    for snippet in ('["title", issueTitle(', '["description", issueDescription(',
                    '["report", reportField]', "maxIssueUrl", "download();"):
        assert snippet in page
    assert "issues/new?template=diagnostic.yml" in page and "/wiki/Diagnostic-Report" in page
    assert 'href="/diagnostics/report?download=1"' in page  # no-JavaScript fallback
    # Report text is put on the page as text, never parsed as HTML.
    assert "innerHTML" not in page


def test_status_and_auth_pages_link_the_diagnostics_page() -> None:
    client = TestClient(build_app(runtime=_Runtime(_item(None))))
    for path in ("/", "/auth"):
        page = client.get(path).text
        assert 'href="/diagnostics"' in page and "{{" not in page
    static = build_app(
        metrics=ExporterMetrics(printer_name="t", serial="s"),
        collector=type("C", (), {"ready": True})(),
    )
    assert "/diagnostics" not in TestClient(static).get("/").text
    assert TestClient(static).get("/diagnostics").status_code == 404


def test_unsupported_badge_only_for_unrecognized_printers() -> None:
    from bambulab_metrics_exporter.api import _printer_rows

    base = {"id": "abc", "name": "Shop", "serial": "ZZZ************", "transport": "local_mqtt",
            "state": "running", "message": ""}
    assert "Unsupported printer" in _printer_rows([{**base, "model": ""}])
    assert 'href="/diagnostics"' in _printer_rows([{**base, "model": ""}])
    assert "Unsupported printer" not in _printer_rows([{**base, "model": "H2D"}])
    assert "Unsupported printer" not in _printer_rows([base])  # older backends: no model key


def test_runtime_detected_model_and_fleet_status(monkeypatch: pytest.MonkeyPatch) -> None:
    from bambulab_metrics_exporter import runtime as rt
    from bambulab_metrics_exporter.fleet import PrinterFleet

    known = rt.ExporterRuntime(settings_factory=lambda: _settings())
    unknown = rt.ExporterRuntime(settings_factory=lambda: _settings(
        bambulab_serial="ZZZFAKE00000001"))
    assert known.detected_model() == "P1S"
    assert unknown.detected_model() is None

    class _Collector:
        last_snapshot = PrinterSnapshot(
            connected=True, raw={"info": {"module": [{"name": "ota",
                                                      "product_name": "Bambu Lab H2S"}]}},
        )

    unknown.collector = _Collector()  # type: ignore[assignment]
    assert unknown.detected_model() == "H2S"  # printer data wins over the serial
    unknown.collector = None

    class _Fleet:
        _lock = __import__("threading").Lock()
        _runtimes = {"a": known, "b": unknown}
        _configs: dict[str, Any] = {}

    rows = PrinterFleet.printers_status(_Fleet())  # type: ignore[arg-type]
    assert [r["model"] for r in rows] == ["P1S", ""]


def test_page_summary_shows_message_model_source_and_no_data() -> None:
    page = TestClient(build_app(runtime=_Runtime(_item(None)))).get("/diagnostics").text
    assert "no data yet" in page and "(from the serial)" in page
    assert "printer-message" in page and "not recognized" in page


def test_runtime_and_fleet_hand_over_their_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    from bambulab_metrics_exporter import runtime as rt

    runtime = rt.ExporterRuntime(settings_factory=lambda: _settings())
    items = runtime.diagnostics_inputs()
    assert len(items) == 1 and items[0].snapshot is None
    assert items[0].settings.bambulab_serial == SERIAL

    class _Fleet:
        _snapshot = staticmethod(lambda: [runtime, runtime])

    from bambulab_metrics_exporter.fleet import PrinterFleet

    assert len(PrinterFleet.diagnostics_inputs(_Fleet())) == 2  # type: ignore[arg-type]


def test_report_is_strict_json_even_with_nan_values() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"bed_temper": float("nan")}})
    report = build_report([_item(snap)])
    json.dumps(report, allow_nan=False)  # raises on NaN or infinity
    assert report["printers"][0]["payload"]["print"]["bed_temper"] is None


# -- review fixes -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("connection to 192.168.1.5.", "connection to 192.0.2.1."),
        ("printer_192.168.1.5 up", "printer_192.0.2.1 up"),
        ("v192.168.1.5", "v192.0.2.1"),
        ("bind 0.0.0.0:9109", "bind 0.0.0.0:9109"),
        ("version 1.2.3.4.5 kept", "version 1.2.3.4.5 kept"),
        ("a :: b", "a :: b"),
        ("x a:: y", "x a:: y"),
    ],
)
def test_scrub_text_review_cases(text: str, expected: str) -> None:
    assert scrub_text(text) == expected


def test_serial_keys_and_text_are_case_insensitive() -> None:
    out = sanitize_payload(
        {"SN": SERIAL, "nozzle_sn": "HX0FAKE00000099", "note": SERIAL.lower()}, [SERIAL]
    )
    assert out["SN"] == "01PFIXTURE00000"
    assert out["nozzle_sn"].startswith("HX0FIXTURE")
    assert SERIAL.lower() not in json.dumps(out).lower()


def test_name_keys_are_replaced() -> None:
    out = sanitize_payload({
        "ssid2": "HomeNet", "ssid_list": ["HomeNet", "Guest"], "hostname": "bambu-garage",
        "tar_name": "", "name": "ota", "file_name": "gift.3mf", "timelapse_path": "/tl/x",
        "oss_url": "https://bucket.example.invalid/a", "lan_task_id": "77", "img_id": "88",
        "project_name": "N2S",  # hardware code in the module list, kept
    })
    assert out == {
        "ssid2": "[redacted]", "ssid_list": ["[redacted]", "[redacted]"],
        "hostname": "[redacted]", "tar_name": "", "name": "ota", "file_name": "[redacted]",
        "timelapse_path": "[redacted]", "oss_url": "[redacted]", "lan_task_id": "0",
        "img_id": "0", "project_name": "N2S",
    }


def test_more_serial_keys_and_lists() -> None:
    out = sanitize_payload({"nozzle_serial": "HX0FAKE00000099", "SerialNumber": SERIAL,
                            "sn": [SERIAL, "006A0FAKE000001"]})
    assert out == {"nozzle_serial": "HX0FIXTURE00000", "SerialNumber": "01PFIXTURE00000",
                   "sn": ["01PFIXTURE00000", "006FIXTURE00000"]}


@pytest.mark.parametrize("name", ["A1 mini", "H2D Pro", "X1 Carbon", "Bambu Lab", "AMS 2 Pro"])
def test_printer_names_that_are_product_words_keep_product_names(name: str) -> None:
    raw = {"module": [{"product_name": f"Bambu Lab {name}"}, {"product_name": "AMS 2 Pro"}]}
    assert sanitize_payload(raw, extra=[name]) == raw


def test_model_detection_survives_sanitizing_every_fixture() -> None:
    """The report must keep what identifies a model: serial prefix, product names and the
    module hardware codes."""
    from pathlib import Path

    for path in sorted(Path("tests/fixtures/printers").glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        raw = {**fixture["pushall"], **(fixture.get("get_version") or {})}
        before = PrinterSnapshot(connected=True, raw=raw).printer_type
        after = PrinterSnapshot(connected=True, raw=sanitize_payload(raw)).printer_type
        assert after == before, path.name


def test_names_that_are_protocol_words_are_not_scrubbed() -> None:
    raw = {"gcode_state": "IDLE", "product_name": "Bambu Lab P1S", "nozzle_type": "stainless_steel"}
    out = sanitize_payload(raw, extra=["IDLE", "Bambu Lab P1S", "stainless"])
    assert out == raw


def test_long_text_is_cut_and_fast() -> None:
    import time

    started = time.monotonic()
    out = scrub_text("aa:" * 40000)
    assert time.monotonic() - started < 1.0
    assert out.endswith("characters cut]")


def test_pydantic_input_values_and_env_secrets_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "fake-env-code-31")
    item = _item(None, bambulab_access_code="")
    item = PrinterDiagnostics(
        settings=item.settings, state="setup_required",
        message="Invalid configuration: input_value='fake-typo-secret' and fake-env-code-31",
        ready=False, snapshot=None, metrics=item.metrics,
    )
    message = build_report([item])["printers"][0]["message"]
    assert "fake-typo-secret" not in message and "fake-env-code-31" not in message
