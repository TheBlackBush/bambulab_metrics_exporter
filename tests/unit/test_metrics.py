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


def test_metrics_fans_follow_step_aware_percent_rounding_and_secondary_aux() -> None:
    metrics = _metrics("p2s", "SNFAN")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "big_fan1_speed": "12",     # 80
                "big_fan2_speed": "7",      # 50
                "cooling_fan_speed": "15",  # 100
                "heatbreak_fan_speed": "21",  # 20 (rounded)
                "device": {
                    "airduct": {
                        "parts": [{"id": 160, "value": "7"}],
                    }
                },
            }
        },
    )
    metrics.update_from_snapshot(snapshot)

    labels = {"printer_name": "p2s", "serial": "SNFAN"}
    assert metrics.fan_big_1_speed.labels(**labels)._value.get() == 80.0
    assert metrics.fan_big_2_speed.labels(**labels)._value.get() == 50.0
    assert metrics.fan_cooling_speed.labels(**labels)._value.get() == 100.0
    assert metrics.fan_heatbreak_speed.labels(**labels)._value.get() == 20.0
    assert metrics.fan_secondary_aux_speed.labels(**labels)._value.get() == 50.0


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
    assert metrics.nozzle_diameter.labels(**labels)._value.get() == 0.4
    assert metrics.spd_lvl.labels(**labels)._value.get() == 3.0
    assert metrics.spd_mag.labels(**labels)._value.get() == 124.0
    assert metrics.spd_lvl_state.labels(**labels, mode="SPORT")._value.get() == 1.0
    assert metrics.print_error_explicit.labels(**labels)._value.get() == 0.0
    assert metrics.fail_reason_info.labels(**labels, fail_reason="filament runout")._value.get() == 1.0
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="1")._value.get() == 56.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 4.0
    assert metrics.ams_slot_tray_info.labels(**labels, ams_id="1", slot_id="2", tray_type="PLA", tray_color="F98C36FF")._value.get() == 1.0
    assert metrics.ams_slot_tray_info.labels(**labels, ams_id="1", slot_id="3", tray_type="PETG", tray_color="161616FF")._value.get() == 1.0


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
    assert metrics.ams_slot_tray_info.labels(**labels, ams_id="0", slot_id="1", tray_type="PLA", tray_color="FFFFFF")._value.get() == 1.0


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
                        0x00000020  # camera_recording
                        | 0x00000400  # ams_auto_switch
                        | 0x00100000  # filament_tangle_detected
                        | 0x00080000  # filament_tangle_detect_supported
                    )
                }
            )
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.camera_recording.labels(**labels)._value.get() == 1.0
        assert m.ams_auto_switch.labels(**labels)._value.get() == 1.0
        assert m.filament_tangle_detected.labels(**labels)._value.get() == 1.0
        assert m.filament_tangle_detect_supported.labels(**labels)._value.get() == 1.0


