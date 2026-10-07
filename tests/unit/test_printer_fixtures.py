"""Per-model checks against sanitized real payloads (tests/fixtures/printers)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "printers"

# Serial prefix per model, so detection runs exactly like a configured printer.
_PREFIX = {
    "A1": "039", "A1MINI": "030", "A2L": "26A", "P1P": "01S", "P1S": "01P", "P2S": "22E",
    "X1": "00W", "X1C": "00M", "X1E": "03W", "X2D": "20P", "H2D": "094", "H2DPRO": "239",
    "H2S": "093", "H2C": "31B",
}


def _load(name: str) -> tuple[dict, PrinterSnapshot, ExporterMetrics]:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    raw = {**fixture["pushall"], **(fixture.get("get_version") or {})}
    snap = PrinterSnapshot(
        connected=True,
        raw=raw,
        configured_serial=_PREFIX[fixture["model"]] + "FIXTURE000001",
    )
    metrics = ExporterMetrics(printer_name="fixture", serial="FIXTURE")
    metrics.update_from_snapshot(snap)
    return fixture, snap, metrics


def _samples(metrics: ExporterMetrics, name: str) -> list[tuple[dict[str, str], float]]:
    return [
        ({k: v for k, v in s.labels.items() if k not in ("printer_name", "serial")}, s.value)
        for metric in metrics.registry.collect()
        for s in metric.samples
        if s.name == name
    ]


def _value(metrics: ExporterMetrics, name: str) -> float:
    found = _samples(metrics, name)
    assert len(found) == 1, (name, found)
    return found[0][1]


ALL = sorted(p.stem for p in FIXTURES.glob("*.json"))


@pytest.mark.parametrize("name", ALL)
def test_fixture_detects_model_and_exports_sane_values(name: str) -> None:
    fixture, snap, metrics = _load(name)
    assert snap.model_name == fixture["model"]

    for metric in metrics.registry.collect():
        for sample in metric.samples:
            if math.isnan(sample.value):
                continue
            if "temperature_celsius" in sample.name:
                assert -40 <= sample.value <= 500, (sample.name, sample.labels, sample.value)
            if sample.name == "bambulab_ams_slot_remaining_percent":
                assert 0 <= sample.value <= 100, (sample.labels, sample.value)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("h2s", 60.0),  # packed ctc value 3932220 = 60 °C current / 60 °C target
        ("x1c_fw0112_ams1", 29.0),
        ("a1", None),  # no chamber sensor: placeholder 5 °C is not exported
        ("a2l", None),
        ("p1p_no_ams", None),
    ],
)
def test_chamber_temperature(name: str, expected: float | None) -> None:
    _, _, metrics = _load(name)
    value = _value(metrics, "bambulab_chamber_temperature_celsius")
    assert math.isnan(value) if expected is None else value == expected


def test_secondary_aux_fan_reads_airduct_state() -> None:
    _, _, metrics = _load("x2d")
    assert _value(metrics, "bambulab_fan_secondary_aux_speed_percent") == 10.0


def _active_slots(metrics: ExporterMetrics) -> list[tuple[str, str]]:
    return sorted(
        (labels["ams_id"], labels["slot_id"])
        for labels, value in _samples(metrics, "bambulab_ams_slot_active")
        if value == 1.0
    )


@pytest.mark.parametrize(
    ("name", "active", "external"),
    [
        ("h2d", [("1", "3")], 0.0),  # snow 0x0103; tray_now only holds the local slot 3
        ("h2d_external_spool", [], 1.0),  # snow 0xFF00 on the active extruder
        ("x2d", [("0", "1")], 0.0),  # active extruder 1, snow 0x0001
        ("x1_legacy_firmware", [("128", "0")], 0.0),  # tray_now 128 is an AMS HT unit
        ("p1p_no_ams", [], 1.0),  # tray_now 254
        ("x1c_fw0112_ams1", [], 0.0),  # nothing loaded
    ],
)
def test_active_slot_and_external_spool(name: str, active: list, external: float) -> None:
    _, _, metrics = _load(name)
    assert _active_slots(metrics) == active
    assert _value(metrics, "bambulab_external_spool_active") == external


def test_unknown_remaining_is_nan_not_negative() -> None:
    _, _, metrics = _load("h2d_external_spool")
    values = [v for _, v in _samples(metrics, "bambulab_ams_slot_remaining_percent")]
    assert values and any(math.isnan(v) for v in values)
    assert all(math.isnan(v) or v >= 0 for v in values)


def test_ams_info_strings_are_hex() -> None:
    """AMS 2 Pro info "2003" / AMS HT "2004": dry status nibble is 0, not 13."""
    _, _, metrics = _load("h2d")
    states = {labels["state"] for labels, _ in _samples(metrics, "bambulab_ams_heater_state_info")}
    assert states and states <= {"0", "1", "2", "3", "4", "5", "6", "7"}


def test_drying_metrics_only_for_units_with_a_dryer() -> None:
    _, _, metrics = _load("x1c_multi_ams")
    models = {
        labels["ams_model"] for labels, _ in _samples(metrics, "bambulab_ams_heater_state_info")
    }
    assert models and models <= {"ams_2_pro", "ams_ht"}


@pytest.mark.parametrize("name", ["a1", "a2l"])
def test_ams_lite_has_no_sensor_metrics(name: str) -> None:
    _, _, metrics = _load(name)
    assert _samples(metrics, "bambulab_ams_unit_temperature_celsius") == []
    assert _samples(metrics, "bambulab_ams_unit_humidity_index") == []


@pytest.mark.parametrize(("name", "model"), [("a1", "ams_lite"), ("x1_legacy_firmware", "ams_ht")])
def test_ams_model_from_get_version_modules(name: str, model: str) -> None:
    _, _, metrics = _load(name)
    assert model in {labels["ams_model"] for labels, _ in _samples(metrics, "bambulab_ams_unit_info")}


@pytest.mark.parametrize("name", ["a1", "a2l", "p1p_no_ams"])
def test_no_door_value_on_models_without_sensor(name: str) -> None:
    _, _, metrics = _load(name)
    assert math.isnan(_value(metrics, "bambulab_door_open"))


@pytest.mark.parametrize("name", ["h2d", "x2d", "x1c_fw0112_ams1"])
def test_door_reported_on_models_with_sensor(name: str) -> None:
    _, _, metrics = _load(name)
    assert _value(metrics, "bambulab_door_open") in (0.0, 1.0)


def test_camera_recording_follows_camera_setting() -> None:
    """Verified on the maintainer's X1C: ipcam_record enable while home_flag bit 5 is 0."""
    _, _, metrics = _load("x1c_fw0112_ams1")
    assert _value(metrics, "bambulab_camera_recording") == 1.0


def test_external_spool_info_omits_empty_virtual_slots() -> None:
    _, _, metrics = _load("h2c")
    for labels, _ in _samples(metrics, "bambulab_external_spool_info"):
        assert labels["tray_type"] != "unknown" or labels["tray_info_idx"] != "unknown"


@pytest.mark.parametrize("name", ["a1", "p1p_no_ams"])
def test_nozzle_info_from_top_level_fields(name: str) -> None:
    _, _, metrics = _load(name)
    nozzles = _samples(metrics, "bambulab_active_nozzle_info")
    assert len(nozzles) == 1 and nozzles[0][0]["nozzle_type"]


def test_h2c_with_legacy_h2d_prefix_is_detected_as_h2c() -> None:
    fixture = json.loads((FIXTURES / "h2c.json").read_text(encoding="utf-8"))
    raw = {**fixture["pushall"]}  # no get_version product name
    snap = PrinterSnapshot(connected=True, raw=raw, configured_serial="094FIXTURE000001")
    assert snap.model_name == "H2C"
    plain_h2d = PrinterSnapshot(connected=True, raw={"print": {}}, configured_serial="094FIXTURE000001")
    assert plain_h2d.model_name == "H2D"
