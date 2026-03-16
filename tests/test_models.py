"""Tests for bambulab_metrics_exporter.models."""
from __future__ import annotations

from bambulab_metrics_exporter import models
from bambulab_metrics_exporter.models import (
    PrinterSnapshot,
    resolve_ams_model,
    resolve_ams_series,
    parse_ams_info,
    AMS_SERIAL_PREFIX_TO_MODEL,
    AMS_MODEL_TO_SERIES,
    AMS_TYPE_TO_MODEL,
)


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


def test_external_spool_active_from_tray_now() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "254"}}})
    assert snap.external_spool_active == 1.0


def test_external_spool_inactive_from_tray_now() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "255"}}})
    assert snap.external_spool_active == 0.0


def test_external_spool_entries_from_vir_slot_preferred() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "vir_slot": [
                    {"id": "254", "tray_type": "PLA", "tray_info_idx": "GFA01", "tray_color": "76d9f4ff"},
                    {"id": "255", "tray_type": "PETG", "tray_info_idx": "GFB99", "tray_color": "11223344"},
                    {"id": "12", "tray_type": "SHOULD_IGNORE"},
                ],
                "vt_tray": {"id": "254", "tray_type": "ABS", "tray_info_idx": "X", "tray_color": "FFFFFFFF"},
            }
        },
    )
    assert snap.external_spool_entries == [
        {"id": "254", "tray_type": "PLA", "tray_info_idx": "GFA01", "tray_color": "76D9F4FF"},
        {"id": "255", "tray_type": "PETG", "tray_info_idx": "GFB99", "tray_color": "11223344"},
    ]


def test_external_spool_entries_from_vt_tray_fallback() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"vt_tray": {"id": "254", "tray_type": "ABS", "tray_info_idx": "GFB00", "tray_color": "000000ff"}}},
    )
    assert snap.external_spool_entries == [
        {"id": "254", "tray_type": "ABS", "tray_info_idx": "GFB00", "tray_color": "000000FF"}
    ]


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


def test_printer_type_sn_prefix_x1() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "00W123456789"}})
    assert snap.printer_type == "X1"


def test_printer_type_sn_prefix_p1p() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "01S0FABCDE123"}})
    assert snap.printer_type == "P1P"


def test_printer_type_sn_prefix_p1s() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "01P0FABCDE123"}})
    assert snap.printer_type == "P1S"


def test_printer_type_sn_prefix_x1e() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "03WXYZABC"}})
    assert snap.printer_type == "X1E"


def test_printer_type_sn_prefix_a1mini() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "030XYZABC"}})
    assert snap.printer_type == "A1MINI"


def test_printer_type_sn_prefix_a1() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "039XYZABC"}})
    assert snap.printer_type == "A1"


def test_printer_type_sn_prefix_p2s() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "22EABCDE123"}})
    assert snap.printer_type == "P2S"


def test_printer_type_sn_prefix_h2s() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "093ABCDE123"}})
    assert snap.printer_type == "H2S"


def test_printer_type_sn_prefix_h2d() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "094ABCDE123"}})
    assert snap.printer_type == "H2D"


def test_printer_type_hw_project_a1mini() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "esp32", "hw_ver": "AP03", "project_name": "N1"}]},
    )
    assert snap.printer_type == "A1MINI"


def test_printer_type_device_type_p1p() -> None:
    snap = PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 2}}})
    assert snap.printer_type == "P1P"


# ---------------------------------------------------------------------------
# AMS model/series integration (v0.1.24)
# ---------------------------------------------------------------------------

class TestAmsSerialPrefixMapping:
    """Test AMS model detection from serial prefix."""

    def test_prefix_006_maps_to_ams_1(self) -> None:
        assert resolve_ams_model({"sn": "006ABCDEF"}) == "ams_1"

    def test_prefix_03c_maps_to_ams_lite(self) -> None:
        assert resolve_ams_model({"sn": "03CABCDEF"}) == "ams_lite"

    def test_prefix_19c_maps_to_ams_2_pro(self) -> None:
        assert resolve_ams_model({"sn": "19CABCDEF"}) == "ams_2_pro"

    def test_prefix_19f_maps_to_ams_ht(self) -> None:
        assert resolve_ams_model({"sn": "19FABCDEF"}) == "ams_ht"

    def test_prefix_case_insensitive(self) -> None:
        assert resolve_ams_model({"sn": "006abcdef"}) == "ams_1"
        assert resolve_ams_model({"sn": "03cabcdef"}) == "ams_lite"

    def test_unknown_prefix_returns_unknown(self) -> None:
        assert resolve_ams_model({"sn": "999UNKNOWN"}) == "unknown"

    def test_no_serial_returns_unknown(self) -> None:
        assert resolve_ams_model({}) == "unknown"

    def test_empty_serial_returns_unknown(self) -> None:
        assert resolve_ams_model({"sn": "  "}) == "unknown"

    def test_all_known_prefixes_covered(self) -> None:
        """All entries in AMS_SERIAL_PREFIX_TO_MODEL are reachable."""
        for prefix, expected_model in AMS_SERIAL_PREFIX_TO_MODEL.items():
            result = resolve_ams_model({"sn": prefix + "TESTDATA"})
            assert result == expected_model, f"prefix {prefix!r} -> expected {expected_model!r}, got {result!r}"


