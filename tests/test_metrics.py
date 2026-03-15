"""Tests for bambulab_metrics_exporter.metrics."""
from __future__ import annotations

import math


from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot, STG_CUR_NAMES


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _snap(print_block: dict | None = None) -> PrinterSnapshot:
    return PrinterSnapshot(connected=True, raw={"print": print_block or {}})


def _metrics(printer_name: str = "test", serial: str = "SN123") -> ExporterMetrics:
    return ExporterMetrics(printer_name=printer_name, serial=serial)


def _get(m: ExporterMetrics, gauge_name: str, extra_labels: dict | None = None) -> float:
    labels = {"printer_name": m._printer_name, "serial": m._serial}  # type: ignore[attr-defined]
    if extra_labels:
        labels.update(extra_labels)
    gauge = getattr(m, gauge_name)
    return gauge.labels(**labels)._value.get()


# ---------------------------------------------------------------------------
# Smoke / basic update
# ---------------------------------------------------------------------------

def test_metrics_update_smoke() -> None:
    metrics = _metrics("x1c", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "gcode_state": "RUNNING",
                "mc_percent": 10,
                "mc_remaining_time": 20,
                "nozzle_temper": 205,
                "bed_temper": 58,
                "mc_print_error_code": 0,
            }
        },
    )
    metrics.update_from_snapshot(snapshot)
    metrics.mark_scrape(0.4, True, now_ts=123.0)
    value = metrics.printer_up.labels(printer_name="x1c", serial="SN123")._value.get()
    assert value == 1.0


def test_metrics_no_subtask_no_fail_reason() -> None:
    metrics = _metrics("p1", "S1")
    snapshot = PrinterSnapshot(connected=True, raw={"print": {}})
    metrics.update_from_snapshot(snapshot)
    assert len(metrics.subtask_name_info._metrics) == 0
    assert len(metrics.fail_reason_info._metrics) == 0


# ---------------------------------------------------------------------------
# Full update including AMS, lights, xcam
# ---------------------------------------------------------------------------

def test_metrics_full_update_with_ams_lights_xcam() -> None:
    metrics = _metrics("p1", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "gcode_state": "RUNNING",
                "mc_print_stage": "PRINTING",
                "mc_percent": 50,
                "mc_remaining_time": 10,
                "layer_num": 100,
                "total_layer_num": 200,
                "nozzle_temper": 210,
                "nozzle_target_temper": 220,
                "nozzle_diameter": "0.4",
                "bed_temper": 60,
                "bed_target_temper": 65,
                "chamber_temper": 34,
                "fan_gear": 10,
                "big_fan1_speed": "33",
                "big_fan2_speed": "44",
                "cooling_fan_speed": "55",
                "heatbreak_fan_speed": "66",
                "mc_stage": 1,
                "mc_print_sub_stage": 2,
                "print_real_action": 3,
                "print_gcode_action": 4,
                "wifi_signal": "-60",
                "online": {"ahb": True, "ext": True},
                "ams_status": 1,
                "ams_rfid_status": 2,
                "print_error": 0,
                "ap_err": 0,
                "mc_print_error_code": "0",
                "spd_lvl": 3,
                "spd_mag": 124,
                "sn": "SN123456",
                "fail_reason": "filament runout",
                "lights_report": [
                    {"node": "chamber_light", "mode": "on"},
                    {"node": "work_light", "mode": "off"},
                ],
                "xcam": {"printing_monitor": True, "spaghetti_detector": False},
                "ams": {
                    "tray_now": "2",
                    "ams": [
                        {
                            "id": "1",
                            "humidity": "4",
                            "humidity_raw": "56",
                            "temp": "23",
                            "tray": [
                                {"id": "2", "remain": "87", "tray_type": "PLA", "tray_color": "f98c36ff"},
                                {"id": "3", "remain": 50, "ctype": "PETG", "tray_color": "161616ff"},
                            ],
                        }
                    ],
                },
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    metrics.mark_scrape(0.1, True, now_ts=111.0)

    labels = dict(printer_name="p1", serial="SN123")
    assert metrics.printer_up.labels(**labels)._value.get() == 1.0
    assert metrics.chamber_light_on.labels(**labels)._value.get() == 1.0
    assert metrics.work_light_on.labels(**labels)._value.get() == 0.0
    assert metrics.fan_gear.labels(**labels)._value.get() == 10.0
    assert metrics.nozzle_diameter.labels(**labels)._value.get() == 0.4
    assert metrics.spd_lvl.labels(**labels)._value.get() == 3.0
    assert metrics.spd_mag.labels(**labels)._value.get() == 124.0
    assert metrics.spd_lvl_state.labels(**labels, mode="SPORT")._value.get() == 1.0
    assert metrics.print_error_explicit.labels(**labels)._value.get() == 0.0
    assert metrics.fail_reason_info.labels(**labels, fail_reason="filament runout")._value.get() == 1.0
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="1")._value.get() == 56.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 4.0
    assert metrics.ams_slot_tray_type.labels(**labels, ams_id="1", slot_id="2", tray_type="PLA")._value.get() == 1.0
    assert metrics.ams_slot_tray_type.labels(**labels, ams_id="1", slot_id="3", tray_type="PETG")._value.get() == 1.0
    assert metrics.ams_slot_tray_color.labels(**labels, ams_id="1", slot_id="2", tray_color="F98C36FF")._value.get() == 1.0