class TestWiredNetworkMetric:
    def test_wired_network_from_net_info(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(
            _snap({"net": {"info": [{"ip": 123}, {"ip": 456}]}})
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.wired_network.labels(**labels)._value.get() == 1.0

    def test_wired_network_false_when_wired_ip_is_zero(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(
            _snap({"net": {"info": [{"ip": 123}, {"ip": 0}]}})
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.wired_network.labels(**labels)._value.get() == 0.0


class TestExternalSpoolMetrics:
    def test_external_spool_active_from_tray_now_254(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"ams": {"tray_now": "254"}}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.external_spool_active.labels(**labels)._value.get() == 1.0

    def test_external_spool_inactive_from_tray_now_255(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"ams": {"tray_now": "255"}}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.external_spool_active.labels(**labels)._value.get() == 0.0

    def test_external_spool_info_from_vir_slot(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(
            _snap(
                {
                    "vir_slot": [
                        {"id": "254", "tray_type": "PLA", "tray_info_idx": "GFA01", "tray_color": "76d9f4ff"},
                        {"id": "255", "tray_type": "PETG", "tray_info_idx": "GFB99", "tray_color": "11223344"},
                    ]
                }
            )
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.external_spool_info.labels(
            **labels,
            external_id="254",
            tray_type="PLA",
            tray_info_idx="GFA01",
            tray_color="76D9F4FF",
        )._value.get() == 1.0
        assert m.external_spool_info.labels(
            **labels,
            external_id="255",
            tray_type="PETG",
            tray_info_idx="GFB99",
            tray_color="11223344",
        )._value.get() == 1.0

    def test_external_spool_info_clears_between_updates(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"vt_tray": {"id": "254", "tray_type": "ABS"}}))
        assert len(m.external_spool_info._metrics) == 1
        m.update_from_snapshot(_snap({}))
        assert len(m.external_spool_info._metrics) == 0

    def test_external_spool_active_is_nan_when_tray_now_missing(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert math.isnan(m.external_spool_active.labels(**labels)._value.get())

    def test_external_spool_info_unknown_fallback_labels(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"vt_tray": {"id": "254"}}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.external_spool_info.labels(
            **labels,
            external_id="254",
            tray_type="unknown",
            tray_info_idx="unknown",
            tray_color="unknown",
        )._value.get() == 1.0


class TestMultiExtruderMetrics:
    def test_active_extruder_index_metric(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"device": {"extruder": {"state": 16}}}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.active_extruder_index.labels(**labels)._value.get() == 1.0

    def test_extruder_temperature_metrics(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        packed0 = (220 << 16) | 210
        packed1 = (230 << 16) | 215
        m.update_from_snapshot(
            _snap({"device": {"extruder": {"info": [{"id": 0, "temp": packed0}, {"id": 1, "temp": packed1}]}}})
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.extruder_temperature_celsius.labels(**labels, extruder_id="0")._value.get() == 210.0
        assert m.extruder_target_temperature_celsius.labels(**labels, extruder_id="1")._value.get() == 230.0

    def test_extruder_nozzle_and_active_nozzle_info(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(
            _snap(
                {
                    "device": {
                        "extruder": {
                            "state": 0,
                            "info": [{"id": 0, "temp": 0, "hnow": 0}, {"id": 1, "temp": 0, "hnow": 1}],
                        },
                        "nozzle": {"info": [{"id": 0, "type": "HS01", "diameter": 0.4}, {"id": 1, "type": "HX05", "diameter": 0.6}]},
                    }
                }
            )
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.extruder_nozzle_info.labels(
            **labels, extruder_id="0", nozzle_type="HS01", nozzle_diameter="0.4"
        )._value.get() == 1.0
        assert m.active_nozzle_info.labels(
            **labels, nozzle_type="HS01", nozzle_diameter="0.4"
        )._value.get() == 1.0


class TestHotendRackMetrics:
    def test_hotend_rack_holder_info_metrics(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"device": {"holder": {"pos": 3, "stat": 7}}}))
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.hotend_rack_holder_position_info.labels(**labels, position="centre")._value.get() == 1.0
        assert m.hotend_rack_holder_state_info.labels(**labels, state="place_hotend")._value.get() == 1.0

    def test_hotend_rack_slot_and_hotend_metrics(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        exist = (1 << 16) | (1 << 19)
        m.update_from_snapshot(
            _snap(
                {
                    "device": {
                        "nozzle": {
                            "exist": exist,
                            "tar_id": 19,
                            "info": [{"id": 16, "type": "HS00", "diameter": 0.2, "wear": 0.1, "tm": 120}],
                        }
                    }
                }
            )
        )
        labels: dict = {"printer_name": "test", "serial": "SN123"}
        assert m.hotend_rack_slot_state_info.labels(**labels, slot_id="19", state="mounted")._value.get() == 1.0
        assert m.hotend_rack_slot_state_info.labels(**labels, slot_id="16", state="docked")._value.get() == 1.0
        assert m.hotend_rack_hotend_info.labels(
            **labels, slot_id="16", nozzle_type="HS00", nozzle_diameter="0.2"
        )._value.get() == 1.0
        assert m.hotend_rack_hotend_wear_ratio.labels(**labels, slot_id="16")._value.get() == 0.1
        assert m.hotend_rack_hotend_runtime_minutes.labels(**labels, slot_id="16")._value.get() == 120.0

    def test_hotend_rack_metrics_clear_when_absent(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        m.update_from_snapshot(_snap({"device": {"holder": {"pos": 3, "stat": 0}}}))
        assert len(m.hotend_rack_holder_position_info._metrics) == 1
        m.update_from_snapshot(_snap({}))
        assert len(m.hotend_rack_holder_position_info._metrics) == 0


class TestSdcardStatus:
    def test_sdcard_from_bool(self) -> None:
        snap = _snap({"sdcard": True})
        assert snap.sdcard_status == "present"

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
# Stage info (stg_cur)
# ---------------------------------------------------------------------------

class TestStgCur:
    def test_stg_cur_printing(self) -> None:
        snap = _snap({"stg_cur": 0})
        assert snap.stg_cur == 0
        assert snap.stg_cur_name == "printing"

    def test_stg_cur_prefers_stage_id_when_present(self) -> None:
        snap = _snap({"stg_cur": 7, "stage": {"_id": 13}})
        assert snap.stg_cur == 13
        assert snap.stg_cur_name == "homing_toolhead"

    def test_stg_cur_falls_back_to_stg_cur(self) -> None:
        snap = _snap({"stg_cur": 7, "stage": {"name": "ignored_without_id"}})
        assert snap.stg_cur == 7
        assert snap.stg_cur_name == "heating_hotend"

    def test_stg_cur_idle_fix_normalizes_zero_to_255(self) -> None:
        snap = _snap({"print_type": "idle", "stg_cur": 0})
        assert snap.stg_cur == 255
        assert snap.stg_cur_name == "idle"

    def test_stg_cur_unknown_id(self) -> None:
        snap = _snap({"stg_cur": 99})
        assert snap.stg_cur_name == "unknown_99"

    def test_stg_cur_255(self) -> None:
        snap = _snap({"stg_cur": 255})
        assert snap.stg_cur_name == "idle"

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
        labels: dict = {"printer_name": "test", "serial": "SN123", "stage": "auto_bed_leveling"}
        assert m.print_stage_info.labels(**labels)._value.get() == 1.0

    def test_removed_mc_print_stage_state_metric(self) -> None:
        m = ExporterMetrics(printer_name="test", serial="SN123")
        assert not hasattr(m, "mc_print_stage_state")


class TestStgCurMapping:
    def test_all_known_stages(self) -> None:
        assert STG_CUR_NAMES[0] == "printing"
        assert STG_CUR_NAMES[1] == "auto_bed_leveling"
        assert STG_CUR_NAMES[13] == "homing_toolhead"
        assert STG_CUR_NAMES[23] == "paused_skipped_step"
        assert STG_CUR_NAMES[34] == "paused_first_layer_error"
        assert STG_CUR_NAMES[35] == "paused_nozzle_clog"
        assert STG_CUR_NAMES[36] == "check_absolute_accuracy_before_calibration"
        assert STG_CUR_NAMES[58] == "thermal_preconditioning"
        assert STG_CUR_NAMES[-1] == "idle"
        assert STG_CUR_NAMES[255] == "idle"
        assert STG_CUR_NAMES[11] == "identifying_build_plate_type"
        assert STG_CUR_NAMES[15] == "checking_extruder_temperature"


# ---------------------------------------------------------------------------
# AMS status metrics – renamed + new name info metrics
# ---------------------------------------------------------------------------

class TestAmsStatusMetrics:
    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _labels(self, m: ExporterMetrics) -> dict:
        return {"printer_name": "test", "serial": "SN123"}

    def test_ams_status_id_metric(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_status": 1}))
        labels = self._labels(m)
        assert m.ams_status_id.labels(**labels)._value.get() == 1.0

    def test_ams_status_name_info_metric(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_status": 1}))
        labels = self._labels(m)
        assert m.ams_status_name_info.labels(**labels, status="filament_change")._value.get() == 1.0

    def test_ams_status_name_idle(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_status": 0}))
        labels = self._labels(m)
        assert m.ams_status_name_info.labels(**labels, status="idle")._value.get() == 1.0

    def test_ams_status_name_unknown_code(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_status": 999}))
        labels = self._labels(m)
        assert m.ams_status_name_info.labels(**labels, status="unknown_999")._value.get() == 1.0

    def test_ams_status_name_absent_clears(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_status": 1}))
        m.update_from_snapshot(_snap({}))  # no ams_status
        assert len(m.ams_status_name_info._metrics) == 0

    def test_ams_rfid_status_id_metric(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_rfid_status": 2}))
        labels = self._labels(m)
        assert m.ams_rfid_status_id.labels(**labels)._value.get() == 2.0

    def test_ams_rfid_status_name_info_metric(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_rfid_status": 1}))
        labels = self._labels(m)
        assert m.ams_rfid_status_name_info.labels(**labels, status="reading")._value.get() == 1.0

    def test_ams_rfid_status_name_idle(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_rfid_status": 0}))
        labels = self._labels(m)
        assert m.ams_rfid_status_name_info.labels(**labels, status="idle")._value.get() == 1.0

    def test_ams_rfid_status_name_unknown(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_rfid_status": 42}))
        labels = self._labels(m)
        assert m.ams_rfid_status_name_info.labels(**labels, status="unknown_42")._value.get() == 1.0

    def test_ams_rfid_status_name_absent_clears(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_rfid_status": 1}))
        m.update_from_snapshot(_snap({}))  # no ams_rfid_status
        assert len(m.ams_rfid_status_name_info._metrics) == 0

    def test_no_ams_status_attributes_with_old_names(self) -> None:
        """Ensure old metric names no longer exist as attributes."""
        m = self._m()
        assert not hasattr(m, "ams_status"), "Old 'ams_status' attribute should not exist"
        assert not hasattr(m, "ams_rfid_status"), "Old 'ams_rfid_status' attribute should not exist"


# ---------------------------------------------------------------------------
# AMS model/series metrics (v0.1.24)
# ---------------------------------------------------------------------------

class TestAmsUnitInfoMetric:
    """Test bambulab_ams_unit_info metric emission."""

    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _labels(self) -> dict:
        return {"printer_name": "test", "serial": "SN123"}

    def test_ams_unit_info_with_serial_prefix(self) -> None:
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006TESTSERIAL"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = self._labels()
        v = m.ams_unit_info.labels(
            **labels, ams_id="0", ams_model="ams_1", ams_series="gen_1"
        )._value.get()
        assert v == 1.0

    def test_ams_unit_info_unknown_fallback(self) -> None:
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = self._labels()
        v = m.ams_unit_info.labels(
            **labels, ams_id="0", ams_model="unknown", ams_series="unknown"
        )._value.get()
        assert v == 1.0

    def test_ams_unit_info_clears_on_update(self) -> None:
        m = self._m()
        snap1 = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006TEST"}]}}},
        )
        snap2 = PrinterSnapshot(connected=True, raw={"print": {}})
        m.update_from_snapshot(snap1)
        assert len(m.ams_unit_info._metrics) == 1
        m.update_from_snapshot(snap2)
        assert len(m.ams_unit_info._metrics) == 0


class TestAmsExistingMetricLabelsUnchanged:
    """Confirm existing AMS metrics do NOT carry ams_model or ams_series labels.

    Model/series info is only exposed via bambulab_ams_unit_info.
    """

    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def test_ams_humidity_labels_unchanged(self) -> None:
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "humidity_raw": "55", "sn": "19FABCDEF"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        # Must work with only ams_id — no ams_model/ams_series
        v = m.ams_unit_humidity.labels(**labels, ams_id="0")._value.get()
        assert v == 55.0

    def test_ams_humidity_index_labels_unchanged(self) -> None:
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "humidity": "3", "sn": "03CABCDEF"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v = m.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get()
        assert v == 3.0

    def test_ams_slot_active_labels_unchanged(self) -> None:
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [
                {"id": "0", "tray_now": "1", "sn": "19CABCDEF", "tray": [{"id": "1", "tray_type": "PLA"}]}
            ]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        # Must work with only ams_id + slot_id — no ams_model/ams_series
        v = m.ams_slot_active.labels(**labels, ams_id="0", slot_id="1")._value.get()
        assert v == 1.0


class TestAmsGen2DryingTelemetry:
    """Test Gen2 drying telemetry metrics from ams_info bits."""

    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _ams_info(
        self, ams_type: int = 3, dry_heater: int = 2, fan1: int = 1, fan2: int = 2, sub: int = 5
    ) -> int:
        return ams_type | (dry_heater << 4) | (fan1 << 18) | (fan2 << 20) | (sub << 22)

    def test_heater_state_emitted(self) -> None:
        m = self._m()
        info = self._ams_info(ams_type=3, dry_heater=2)
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": info}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v = m.ams_heater_state_info.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", state="2"
        )._value.get()
        assert v == 1.0

    def test_dry_fan_status_emitted(self) -> None:
        m = self._m()
        info = self._ams_info(ams_type=4, fan1=3, fan2=1)
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": info}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v1 = m.ams_dry_fan_status.labels(
            **labels, ams_id="0", ams_model="ams_ht", ams_series="gen_2", fan_id="fan1"
        )._value.get()
        v2 = m.ams_dry_fan_status.labels(
            **labels, ams_id="0", ams_model="ams_ht", ams_series="gen_2", fan_id="fan2"
        )._value.get()
        assert v1 == 3.0
        assert v2 == 1.0

    def test_dry_sub_status_emitted(self) -> None:
        m = self._m()
        info = self._ams_info(ams_type=3, sub=7)
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": info}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v = m.ams_dry_sub_status_info.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", state="7"
        )._value.get()
        assert v == 1.0

    def test_drying_metrics_not_emitted_without_ams_info(self) -> None:
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006ABCDEF"}]}}},
        )
        m.update_from_snapshot(snap)
        # No ams_info -> no drying telemetry metrics
        assert len(m.ams_heater_state_info._metrics) == 0
        assert len(m.ams_dry_fan_status._metrics) == 0
        assert len(m.ams_dry_sub_status_info._metrics) == 0

    def test_drying_metrics_clear_on_next_update(self) -> None:
        m = self._m()
        info = self._ams_info(ams_type=3, dry_heater=1)
        snap1 = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": info}]}}},
        )
        snap2 = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006ABCDEF"}]}}},
        )
        m.update_from_snapshot(snap1)
        assert len(m.ams_heater_state_info._metrics) == 1
        m.update_from_snapshot(snap2)
        assert len(m.ams_heater_state_info._metrics) == 0


# ---------------------------------------------------------------------------
# Additional metric emission assertions: info metrics and fan/heater/sub-status
# (v0.1.24 supplement)
# ---------------------------------------------------------------------------

class TestAmsUnitInfoMetricAdditional:
    """Additional assertions for bambulab_ams_unit_info emission."""

    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _labels(self) -> dict:
        return {"printer_name": "test", "serial": "SN123"}

    def test_ams_unit_info_ams_info_override_gen2(self) -> None:
        """ams_info with type=3 (ams_2_pro, gen_2) emits correct unit info labels."""
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "006TESTSERIAL", "ams_info": 3}]}}},
        )
        m.update_from_snapshot(snap)
        labels = self._labels()
        v = m.ams_unit_info.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2"
        )._value.get()
        assert v == 1.0

    def test_ams_unit_info_two_units(self) -> None:
        """Two AMS units both get their own info metric entry."""
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [
                {"id": "0", "sn": "006UNIT0"},
                {"id": "1", "sn": "19FUNIT1"},
            ]}}},
        )
        m.update_from_snapshot(snap)
        labels = self._labels()
        assert len(m.ams_unit_info._metrics) == 2
        v0 = m.ams_unit_info.labels(
            **labels, ams_id="0", ams_model="ams_1", ams_series="gen_1"
        )._value.get()
        v1 = m.ams_unit_info.labels(
            **labels, ams_id="1", ams_model="ams_ht", ams_series="gen_2"
        )._value.get()
        assert v0 == 1.0
        assert v1 == 1.0

    def test_ams_unit_info_no_serial_field(self) -> None:
        """Unit with no sn field still emits AMS unit info."""
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = self._labels()
        v = m.ams_unit_info.labels(
            **labels, ams_id="0", ams_model="unknown", ams_series="unknown"
        )._value.get()
        assert v == 1.0

    def test_ams_unit_info_lite_serial(self) -> None:
        """03C prefix maps to ams_lite, gen_1."""
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "sn": "03CLITEUNIT"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = self._labels()
        v = m.ams_unit_info.labels(
            **labels, ams_id="0", ams_model="ams_lite", ams_series="gen_1"
        )._value.get()
        assert v == 1.0


class TestAmsGen2DryingTelemetryAdditional:
    """Additional metric emission assertions for Gen2 drying telemetry."""

    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _ams_info(
        self, ams_type: int = 3, dry_heater: int = 0, fan1: int = 0, fan2: int = 0, sub: int = 0
    ) -> int:
        return ams_type | (dry_heater << 4) | (fan1 << 18) | (fan2 << 20) | (sub << 22)

    def test_heater_state_zero_is_emitted(self) -> None:
        """dry_heater_state=0 still gets emitted (it's a valid state)."""
        m = self._m()
        info = self._ams_info(ams_type=3, dry_heater=0)
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": info}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v = m.ams_heater_state_info.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", state="0"
        )._value.get()
        assert v == 1.0

    def test_fan_status_zero_is_emitted(self) -> None:
        """fan1=0, fan2=0 still emitted as 0.0 values."""
        m = self._m()
        info = self._ams_info(ams_type=3, fan1=0, fan2=0)
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": info}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v1 = m.ams_dry_fan_status.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", fan_id="fan1"
        )._value.get()
        v2 = m.ams_dry_fan_status.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", fan_id="fan2"
        )._value.get()
        assert v1 == 0.0
        assert v2 == 0.0

    def test_ams_info_zero_does_not_emit_drying_metrics(self) -> None:
        """ams_info=0 is treated as absent (ams_info_raw > 0 guard), no drying metrics."""
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": 0}]}}},
        )
        m.update_from_snapshot(snap)
        assert len(m.ams_heater_state_info._metrics) == 0
        assert len(m.ams_dry_fan_status._metrics) == 0
        assert len(m.ams_dry_sub_status_info._metrics) == 0

    def test_ams_info_string_emits_drying_metrics(self) -> None:
        """String ams_info should be parsed and emit drying metrics."""
        m = self._m()
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [{"id": "0", "ams_info": "0x33"}]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v = m.ams_heater_state_info.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", state="3"
        )._value.get()
        assert v == 1.0

    def test_two_ams_units_both_emit_drying_metrics(self) -> None:
        """Both AMS units with ams_info should emit their own drying metrics."""
        m = self._m()
        info0 = self._ams_info(ams_type=3, dry_heater=1)
        info1 = self._ams_info(ams_type=4, dry_heater=2)
        snap = PrinterSnapshot(
            connected=True,
            raw={"print": {"ams": {"ams": [
                {"id": "0", "ams_info": info0},
                {"id": "1", "ams_info": info1},
            ]}}},
        )
        m.update_from_snapshot(snap)
        labels = {"printer_name": "test", "serial": "SN123"}
        v0 = m.ams_heater_state_info.labels(
            **labels, ams_id="0", ams_model="ams_2_pro", ams_series="gen_2", state="1"
        )._value.get()
        v1 = m.ams_heater_state_info.labels(
            **labels, ams_id="1", ams_model="ams_ht", ams_series="gen_2", state="2"
        )._value.get()
        assert v0 == 1.0
        assert v1 == 1.0