class TestAmsModelToSeriesMapping:
    """Test AMS model -> series mapping."""

    def test_ams_1_is_gen_1(self) -> None:
        assert resolve_ams_series("ams_1") == "gen_1"

    def test_ams_lite_is_gen_1(self) -> None:
        assert resolve_ams_series("ams_lite") == "gen_1"

    def test_ams_2_pro_is_gen_2(self) -> None:
        assert resolve_ams_series("ams_2_pro") == "gen_2"

    def test_ams_ht_is_gen_2(self) -> None:
        assert resolve_ams_series("ams_ht") == "gen_2"

    def test_unknown_model_returns_unknown(self) -> None:
        assert resolve_ams_series("unknown") == "unknown"

    def test_all_model_to_series_entries(self) -> None:
        for model, expected_series in AMS_MODEL_TO_SERIES.items():
            assert resolve_ams_series(model) == expected_series


class TestAmsInfoTypeOverride:
    """Test ams_info ams_type bits take precedence over serial prefix."""

    def test_ams_type_1_overrides_serial(self) -> None:
        # Serial prefix says ams_lite (03C), but ams_info type=1 -> ams_1
        result = resolve_ams_model({"sn": "03CABCDEF", "ams_info": 0b0001})
        assert result == "ams_1"

    def test_ams_type_2_maps_to_ams_lite(self) -> None:
        result = resolve_ams_model({"ams_info": 0b0010})
        assert result == "ams_lite"

    def test_ams_type_3_maps_to_ams_2_pro(self) -> None:
        result = resolve_ams_model({"ams_info": 0b0011})
        assert result == "ams_2_pro"

    def test_ams_type_4_maps_to_ams_ht(self) -> None:
        result = resolve_ams_model({"ams_info": 0b0100})
        assert result == "ams_ht"

    def test_ams_type_0_falls_through_to_serial(self) -> None:
        # ams_info=0 means ams_type=0, which is invalid/zero, so fall through to serial
        result = resolve_ams_model({"sn": "006ABCDEF", "ams_info": 0})
        assert result == "ams_1"

    def test_ams_type_unknown_falls_through_to_serial(self) -> None:
        # ams_info with ams_type=15 (unknown), no serial -> unknown
        result = resolve_ams_model({"ams_info": 0b00001111})
        assert result == "unknown"

    def test_ams_info_bits_only_low_4_bits_used_for_type(self) -> None:
        # Higher bits set, but ams_type (bits 0-3) = 1 -> ams_1
        result = resolve_ams_model({"ams_info": 0b11110001})
        assert result == "ams_1"

    def test_all_known_ams_types(self) -> None:
        for ams_type, expected_model in AMS_TYPE_TO_MODEL.items():
            result = resolve_ams_model({"ams_info": ams_type})
            assert result == expected_model, f"ams_type {ams_type} -> expected {expected_model!r}, got {result!r}"