def test_metrics_work_light_flashing_treated_as_on() -> None:
    metrics = _metrics("p1", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={"print": {"lights_report": [{"node": "work_light", "mode": "flashing"}]}},
    )
    metrics.update_from_snapshot(snapshot)
    labels = dict(printer_name="p1", serial="SN123")
    assert metrics.work_light_on.labels(**labels)._value.get() == 1.0


# ---------------------------------------------------------------------------
# AMS – humidity strict mapping
# ---------------------------------------------------------------------------

def test_ams_humidity_strict_mapping() -> None:
    metrics = _metrics("p1", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {"id": "0", "humidity": "5", "humidity_raw": "62"},
                        {"id": "1", "humidity": 4, "humidity_raw": 58, "humidity_level": 2},
                        {"id": "2", "humidity": "3"},
                    ]
                }
            }
        },
    )
    metrics.update_from_snapshot(snapshot)

    labels = {"printer_name": "p1", "serial": "SN123"}
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get() == 5.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 4.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="2")._value.get() == 3.0
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="0")._value.get() == 62.0
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="1")._value.get() == 58.0
    assert (labels["printer_name"], labels["serial"], "2") not in metrics.ams_unit_humidity._metrics


def test_ams_humidity_index_invalid_values_are_skipped() -> None:
    metrics = _metrics("p1", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {"id": "0", "humidity": "oops"},
                        {"id": "1", "humidity": None},
                        {"id": "2", "humidity": "nan"},
                    ]
                }
            }
        },
    )
    metrics.update_from_snapshot(snapshot)
    assert len(metrics.ams_unit_humidity_index._metrics) == 0


def test_ams_humidity_index_per_ams_refresh_behavior() -> None:
    metrics = _metrics("p1", "SN123")
    labels = {"printer_name": "p1", "serial": "SN123"}

    first = PrinterSnapshot(
        connected=True,
        raw={"print": {"ams": {"ams": [{"id": "0", "humidity": 3}, {"id": "1", "humidity": 5}]}}},
    )
    metrics.update_from_snapshot(first)
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get() == 3.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 5.0

    second = PrinterSnapshot(
        connected=True,
        raw={"print": {"ams": {"ams": [{"id": "0", "humidity": "7"}, {"id": "1", "humidity": "bad"}]}}},
    )
    metrics.update_from_snapshot(second)
    # Index is range-limited to [1..5], so 7 is ignored.
    assert (labels["printer_name"], labels["serial"], "0") not in metrics.ams_unit_humidity_index._metrics
    assert (labels["printer_name"], labels["serial"], "1") not in metrics.ams_unit_humidity_index._metrics


