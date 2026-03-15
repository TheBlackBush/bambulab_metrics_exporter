"""Tests for bambulab_metrics_exporter.models."""
from __future__ import annotations

from bambulab_metrics_exporter import models
from bambulab_metrics_exporter.models import PrinterSnapshot


# ---------------------------------------------------------------------------
# Core field extraction
# ---------------------------------------------------------------------------

def test_snapshot_extracts_core_fields() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "gcode_state": "RUNNING",
                "mc_percent": 42,
                "mc_remaining_time": 11,
                "layer_num": 196,
                "total_layer_num": 240,
                "nozzle_temper": 215.5,
                "bed_temper": 60,
                "chamber_temper": 36,
                "mc_print_error_code": 0,
            }
        },
    )

    assert snap.gcode_state == "RUNNING"
    assert snap.progress_percent == 42.0
    assert snap.remaining_seconds == 660.0
    assert snap.layer_current == 196.0
    assert snap.layer_total == 240.0
    assert round(snap.layer_progress_percent or 0.0, 2) == 81.67
    assert snap.nozzle_temp == 215.5
    assert snap.bed_temp == 60.0
    assert snap.chamber_temp == 36.0


# ---------------------------------------------------------------------------
# Extended fields
# ---------------------------------------------------------------------------

def test_model_parsing_extended_fields() -> None:
    snap = PrinterSnapshot(
        connected=False,
        raw={
            "print": {
                "fan_gear": 10,
                "big_fan1_speed": "40",
                "big_fan2_speed": "55",
                "cooling_fan_speed": "60",
                "heatbreak_fan_speed": "70",
                "mc_stage": "2",
                "mc_print_sub_stage": 3,
                "print_real_action": "4",
                "print_gcode_action": "5",
                "mc_print_stage": "PRINTING",
                "nozzle_diameter": "0.4",
                "wifi_signal": "-62",
                "online": {"ahb": True, "ext": False},
                "ams_status": "1",
                "ams_rfid_status": 2,
                "queue_total": "3",
                "queue_est": "120",
                "queue_number": 4,
                "queue_sts": "5",
                "queue": "6",
                "spd_lvl": 3,
                "spd_mag": 124,
                "sn": "SN123456",
                "lights_report": [{"node": "chamber_light", "mode": "on"}],
                "xcam": {
                    "allow_skip_parts": True,
                    "buildplate_marker_detector": False,
                    "first_layer_inspector": True,
                    "print_halt": False,
                    "printing_monitor": True,
                    "spaghetti_detector": False,
                },
            }
        },
    )

    assert snap.fan_gear is not None
    assert snap.fan_gear_raw == 10.0
    assert snap.fan_big_1_percent == 40.0
    assert snap.fan_big_2_percent == 55.0
    assert snap.fan_cooling_percent == 60.0
    assert snap.fan_heatbreak_percent == 70.0
    assert snap.mc_stage == 2.0
    assert snap.mc_print_sub_stage == 3.0
    assert snap.print_real_action == 4.0
    assert snap.print_gcode_action == 5.0
    assert snap.mc_print_stage_name == "PRINTING"
    assert snap.nozzle_diameter == 0.4
    assert snap.wifi_signal == -62.0
    assert snap.online_ahb == 1.0
    assert snap.online_ext == 0.0
    assert snap.ams_status == 1.0
    assert snap.ams_rfid_status == 2.0
    assert snap.queue_total == 3.0
    assert snap.queue_est == 120.0
    assert snap.queue_number == 4.0
    assert snap.queue_status == 5.0
    assert snap.queue_position == 6.0
    assert snap.spd_lvl == 3.0
    assert snap.spd_mag == 124.0
    assert snap.sn == "SN123456"
    assert len(snap.lights_report) == 1
    assert snap.xcam_flags["allow_skip_parts"] == 1.0


# ---------------------------------------------------------------------------
# Chamber temp fallback, wifi_signal string, fail_reason
# ---------------------------------------------------------------------------

def test_model_chamber_temp_fallback_and_defaults() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"device": {"ctc": {"info": {"temp": 31}}}}},
    )
    assert snap.chamber_temp == 31.0
    assert snap.subtask_name is None


def test_model_wifi_signal_dbm_string() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"wifi_signal": "-42dBm"}})
    assert snap.wifi_signal == -42.0


def test_model_fail_reason_string() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"fail_reason": "filament runout"}})
    assert snap.fail_reason == "filament runout"


# ---------------------------------------------------------------------------
# Model name discovery
# ---------------------------------------------------------------------------

def test_model_name_discovery_paths() -> None:
    snap_p1s = PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 3}}})
    assert snap_p1s.model_name == "P1S"

    snap_fallback = PrinterSnapshot(connected=True, raw={"print": {"model_id": "X1C"}})
    assert snap_fallback.model_name == "X1C"

    snap_unknown = PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 99}}})
    assert snap_unknown.model_name is None


def test_printer_type_detection_from_module_metadata() -> None:
    by_product = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "ota", "product_name": "Bambu Lab H2D"}]},
    )
    assert by_product.printer_type == "H2D"

    by_hw_project = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "esp32", "hw_ver": "AP04", "project_name": "C12"}]},
    )
    assert by_hw_project.printer_type == "P1S"


# ---------------------------------------------------------------------------
# Parsing helpers (_to_float, _to_int)
# ---------------------------------------------------------------------------

def test_parsing_helpers() -> None:
    assert models._to_float("  ") is None
    assert models._to_int(True) == 1
    assert models._to_int(1.5) == 1
    assert models._to_int("  ") is None
    assert models._to_int("not-int") is None


# ---------------------------------------------------------------------------
# fan_gear edge cases
# ---------------------------------------------------------------------------

