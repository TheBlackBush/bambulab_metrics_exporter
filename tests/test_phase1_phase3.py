"""Tests for Phase 1 (binary sensors, usage_hours, sdcard) and Phase 3 (stage info) metrics."""
from __future__ import annotations

import math

from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot, STG_CUR_NAMES


def _snap(print_block: dict | None = None) -> PrinterSnapshot:
    return PrinterSnapshot(connected=True, raw={"print": print_block or {}})


def _metrics() -> ExporterMetrics:
    return ExporterMetrics(printer_name="test", serial="SN123")


def _get(m: ExporterMetrics, gauge_name: str, extra_labels: dict | None = None) -> float:
    labels = {"printer_name": "test", "serial": "SN123"}
    if extra_labels:
        labels.update(extra_labels)
    gauge = getattr(m, gauge_name)
    return gauge.labels(**labels)._value.get()


class TestUsageHours:
    def test_usage_hours_set(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"usage_hours": 1234.5}))
        assert _get(m, "usage_hours") == 1234.5

    def test_usage_hours_none(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({}))
        assert math.isnan(_get(m, "usage_hours"))


class TestDoorOpen:
    def test_door_open_true(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"door_open": True}))
        assert _get(m, "door_open") == 1.0

    def test_door_open_false(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"door_open": False}))
        assert _get(m, "door_open") == 0.0

    def test_door_open_from_home_flag(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"home_flag": 0x00800000}))
        assert _get(m, "door_open") == 1.0

    def test_door_closed_from_home_flag(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"home_flag": 0x0}))
        assert _get(m, "door_open") == 0.0

    def test_door_open_from_stat_hex(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"stat": "46A58008"}))
        assert _get(m, "door_open") == 1.0

    def test_door_closed_from_stat_hex(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"stat": "46258008"}))
        assert _get(m, "door_open") == 0.0

    def test_door_open_model_preference_x1_home_flag_over_stat(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"model_id": "X1C", "home_flag": 0x00800000, "stat": "46258008"}))
        assert _get(m, "door_open") == 1.0

    def test_door_open_model_preference_non_x1_stat_over_home_flag(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"model_id": "H2D", "home_flag": 0x00800000, "stat": "46258008"}))
        assert _get(m, "door_open") == 0.0

    def test_door_open_none(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({}))
        assert math.isnan(_get(m, "door_open"))


class TestFilamentLoaded:
    def test_filament_loaded(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"ctt": 1}))
        assert _get(m, "filament_loaded") == 1.0

    def test_filament_not_loaded(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"ctt": 0}))
        assert _get(m, "filament_loaded") == 0.0

    def test_filament_none(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({}))
        assert math.isnan(_get(m, "filament_loaded"))


class TestTimelapseEnabled:
    def test_timelapse_bool_true(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"timelapse": True}))
        assert _get(m, "timelapse_enabled") == 1.0

    def test_timelapse_bool_false(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"timelapse": False}))
        assert _get(m, "timelapse_enabled") == 0.0

    def test_timelapse_string(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"timelapse": "enable"}))
        assert _get(m, "timelapse_enabled") == 1.0

    def test_timelapse_int(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"timelapse": 1}))
        assert _get(m, "timelapse_enabled") == 1.0


class TestSdcardStatus:
    def test_sdcard_from_bool(self) -> None:
        snap = _snap({"sdcard": True})
        assert snap.sdcard_status == "present"

    def test_home_flag_state_metric(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"home_flag": 0x00800300}))
        assert _get(m, "home_flag_state", {"flag": "door_open"}) == 1.0
        assert _get(m, "home_flag_state", {"flag": "sd_card_present"}) == 1.0
        assert _get(m, "home_flag_state", {"flag": "sd_card_abnormal"}) == 1.0

    def test_stat_flag_state_metric(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"stat": "46A58008"}))
        assert _get(m, "stat_flag_state", {"flag": "door_open"}) == 1.0

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
        m = _metrics()
        m.update_from_snapshot(_snap({"sdcard": True}))
        labels = {"printer_name": "test", "serial": "SN123", "status": "present"}
        assert m.sdcard_status_info.labels(**labels)._value.get() == 1.0


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
        m = _metrics()
        m.update_from_snapshot(_snap({"stg_cur": 7}))
        assert _get(m, "stg_cur") == 7.0

    def test_stage_info_metric(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"stg_cur": 7}))
        labels = {"printer_name": "test", "serial": "SN123", "stage": "heating_hotend"}
        assert m.print_stage_info.labels(**labels)._value.get() == 1.0

    def test_stage_info_clears(self) -> None:
        m = _metrics()
        m.update_from_snapshot(_snap({"stg_cur": 0}))
        m.update_from_snapshot(_snap({"stg_cur": 1}))
        labels = {"printer_name": "test", "serial": "SN123", "stage": "bed_leveling"}
        assert m.print_stage_info.labels(**labels)._value.get() == 1.0


class TestStgCurMapping:
    def test_all_known_stages(self) -> None:
        """Ensure all documented stage IDs map correctly."""
        assert STG_CUR_NAMES[0] == "printing"
        assert STG_CUR_NAMES[13] == "homing_toolhead"
        assert STG_CUR_NAMES[23] == "motor_noise_calibration"
        assert STG_CUR_NAMES[34] == "standby"
        assert STG_CUR_NAMES[35] == "idle"
        assert STG_CUR_NAMES[-1] == "idle"