def test_ams_humidity_raw_out_of_range_is_ignored() -> None:
    metrics = _metrics("p1", "SN123")
    labels = {"printer_name": "p1", "serial": "SN123"}

    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {"id": "0", "humidity_raw": "0", "humidity": "3"},
                        {"id": "1", "humidity_raw": "150", "humidity": "4"},
                    ]
                }
            }
        },
    )
    metrics.update_from_snapshot(snapshot)
    assert (labels["printer_name"], labels["serial"], "0") not in metrics.ams_unit_humidity._metrics
    assert (labels["printer_name"], labels["serial"], "1") not in metrics.ams_unit_humidity._metrics
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get() == 3.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 4.0


def test_ams_error_edge_cases() -> None:
    """Invalid humidity/temp types should not crash update_from_snapshot."""
    metrics = _metrics("p1", "S1")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "humidity": "not-a-number",
                            "temp": None,
                            "tray": [{"id": "0", "remain": "invalid"}],
                        }
                    ]
                }
            }
        },
    )
    metrics.update_from_snapshot(snapshot)
    assert True  # no exception raised


# ---------------------------------------------------------------------------
# AMS – slot data (remain, tray type, color)
# ---------------------------------------------------------------------------

def test_ams_string_remain_and_tray_type_fallback() -> None:
    metrics = _metrics("p1", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "tray_now": "1",
                            "tray": [
                                {"id": "1", "remain": "77.5", "tray_color": "ffffff", "ctype": "PLA"}
                            ],
                        }
                    ]
                }
            }
        },
    )
    metrics.update_from_snapshot(snapshot)
    labels = {"printer_name": "p1", "serial": "SN123"}
    assert metrics.ams_slot_remaining_percent.labels(**labels, ams_id="0", slot_id="1")._value.get() == 77.5
    assert metrics.ams_slot_tray_type.labels(**labels, ams_id="0", slot_id="1", tray_type="PLA")._value.get() == 1.0


def test_ams_invalid_remain_is_ignored() -> None:
    metrics = _metrics("p1", "SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "tray": [{"id": "1", "remain": "bad-value", "tray_type": "PETG", "tray_color": "161616ff"}],
                        }
                    ]
                }
            }
        },
    )
    metrics.update_from_snapshot(snapshot)
    labels = {"printer_name": "p1", "serial": "SN123", "ams_id": "0", "slot_id": "1"}
    assert metrics.ams_slot_remaining_percent.labels(**labels)._value.get() == 0.0


# ---------------------------------------------------------------------------
# Phase 1: binary sensors, sdcard
# ---------------------------------------------------------------------------

class TestDoorOpen:
    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _get(self, m: ExporterMetrics, gauge_name: str, extra: dict | None = None) -> float:
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        if extra:
            labels.update(extra)
        return getattr(m, gauge_name).labels(**labels)._value.get()

    def test_door_open_true(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"door_open": True}))
        assert self._get(m, "door_open") == 1.0

    def test_door_open_false(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"door_open": False}))
        assert self._get(m, "door_open") == 0.0

    def test_door_open_from_home_flag(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"home_flag": 0x00800000}))
        assert self._get(m, "door_open") == 1.0

    def test_door_closed_from_home_flag(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"home_flag": 0x0}))
        assert self._get(m, "door_open") == 0.0

    def test_door_open_from_stat_hex(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"stat": "46A58008"}))
        assert self._get(m, "door_open") == 1.0

    def test_door_closed_from_stat_hex(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"stat": "46258008"}))
        assert self._get(m, "door_open") == 0.0

    def test_door_open_model_preference_x1_home_flag_over_stat(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"model_id": "X1C", "home_flag": 0x00800000, "stat": "46258008"}))
        assert self._get(m, "door_open") == 1.0

    def test_door_open_model_preference_non_x1_stat_over_home_flag(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"model_id": "H2D", "home_flag": 0x00800000, "stat": "46258008"}))
        assert self._get(m, "door_open") == 0.0

    def test_door_open_none(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({}))
        assert math.isnan(self._get(m, "door_open"))