# ---------------------------------------------------------------------------
# Label regression: existing AMS metrics must NOT have ams_model/ams_series
# (v0.1.24 supplement – comprehensive regression suite)
# ---------------------------------------------------------------------------

class TestAmsExistingMetricLabelRegressionComprehensive:
    """Comprehensive regression: no existing AMS metric has gained ams_model/ams_series labels."""

    def _m(self) -> ExporterMetrics:
        return ExporterMetrics(printer_name="test", serial="SN123")

    def _snap_with_ams(self) -> PrinterSnapshot:
        return PrinterSnapshot(
            connected=True,
            raw={
                "print": {
                    "ams": {
                        "ams": [
                            {
                                "id": "0",
                                "sn": "19FABCDEF",
                                "humidity": "3",
                                "humidity_raw": "55",
                                "temp": "23",
                                "tray_now": "1",  # active tray within this unit
                                "tray": [
                                    {"id": "0", "remain": "80", "tray_type": "PLA", "tray_color": "FFFFFFFF"},
                                    {"id": "1", "remain": "60", "tray_type": "PETG", "tray_color": "000000FF"},
                                ],
                            }
                        ],
                    }
                }
            },
        )

    def _base_labels(self) -> dict:
        return {"printer_name": "test", "serial": "SN123"}

    def test_ams_unit_humidity_only_needs_ams_id(self) -> None:
        m = self._m()
        m.update_from_snapshot(self._snap_with_ams())
        labels = self._base_labels()
        v = m.ams_unit_humidity.labels(**labels, ams_id="0")._value.get()
        assert v == 55.0

    def test_ams_unit_humidity_index_only_needs_ams_id(self) -> None:
        m = self._m()
        m.update_from_snapshot(self._snap_with_ams())
        labels = self._base_labels()
        v = m.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get()
        assert v == 3.0

    def test_ams_unit_temperature_only_needs_ams_id(self) -> None:
        m = self._m()
        m.update_from_snapshot(self._snap_with_ams())
        labels = self._base_labels()
        v = m.ams_unit_temperature_celsius.labels(**labels, ams_id="0")._value.get()
        assert v == 23.0

    def test_ams_slot_active_only_needs_ams_id_and_slot_id(self) -> None:
        m = self._m()
        m.update_from_snapshot(self._snap_with_ams())
        labels = self._base_labels()
        v = m.ams_slot_active.labels(**labels, ams_id="0", slot_id="1")._value.get()
        assert v == 1.0

    def test_ams_slot_remaining_only_needs_ams_id_and_slot_id(self) -> None:
        m = self._m()
        m.update_from_snapshot(self._snap_with_ams())
        labels = self._base_labels()
        v = m.ams_slot_remaining_percent.labels(**labels, ams_id="0", slot_id="0")._value.get()
        assert v == 80.0

    def test_ams_slot_tray_info_has_type_and_color(self) -> None:
        m = self._m()
        m.update_from_snapshot(self._snap_with_ams())
        labels = self._base_labels()
        v = m.ams_slot_tray_info.labels(**labels, ams_id="0", slot_id="0", tray_type="PLA", tray_color="FFFFFFFF")._value.get()
        assert v == 1.0

    def test_ams_status_id_only_base_labels(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_status": 1}))
        labels = self._base_labels()
        v = m.ams_status_id.labels(**labels)._value.get()
        assert v == 1.0

    def test_ams_rfid_status_id_only_base_labels(self) -> None:
        m = self._m()
        m.update_from_snapshot(_snap({"ams_rfid_status": 3}))
        labels = self._base_labels()
        v = m.ams_rfid_status_id.labels(**labels)._value.get()
        assert v == 3.0