class TestParseAmsInfo:
    """Test ams_info bitmask parsing."""

    def test_parse_zero(self) -> None:
        parsed = parse_ams_info(0)
        assert parsed["ams_type"] == 0
        assert parsed["dry_heater_state"] == 0
        assert parsed["dry_fan1"] == 0
        assert parsed["dry_fan2"] == 0
        assert parsed["dry_sub_status"] == 0

    def test_ams_type_bits_0_3(self) -> None:
        parsed = parse_ams_info(0b1010)
        assert parsed["ams_type"] == 0b1010

    def test_dry_heater_state_bits_4_7(self) -> None:
        # bits 4-7: value 5 = 0b0101_0000 = 0x50
        parsed = parse_ams_info(0x50)
        assert parsed["dry_heater_state"] == 5

    def test_dry_fan1_bits_18_19(self) -> None:
        # bits 18-19: value 3 -> 0b11 << 18 = 0xC0000
        parsed = parse_ams_info(0xC0000)
        assert parsed["dry_fan1"] == 3

    def test_dry_fan2_bits_20_21(self) -> None:
        # bits 20-21: value 2 -> 0b10 << 20 = 0x200000
        parsed = parse_ams_info(0x200000)
        assert parsed["dry_fan2"] == 2

    def test_dry_sub_status_bits_22_25(self) -> None:
        # bits 22-25: value 7 -> 0b0111 << 22 = 0x1C00000
        parsed = parse_ams_info(0x1C00000)
        assert parsed["dry_sub_status"] == 7

    def test_combined_value(self) -> None:
        # ams_type=2, dry_heater=3, dry_fan1=1, dry_fan2=2, dry_sub_status=5
        val = (2) | (3 << 4) | (1 << 18) | (2 << 20) | (5 << 22)
        parsed = parse_ams_info(val)
        assert parsed["ams_type"] == 2
        assert parsed["dry_heater_state"] == 3
        assert parsed["dry_fan1"] == 1
        assert parsed["dry_fan2"] == 2
        assert parsed["dry_sub_status"] == 5


class TestAmsUnitsWithModel:
    """Test PrinterSnapshot.ams_units_with_model property."""

    def test_ams_units_with_model_no_units(self) -> None:
        snap = PrinterSnapshot(connected=True, raw={"print": {}})
        assert snap.ams_units_with_model == []

    def test_ams_units_with_model_serial_prefix(self) -> None:
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006TESTSERIAL"}]}}},
        )
        enriched = snap.ams_units_with_model
        assert len(enriched) == 1
        assert enriched[0]["ams_model"] == "ams_1"
        assert enriched[0]["ams_series"] == "gen_1"

    def test_ams_units_with_model_ams_info_override(self) -> None:
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006TESTSERIAL", "ams_info": 0b0011}]}}},
        )
        enriched = snap.ams_units_with_model
        # ams_info ams_type=3 -> ams_2_pro (overrides 006 prefix)
        assert enriched[0]["ams_model"] == "ams_2_pro"
        assert enriched[0]["ams_series"] == "gen_2"

    def test_ams_units_with_model_unknown(self) -> None:
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0"}]}}},
        )
        enriched = snap.ams_units_with_model
        assert enriched[0]["ams_model"] == "unknown"
        assert enriched[0]["ams_series"] == "unknown"

    def test_ams_units_preserves_original_fields(self) -> None:
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "1", "humidity": 3, "sn": "19FABCDEF"}]}}},
        )
        enriched = snap.ams_units_with_model
        assert enriched[0]["id"] == "1"
        assert enriched[0]["humidity"] == 3
        assert enriched[0]["ams_model"] == "ams_ht"
        assert enriched[0]["ams_series"] == "gen_2"


# ---------------------------------------------------------------------------
# Additional edge cases: serial prefix mapping (v0.1.24 supplement)
# ---------------------------------------------------------------------------

class TestAmsSerialPrefixEdgeCases:
    """Additional edge cases for serial-prefix mapping."""

    def test_single_char_serial_returns_unknown(self) -> None:
        # Serial shorter than any prefix should not match anything
        assert resolve_ams_model({"sn": "0"}) == "unknown"

    def test_two_char_serial_returns_unknown(self) -> None:
        assert resolve_ams_model({"sn": "00"}) == "unknown"

    def test_serial_exactly_3_chars_matching(self) -> None:
        # Exact prefix length (e.g. "006") should match
        assert resolve_ams_model({"sn": "006"}) == "ams_1"

    def test_serial_exactly_3_chars_non_matching(self) -> None:
        # "007" is not a known prefix
        assert resolve_ams_model({"sn": "007"}) == "unknown"

    def test_whitespace_only_serial_returns_unknown(self) -> None:
        assert resolve_ams_model({"sn": "   "}) == "unknown"

    def test_serial_with_leading_whitespace_still_matches(self) -> None:
        # strip() is applied, so leading spaces should not prevent matching
        assert resolve_ams_model({"sn": "  006ABCDEF"}) == "ams_1"

    def test_serial_none_value_returns_unknown(self) -> None:
        assert resolve_ams_model({"sn": None}) == "unknown"

    def test_serial_integer_value_returns_unknown(self) -> None:
        # sn must be a string; int type is skipped
        assert resolve_ams_model({"sn": 6}) == "unknown"

    def test_serial_list_value_returns_unknown(self) -> None:
        assert resolve_ams_model({"sn": ["006ABCDEF"]}) == "unknown"

    def test_prefix_match_is_prefix_not_substring(self) -> None:
        # A serial that contains the prefix but NOT at the start should not match
        # e.g. "XXX006ABCDEF" — prefix "006" is not at start
        assert resolve_ams_model({"sn": "XXX006ABCDEF"}) == "unknown"

    def test_all_lowercase_prefix_matches(self) -> None:
        # Already tested mixed case, but fully lowercase sn
        assert resolve_ams_model({"sn": "006abcdef"}) == "ams_1"
        assert resolve_ams_model({"sn": "19cabcdef"}) == "ams_2_pro"
        assert resolve_ams_model({"sn": "19fabcdef"}) == "ams_ht"

    def test_all_uppercase_prefix_matches(self) -> None:
        assert resolve_ams_model({"sn": "03CABCDEF"}) == "ams_lite"
        assert resolve_ams_model({"sn": "19FABCDEF"}) == "ams_ht"