class TestFlagDerivedBinarySensors:
    def test_flag_binary_sensors_from_home_flag(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(
            _snap(
                {
                    "home_flag": (
                        0x00040000  # wired_network
                        | 0x00000020  # camera_recording
                        | 0x00000400  # ams_auto_switch
                        | 0x00100000  # filament_tangle_detected
                        | 0x00080000  # filament_tangle_detect_supported
                    )
                }
            )
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.wired_network.labels(**labels)._value.get() == 1.0
        assert m.camera_recording.labels(**labels)._value.get() == 1.0
        assert m.ams_auto_switch.labels(**labels)._value.get() == 1.0
        assert m.filament_tangle_detected.labels(**labels)._value.get() == 1.0
        assert m.filament_tangle_detect_supported.labels(**labels)._value.get() == 1.0


class TestSdcardStatus:
    def test_sdcard_from_bool(self) -> None:
        snap = _snap({"sdcard": True})
        assert snap.sdcard_status == "present"

    def test_stat_flag_state_metric(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"stat": "46A58008"}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.stat_flag_state.labels(**labels, flag="door_open")._value.get() == 1.0

    def test_sdcard_from_home_flag(self) -> None:
        snap = _snap({"home_flag": 0x100})
        assert snap.sdcard_status == "present"

    def test_sdcard_abnormal_home_flag(self) -> None:
        snap = _snap({"home_flag": 0x300})
        assert snap.sdcard_status == "abnormal"

    def test_sdcard_absent_home_flag(self) -> None:
        snap = _snap({"home_flag": 0x0})
        assert snap.sdcard_status == "absent"

    def test_sdcard_info_metric(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"sdcard": True}))
        labels: dict = {"printer_name": "test", "serial": "SN123", "status": "present"}
        assert m.sdcard_status_info.labels(**labels)._value.get() == 1.0


# ---------------------------------------------------------------------------
# Phase 3: stage info (stg_cur)
# ---------------------------------------------------------------------------

class TestStgCur:
    def test_stg_cur_printing(self) -> None:
        snap = _snap({"stg_cur": 0})
        assert snap.stg_cur == 0
        assert snap.stg_cur_name == "printing"

    def test_stg_cur_bed_leveling(self) -> None:
        snap = _snap({"stg_cur": 1})
        assert snap.stg_cur_name == "bed_leveling"

    def test_stg_cur_unknown_id(self) -> None:
        snap = _snap({"stg_cur": 99})
        assert snap.stg_cur_name == "unknown_99"

    def test_stg_cur_255(self) -> None:
        snap = _snap({"stg_cur": 255})
        assert snap.stg_cur_name == "unknown"

    def test_stg_cur_none(self) -> None:
        snap = _snap({})
        assert snap.stg_cur is None
        assert snap.stg_cur_name is None

    def test_stg_cur_metric(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"stg_cur": 7}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.stg_cur.labels(**labels)._value.get() == 7.0

    def test_stage_info_metric(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"stg_cur": 7}))
        labels: dict = {"printer_name": "test", "serial": "SN123", "stage": "heating_hotend"}
        assert m.print_stage_info.labels(**labels)._value.get() == 1.0

    def test_stage_info_clears(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"stg_cur": 0}))
        m.update_from_snapshot(_snap({"stg_cur": 1}))
        labels: dict = {"printer_name": "test", "serial": "SN123", "stage": "bed_leveling"}
        assert m.print_stage_info.labels(**labels)._value.get() == 1.0


class TestStgCurMapping:
    def test_all_known_stages(self) -> None:
        assert STG_CUR_NAMES[0] == "printing"
        assert STG_CUR_NAMES[13] == "homing_toolhead"
        assert STG_CUR_NAMES[23] == "motor_noise_calibration"
        assert STG_CUR_NAMES[34] == "standby"
        assert STG_CUR_NAMES[35] == "idle"
        assert STG_CUR_NAMES[-1] == "idle"
