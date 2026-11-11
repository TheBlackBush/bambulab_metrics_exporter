"""H3C (tool changer) and AMS 3H support: identity, rack slots and AMS zones."""
from __future__ import annotations

import pytest

from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import (
    PrinterSnapshot,
    normalize_model_hint,
    parse_ams_zones,
)


def _series(metrics: ExporterMetrics, name: str) -> list[dict[str, str]]:
    return [s.labels for m in metrics.registry.collect() for s in m.samples if s.name == name]


@pytest.mark.parametrize(
    "raw, serial",
    [
        ({"info": {"module": [{"name": "ota", "product_name": "Bambu Lab H3C"}]}}, ""),
        ({"print": {"sn": "32XFAKE00000001"}}, ""),
        ({"print": {}}, "32XFAKE00000001"),
    ],
)
def test_h3c_identity_sources(raw: dict, serial: str) -> None:
    snap = PrinterSnapshot(connected=True, raw=raw, configured_serial=serial)
    assert snap.model_name == "H3C"


@pytest.mark.parametrize("hint", ["N10", "N10-V2", "H3C", "Bambu Lab H3C", "h3c"])
def test_h3c_model_hints(hint: str) -> None:
    assert normalize_model_hint(hint) == "H3C"


def _ams_3h_unit(**extra: object) -> dict[str, object]:
    return {"id": "32", "tray": [{"id": str(i)} for i in range(9)], **extra}


def test_ams_3h_detected_from_module_name_without_info() -> None:
    raw = {
        "print": {"ams": {"ams": [_ams_3h_unit()], "tray_exist_bits": "10000000"}},
        "info": {"module": [{"name": "n10a", "product_name": "AMS 3H"}]},
    }
    snap = PrinterSnapshot(connected=True, raw=raw)
    assert [u["ams_model"] for u in snap.ams_units_with_model] == ["ams_3h"]
    present = snap.ams_slots_present
    assert present[("32", "0")] == 1.0
    assert present[("32", "8")] == 0.0
    assert len(present) == 9


def test_parse_ams_zones_tolerates_malformed_entries() -> None:
    unit = {
        "zone_info": [
            "bad",
            {"zone_id": "x"},
            {"zone_id": 9},
            {
                "zone_id": 0,
                "zone_slots": [1, "2", "x", 2, 99],
                "humidity": "7",
                "humidity_raw": "0",
                "temp": "warm",
                "info": "zz",
                "dry_time": 30,
                "dry_setting": {"dry_temperature": 55, "dry_duration": 8},
                "dry_sf_reason": [6, True, "1"],
            },
            {"zone_id": 0, "zone_slots": [3]},
        ]
    }
    zones = parse_ams_zones(unit)
    assert len(zones) == 1
    zone = zones[0]
    assert zone["slots"] == [1, 2]
    assert zone["dryable"] is True
    assert zone["humidity_index"] is None and zone["humidity_percent"] is None
    assert zone["temperature"] is None and zone["info"] is None
    assert zone["drying"] == {
        "remaining_seconds": 1800.0,
        "target_temperature": 55.0,
        "duration_seconds": 28800.0,
    }
    assert zone["blocked_reasons"] == ["drying_in_progress"]
    assert parse_ams_zones({"zone_info": "nope"}) == []
    assert parse_ams_zones({}) == []


def test_ams_zone_series_are_cleared_when_zones_disappear() -> None:
    zone = {
        "zone_id": 0, "zone_slots": [5, 7], "humidity": "4", "humidity_raw": "27",
        "temp": "16.7", "info": "240002006", "dry_time": 0,
        "dry_sf_reason": [1],
    }
    raw = {"print": {"ams": {"ams": [_ams_3h_unit(info="240002006", zone_info=[zone])]}}}
    metrics = ExporterMetrics(printer_name="t", serial="s")
    metrics.update_from_snapshot(PrinterSnapshot(connected=True, raw=raw))
    assert _series(metrics, "bambulab_ams_zone_humidity")[0]["zone_id"] == "0"
    reasons = _series(metrics, "bambulab_ams_zone_drying_blocked_reason_info")
    assert [r["reason"] for r in reasons] == ["insufficient_power"]
    raw["print"]["ams"]["ams"] = [_ams_3h_unit(info="240002006")]
    metrics.update_from_snapshot(PrinterSnapshot(connected=True, raw=raw))
    for name in (
        "bambulab_ams_zone_slot_info",
        "bambulab_ams_zone_humidity",
        "bambulab_ams_zone_humidity_index",
        "bambulab_ams_zone_temperature_celsius",
        "bambulab_ams_zone_heater_state_info",
        "bambulab_ams_zone_drying_remaining_seconds",
        "bambulab_ams_zone_drying_blocked_reason_info",
    ):
        assert _series(metrics, name) == [], name


def test_unknown_model_reports_extra_rack_slots_when_docked() -> None:
    # No model known: 6 slots by default, more when a higher slot is docked.
    six = PrinterSnapshot(
        connected=True, raw={"print": {"device": {"nozzle": {"exist": 1 << 16, "tar_id": 255}}}}
    )
    assert [e["slot_id"] for e in six.hotend_rack_slot_entries] == [str(i) for i in range(16, 22)]
    nine = PrinterSnapshot(
        connected=True, raw={"print": {"device": {"nozzle": {"exist": 1 << 23, "tar_id": 255}}}}
    )
    ids = [e["slot_id"] for e in nine.hotend_rack_slot_entries]
    assert ids == [str(i) for i in range(16, 24)]


def test_negative_rack_exist_does_not_add_slots() -> None:
    snap = PrinterSnapshot(
        connected=True, raw={"print": {"device": {"nozzle": {"exist": -1, "tar_id": 255}}}}
    )
    assert len(snap.hotend_rack_slot_entries) == 6


def test_ams_3h_zero_padded_id_still_uses_3h_bits() -> None:
    raw = {"print": {"ams": {"ams": [_ams_3h_unit(id="032", info="6")], "tray_exist_bits": "10000000"}}}
    present = PrinterSnapshot(connected=True, raw=raw).ams_slots_present
    assert present[("32", "0")] == 1.0