# ---------------------------------------------------------------------------
# Additional edge cases: ams_info precedence over serial (v0.1.24 supplement)
# ---------------------------------------------------------------------------

class TestAmsInfoPrecedenceEdgeCases:
    """Additional edge cases: ams_info over serial, including string payload variants."""

    def test_ams_info_decimal_string_is_used(self) -> None:
        # Some payloads provide ams_info as decimal string
        result = resolve_ams_model({"sn": "006ABCDEF", "ams_info": "3"})
        assert result == "ams_2_pro"  # type=3 overrides serial prefix

    def test_ams_info_hex_string_in_info_field_is_used(self) -> None:
        # Some cloud payloads use key `info` with hex payload
        result = resolve_ams_model({"sn": "006ABCDEF", "info": "0x4"})
        assert result == "ams_ht"  # type=4 overrides serial prefix

    def test_info_digit_string_prefers_hex_when_type_matches(self) -> None:
        # Real cloud payload example: "1001" should be interpreted as hex (0x1001),
        # which yields ams_type=1 (ams_1), not decimal 1001 (ams_type=9 unknown).
        result = resolve_ams_model({"info": "1001"})
        assert result == "ams_1"

    def test_ams_info_float_is_not_used(self) -> None:
        # float is not an int
        result = resolve_ams_model({"sn": "006ABCDEF", "ams_info": 3.0})
        assert result == "ams_1"  # from serial prefix

    def test_ams_info_none_is_not_used(self) -> None:
        result = resolve_ams_model({"sn": "006ABCDEF", "ams_info": None})
        assert result == "ams_1"

    def test_ams_info_zero_falls_through_to_serial(self) -> None:
        result = resolve_ams_model({"sn": "03CABCDEF", "ams_info": 0})
        assert result == "ams_lite"  # serial prefix takes over

    def test_ams_info_zero_no_serial_returns_unknown(self) -> None:
        result = resolve_ams_model({"ams_info": 0})
        assert result == "unknown"

    def test_ams_info_negative_falls_through_to_serial(self) -> None:
        # Negative values: isinstance(x, int) is True for negative ints
        # but ams_info_raw > 0 guard blocks them
        result = resolve_ams_model({"sn": "006ABCDEF", "ams_info": -1})
        assert result == "ams_1"

    def test_ams_info_unknown_type_no_serial_returns_unknown(self) -> None:
        # ams_type=15 is not in AMS_TYPE_TO_MODEL, no serial -> unknown
        result = resolve_ams_model({"ams_info": 0xF})
        assert result == "unknown"

    def test_ams_info_unknown_type_with_serial_falls_through(self) -> None:
        # ams_type=15 unknown, but serial matches -> serial result
        result = resolve_ams_model({"sn": "19CABCDEF", "ams_info": 0xF})
        assert result == "ams_2_pro"

    def test_ams_info_bits_above_type_do_not_affect_type(self) -> None:
        # Set many high bits; type bits 0-3 = 4 -> ams_ht
        val = 0xFFFFFF0 | 4  # type=4, lots of upper bits set
        result = resolve_ams_model({"ams_info": val})
        assert result == "ams_ht"


# ---------------------------------------------------------------------------
# Additional edge cases: parse_ams_info bit parsing (v0.1.24 supplement)
# ---------------------------------------------------------------------------

