from dataclasses import dataclass
from typing import Any


STG_CUR_NAMES: dict[int, str] = {
    0: "printing",
    1: "bed_leveling",
    2: "heatbed_preheating",
    3: "sweeping_xy_mech_mode",
    4: "changing_filament",
    5: "m400_pause",
    6: "filament_runout_pause",
    7: "heating_hotend",
    8: "calibrating_extrusion",
    9: "scanning_bed_surface",
    10: "inspecting_first_layer",
    11: "identifying_build_plate",
    12: "calibrating_micro_lidar",
    13: "homing_toolhead",
    14: "cleaning_nozzle_tip",
    15: "checking_extruder_temp",
    16: "paused_user",
    17: "paused_front_cover",
    18: "calibrating_lidar",
    19: "calibrating_micro_lidar_2",
    20: "toolhead_shell_off_pause",
    21: "nozzle_hub_clog_pause",
    22: "checking_foreign_body",
    23: "motor_noise_calibration",
    24: "paused_nozzle_temperature_malfunction",
    25: "paused_heat_bed_temperature_malfunction",
    26: "filament_unloading",
    27: "skip_step_pause",
    28: "filament_loading",
    29: "motor_noise_showoff",
    30: "pressure_advance_calibrating",
    31: "auto_bed_leveling_wip",
    32: "change_cartridge",
    33: "vibration_compensation_calibrating",
    34: "standby",
    35: "idle",
    255: "unknown",
    -1: "idle",
}


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