def test_model_fan_gear_gear_scale() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 15}})
    assert snap.fan_gear == 100.0  # (15/15)*100


def test_model_fan_gear_above_15() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 20.0}})
    assert snap.fan_gear == 20.0


def test_model_fan_gear_high_passthrough() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 50}})
    assert snap.fan_gear == 50.0


# ---------------------------------------------------------------------------
# layer_progress_percent edge case
# ---------------------------------------------------------------------------

def test_model_layer_progress_percent_zero_total() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"total_layer_num": 0}})
    assert snap.layer_progress_percent is None


# ---------------------------------------------------------------------------
# online field edge cases
# ---------------------------------------------------------------------------

def test_model_online_not_dict() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"online": "not-a-dict"}})
    assert snap.online_ahb is None


def test_model_online_non_bool() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"online": {"ahb": "not-bool"}}})
    assert snap.online_ahb is None


# ---------------------------------------------------------------------------
# AMS field edge cases
# ---------------------------------------------------------------------------

def test_model_ams_not_dict() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": "not-a-dict"}})
    assert snap.ams_tray_now is None
    assert snap.ams_units == []


def test_model_ams_tray_now_string() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "255"}}})
    assert snap.ams_tray_now == "255"


def test_model_ams_tray_now_from_short_form() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "1"}}})
    assert snap.ams_tray_now == "1"


def test_model_ams_units_name() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": {"ams": [{"id": "0", "name": "AMS1"}]}}})
    assert snap.ams_units[0]["name"] == "AMS1"


# ---------------------------------------------------------------------------
# subtask_name edge cases
# ---------------------------------------------------------------------------

def test_model_subtask_name_strip() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"subtask_name": "  test.gcode  "}})
    assert snap.subtask_name == "test.gcode"


def test_model_subtask_name_non_string() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"subtask_name": 123}})
    assert snap.subtask_name is None


# ---------------------------------------------------------------------------
# sn edge cases
# ---------------------------------------------------------------------------

def test_model_sn_empty() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "   "}})
    assert snap.sn is None


# ---------------------------------------------------------------------------
# nozzle_temp
# ---------------------------------------------------------------------------

def test_model_nozzle_temp_missing() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"upgrade_state": {"nozzle_ctc": {"ctc": {}}}}})
    assert snap.nozzle_temp is None


def test_model_nozzle_temp_vt_tray_none() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"vt_tray": None}})
    assert snap.nozzle_temp is None


# ---------------------------------------------------------------------------
# name (top-level)
# ---------------------------------------------------------------------------

def test_model_name_none_when_absent() -> None:
    snap = PrinterSnapshot(connected=True, raw={})
    assert snap.name is None


# ---------------------------------------------------------------------------
# AMS status name mapping
# ---------------------------------------------------------------------------

def test_ams_status_name_known_codes() -> None:
    from bambulab_metrics_exporter.models import AMS_STATUS_NAMES
    for code, expected in AMS_STATUS_NAMES.items():
        snap = PrinterSnapshot(connected=True, raw={"print": {"ams_status": code}})
        assert snap.ams_status_name == expected, f"code {code}: expected {expected}, got {snap.ams_status_name}"


def test_ams_status_name_unknown_code() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams_status": 999}})
    assert snap.ams_status_name == "unknown_999"


def test_ams_status_name_none_when_missing() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {}})
    assert snap.ams_status_name is None


def test_ams_status_idle() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams_status": 0}})
    assert snap.ams_status == 0.0
    assert snap.ams_status_name == "idle"


def test_ams_status_filament_change() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams_status": 1}})
    assert snap.ams_status_name == "filament_change"


# ---------------------------------------------------------------------------
# AMS RFID status name mapping
# ---------------------------------------------------------------------------

def test_ams_rfid_status_name_known_codes() -> None:
    from bambulab_metrics_exporter.models import AMS_RFID_STATUS_NAMES
    for code, expected in AMS_RFID_STATUS_NAMES.items():
        snap = PrinterSnapshot(connected=True, raw={"print": {"ams_rfid_status": code}})
        assert snap.ams_rfid_status_name == expected, f"code {code}: expected {expected}, got {snap.ams_rfid_status_name}"


def test_ams_rfid_status_name_unknown_code() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams_rfid_status": 99}})
    assert snap.ams_rfid_status_name == "unknown_99"


def test_ams_rfid_status_name_none_when_missing() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {}})
    assert snap.ams_rfid_status_name is None


def test_ams_rfid_status_idle() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams_rfid_status": 0}})
    assert snap.ams_rfid_status == 0.0
    assert snap.ams_rfid_status_name == "idle"


def test_ams_rfid_status_reading() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams_rfid_status": 1}})
    assert snap.ams_rfid_status_name == "reading"


# ---------------------------------------------------------------------------
# Printer model resolver modernization
# ---------------------------------------------------------------------------

def test_printer_type_product_name_x1c() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "ota", "product_name": "Bambu Lab X1 Carbon"}]},
    )
    assert snap.printer_type == "X1C"


def test_printer_type_product_name_x1e() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "ota", "product_name": "Bambu Lab X1E"}]},
    )
    assert snap.printer_type == "X1E"


def test_printer_type_sn_prefix_x1c() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "00M09D510900751"}})
    assert snap.printer_type == "X1C"


def test_printer_type_sn_prefix_p1s() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "01S0FABCDE123"}})
    assert snap.printer_type == "P1S"


def test_printer_type_sn_prefix_a1mini() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "030XYZABC"}})
    assert snap.printer_type == "A1MINI"


def test_printer_type_hw_project_a1mini() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "esp32", "hw_ver": "AP03", "project_name": "N1"}]},
    )
    assert snap.printer_type == "A1MINI"


def test_printer_type_device_type_p1p() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 2}}})
    assert snap.printer_type == "P1P"