class TestParseAmsInfoEdgeCases:
    """Additional edge cases for parse_ams_info drying telemetry bit parsing."""

    def test_max_ams_type(self) -> None:
        # bits 0-3 all set = 15
        parsed = parse_ams_info(0xF)
        assert parsed["ams_type"] == 15

    def test_max_dry_heater_state(self) -> None:
        # bits 4-7 all set = 15
        parsed = parse_ams_info(0xF0)
        assert parsed["dry_heater_state"] == 15

    def test_max_dry_fan1(self) -> None:
        # bits 18-19 both set = 3
        parsed = parse_ams_info(3 << 18)
        assert parsed["dry_fan1"] == 3

    def test_max_dry_fan2(self) -> None:
        # bits 20-21 both set = 3
        parsed = parse_ams_info(3 << 20)
        assert parsed["dry_fan2"] == 3

    def test_max_dry_sub_status(self) -> None:
        # bits 22-25 all set = 15
        parsed = parse_ams_info(0xF << 22)
        assert parsed["dry_sub_status"] == 15

    def test_all_fields_max(self) -> None:
        # All fields at max values simultaneously
        val = 0xF | (0xF << 4) | (3 << 18) | (3 << 20) | (0xF << 22)
        parsed = parse_ams_info(val)
        assert parsed["ams_type"] == 15
        assert parsed["dry_heater_state"] == 15
        assert parsed["dry_fan1"] == 3
        assert parsed["dry_fan2"] == 3
        assert parsed["dry_sub_status"] == 15

    def test_bits_8_to_17_are_ignored(self) -> None:
        # Bits 8-17 are not mapped; setting them should not affect known fields
        val = 0b11_1111_1111 << 8  # bits 8-17 all set
        parsed = parse_ams_info(val)
        assert parsed["ams_type"] == 0
        assert parsed["dry_heater_state"] == 0
        assert parsed["dry_fan1"] == 0
        assert parsed["dry_fan2"] == 0
        assert parsed["dry_sub_status"] == 0

    def test_large_value_does_not_overflow_fields(self) -> None:
        # Very large value; each field should still extract only its bits
        parsed = parse_ams_info(0xFFFFFFFF)
        assert parsed["ams_type"] == 15          # bits 0-3
        assert parsed["dry_heater_state"] == 15   # bits 4-7
        assert parsed["dry_fan1"] == 3            # bits 18-19
        assert parsed["dry_fan2"] == 3            # bits 20-21
        assert parsed["dry_sub_status"] == 15     # bits 22-25

    def test_fan1_and_fan2_independent(self) -> None:
        # fan1=2, fan2=1 simultaneously
        val = (2 << 18) | (1 << 20)
        parsed = parse_ams_info(val)
        assert parsed["dry_fan1"] == 2
        assert parsed["dry_fan2"] == 1

    def test_heater_state_isolated_from_type(self) -> None:
        # ams_type=0, dry_heater=5
        val = 5 << 4
        parsed = parse_ams_info(val)
        assert parsed["ams_type"] == 0
        assert parsed["dry_heater_state"] == 5

    def test_sub_status_zero_when_not_set(self) -> None:
        # Only ams_type and dry_heater set; sub_status should be 0
        val = 3 | (2 << 4)
        parsed = parse_ams_info(val)
        assert parsed["dry_sub_status"] == 0


# ---------------------------------------------------------------------------
# Additional edge cases: unknown fallback paths (v0.1.24 supplement)
# ---------------------------------------------------------------------------

class TestAmsUnknownFallbacks:
    """Explicit tests for all fallback/unknown paths."""

    def test_completely_empty_unit_resolves_unknown(self) -> None:
        assert resolve_ams_model({}) == "unknown"
        assert resolve_ams_series("unknown") == "unknown"

    def test_unit_with_only_id_resolves_unknown(self) -> None:
        assert resolve_ams_model({"id": "0"}) == "unknown"

    def test_unit_with_only_temp_resolves_unknown(self) -> None:
        assert resolve_ams_model({"temp": 23.5}) == "unknown"

    def test_unit_with_only_humidity_resolves_unknown(self) -> None:
        assert resolve_ams_model({"humidity": 3}) == "unknown"

    def test_series_for_nonexistent_model_is_unknown(self) -> None:
        assert resolve_ams_series("ams_99") == "unknown"
        assert resolve_ams_series("") == "unknown"
        assert resolve_ams_series("gen_1") == "unknown"  # series name ≠ model name

    def test_resolve_ams_series_from_unknown_model(self) -> None:
        # Chained: model resolves unknown, then series also unknown
        model = resolve_ams_model({"sn": "ZZZUNKNOWN"})
        series = resolve_ams_series(model)
        assert model == "unknown"
        assert series == "unknown"