@dataclass(slots=True)
class PrinterSnapshot:
    connected: bool
    raw: dict[str, Any]

    @property
    def print_block(self) -> dict[str, Any]:
        block = self.raw.get("print", {})
        return block if isinstance(block, dict) else {}

    @property
    def gcode_state(self) -> str:
        value = self.print_block.get("gcode_state", "UNKNOWN")
        return str(value).upper()

    @property
    def name(self) -> str | None:
        # Some firmware reports printer name in mc_print_line or other fields,
        # but the standard field is often dev_name or simply not in pushall.
        # We'll check dev_name first.
        return self.print_block.get("dev_name")

    @property
    def model_name(self) -> str | None:
        dtype = _to_int(self.print_block.get("device", {}).get("type"))
        if dtype is None:
             # Fallback to model_id if available
             return self.print_block.get("model_id")
        
        mapping = {
            0: "X1",
            1: "X1C",
            2: "P1P",
            3: "P1S",
            4: "A1",
            5: "A1 Mini",
        }
        return mapping.get(dtype)

    @property
    def progress_percent(self) -> float | None:
        return _to_float(self.print_block.get("mc_percent"))

    @property
    def remaining_seconds(self) -> float | None:
        value = _to_float(self.print_block.get("mc_remaining_time"))
        return value * 60.0 if value is not None else None

    @property
    def nozzle_temp(self) -> float | None:
        return _to_float(self.print_block.get("nozzle_temper"))

    @property
    def nozzle_target_temp(self) -> float | None:
        return _to_float(self.print_block.get("nozzle_target_temper"))

    @property
    def nozzle_diameter(self) -> float | None:
        return _to_float(self.print_block.get("nozzle_diameter"))

    @property
    def bed_temp(self) -> float | None:
        return _to_float(self.print_block.get("bed_temper"))

    @property
    def bed_target_temp(self) -> float | None:
        return _to_float(self.print_block.get("bed_target_temper"))

    @property
    def chamber_temp(self) -> float | None:
        value = _to_float(self.print_block.get("chamber_temper"))
        if value is not None:
            return value
        nested = self.print_block.get("device", {})
        if isinstance(nested, dict):
            ctc = nested.get("ctc", {})
            if isinstance(ctc, dict):
                info = ctc.get("info", {})
                if isinstance(info, dict):
                    return _to_float(info.get("temp"))
        return None

    @property
    def layer_current(self) -> float | None:
        return _to_float(self.print_block.get("layer_num"))

    @property
    def layer_total(self) -> float | None:
        return _to_float(self.print_block.get("total_layer_num"))

    @property
    def layer_progress_percent(self) -> float | None:
        current = self.layer_current
        total = self.layer_total
        if current is None or total is None or total <= 0:
            return None
        return (current / total) * 100.0

    @property
    def fan_gear(self) -> float | None:
        value = _to_float(self.print_block.get("fan_gear"))
        if value is None:
            value = _to_float(self.print_block.get("big_fan1_speed"))
        if value is None:
            return None
        if value <= 15:
            return (value / 15.0) * 100.0
        return value

    @property
    def fan_gear_raw(self) -> float | None:
        return _to_float(self.print_block.get("fan_gear"))

    @property
    def fan_big_1_percent(self) -> float | None:
        return _to_float(self.print_block.get("big_fan1_speed"))

    @property
    def fan_big_2_percent(self) -> float | None:
        return _to_float(self.print_block.get("big_fan2_speed"))

    @property
    def fan_cooling_percent(self) -> float | None:
        return _to_float(self.print_block.get("cooling_fan_speed"))

    @property
    def fan_heatbreak_percent(self) -> float | None:
        return _to_float(self.print_block.get("heatbreak_fan_speed"))

    @property
    def mc_stage(self) -> float | None:
        value = _to_int(self.print_block.get("mc_stage"))
        return float(value) if value is not None else None

    @property
    def mc_print_sub_stage(self) -> float | None:
        value = _to_int(self.print_block.get("mc_print_sub_stage"))
        return float(value) if value is not None else None

    @property
    def print_real_action(self) -> float | None:
        value = _to_int(self.print_block.get("print_real_action"))
        return float(value) if value is not None else None

    @property
    def print_gcode_action(self) -> float | None:
        value = _to_int(self.print_block.get("print_gcode_action"))
        return float(value) if value is not None else None

    @property
    def mc_print_stage_name(self) -> str | None:
        value = self.print_block.get("mc_print_stage")
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
        return None

    @property
    def wifi_signal(self) -> float | None:
        value = self.print_block.get("wifi_signal")
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
        if isinstance(value, str):
            text = value.strip().lower()
            if text.endswith("dbm"):
                return _to_float(text[:-3].strip())
        return None

    @property
    def online_ahb(self) -> float | None:
        online = self.print_block.get("online")
        if isinstance(online, dict):
            value = online.get("ahb")
            if isinstance(value, bool):
                return 1.0 if value else 0.0
        return None

    @property
    def online_ext(self) -> float | None:
        online = self.print_block.get("online")
        if isinstance(online, dict):
            value = online.get("ext")
            if isinstance(value, bool):
                return 1.0 if value else 0.0
        return None

    @property
    def ams_status(self) -> float | None:
        value = _to_int(self.print_block.get("ams_status"))
        return float(value) if value is not None else None

    @property
    def ams_rfid_status(self) -> float | None:
        value = _to_int(self.print_block.get("ams_rfid_status"))
        return float(value) if value is not None else None


    @property
    def queue_total(self) -> float | None:
        return _to_float(self.print_block.get("queue_total"))

    @property
    def queue_est(self) -> float | None:
        return _to_float(self.print_block.get("queue_est"))

    @property
    def queue_number(self) -> float | None:
        return _to_float(self.print_block.get("queue_number"))

    @property
    def queue_status(self) -> float | None:
        return _to_float(self.print_block.get("queue_sts"))

    @property
    def queue_position(self) -> float | None:
        return _to_float(self.print_block.get("queue"))

    @property
    def spd_lvl(self) -> float | None:
        value = _to_int(self.print_block.get("spd_lvl"))
        return float(value) if value is not None else None

    @property
    def spd_mag(self) -> float | None:
        return _to_float(self.print_block.get("spd_mag"))

    @property
    def ams_tray_now(self) -> str | None:
        ams = self.print_block.get("ams")
        if isinstance(ams, dict):
            value = ams.get("tray_now")
            if isinstance(value, str):
                return value
        return None
    @property
    def print_error_code(self) -> int | None:
        return _to_int(self.print_block.get("mc_print_error_code"))

    @property
    def print_error(self) -> float | None:
        value = _to_int(self.print_block.get("print_error"))
        return float(value) if value is not None else None

    @property
    def ap_err(self) -> float | None:
        value = _to_int(self.print_block.get("ap_err"))
        return float(value) if value is not None else None

    @property
    def subtask_name(self) -> str | None:
        value = self.print_block.get("subtask_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @property
    def fail_reason(self) -> str | None:
        value = self.print_block.get("fail_reason")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @property
    def sn(self) -> str | None:
        value = self.print_block.get("sn")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @property
    def lights_report(self) -> list[dict[str, Any]]:
        value = self.print_block.get("lights_report")
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        return []

    @property
    def xcam_flags(self) -> dict[str, float]:
        xcam = self.print_block.get("xcam")
        if not isinstance(xcam, dict):
            return {}
        out: dict[str, float] = {}
        keys = [
            "allow_skip_parts",
            "buildplate_marker_detector",
            "first_layer_inspector",
            "print_halt",
            "printing_monitor",
            "spaghetti_detector",
        ]
        for key in keys:
            val = xcam.get(key)
            if isinstance(val, bool):
                out[key] = 1.0 if val else 0.0
        return out
    @property
    def usage_hours(self) -> float | None:
        return _to_float(self.print_block.get("usage_hours"))

    @property
    def sdcard_status(self) -> str | None:
        """SD card status from home_flag or direct field."""
        value = self.print_block.get("sdcard")
        if isinstance(value, bool):
            return "present" if value else "absent"
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
        # Also check home_flag bitmask bit for sdcard
        hf = _to_int(self.print_block.get("home_flag"))
        if hf is not None:
            # bit 9 (0x200) = sdcard present in ha-bambulab
            return "present" if (hf & 0x200) else "absent"
        return None

    @property
    def door_open(self) -> float | None:
        """1.0 if door is open, 0.0 if closed. From home_flag bit or direct field."""
        val = self.print_block.get("door_open")
        if isinstance(val, bool):
            return 1.0 if val else 0.0
        if isinstance(val, (int, float)):
            return 1.0 if val else 0.0
        hf = _to_int(self.print_block.get("home_flag"))
        if hf is not None:
            # bit 1 (0x2) = door open in ha-bambulab
            return 1.0 if (hf & 0x2) else 0.0
        return None

    @property
    def filament_loaded(self) -> float | None:
        """1.0 if filament is loaded (extruder has filament). From ctt or ams."""
        val = _to_int(self.print_block.get("ctt"))
        if val is not None:
            return 1.0 if val else 0.0
        # Also check ams.tray_now != 255 as proxy
        return None

    @property
    def timelapse_enabled(self) -> float | None:
        """1.0 if timelapse recording is enabled."""
        val = self.print_block.get("timelapse")
        if isinstance(val, bool):
            return 1.0 if val else 0.0
        if isinstance(val, str):
            return 1.0 if val.lower() in ("true", "1", "on", "enable") else 0.0
        if isinstance(val, (int, float)):
            return 1.0 if val else 0.0
        return None

    @property
    def stg_cur(self) -> int | None:
        """Current print stage ID."""
        return _to_int(self.print_block.get("stg_cur"))

    @property
    def stg_cur_name(self) -> str | None:
        """Human-readable name for the current print stage."""
        stage_id = self.stg_cur
        if stage_id is None:
            return None
        return STG_CUR_NAMES.get(stage_id, f"unknown_{stage_id}")

    @property
    def ams_units(self) -> list[dict[str, Any]]:
        ams = self.print_block.get("ams", {})
        if not isinstance(ams, dict):
            return []
        units = ams.get("ams")
        if isinstance(units, list):
            return [x for x in units if isinstance(x, dict)]
        return []
