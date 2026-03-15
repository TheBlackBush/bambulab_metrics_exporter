from dataclasses import dataclass
from typing import Any

from bambulab_metrics_exporter.flags import (
    DOOR_OPEN_MASK,
    SD_CARD_ABNORMAL_MASK,
    SD_CARD_PRESENT_MASK,
    decode_home_flags,
    decode_stat_flags,
    to_hex_int,
    to_int,
)


X1_HOMEFLAG_MODELS = {"X1", "X1C"}
PRODUCT_NAME_TO_PRINTER: dict[str, str] = {
    "bambu lab a1": "A1",
    "bambu lab a1 mini": "A1MINI",
    "bambu lab p1p": "P1P",
    "bambu lab p1s": "P1S",
    "bambu lab p2s": "P2S",
    "bambu lab h2c": "H2C",
    "bambu lab h2d": "H2D",
    "bambu lab h2d pro": "H2DPRO",
    "bambu lab h2s": "H2S",
}


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


# Backward-compatible aliases for legacy tests/importers.
_to_int = to_int
_to_hex_int = to_hex_int


def _normalize_product_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


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
    def modules(self) -> list[dict[str, Any]]:
        candidates: list[Any] = []
        candidates.append(self.raw.get("module"))
        info = self.raw.get("info")
        if isinstance(info, dict):
            candidates.append(info.get("module"))
        candidates.append(self.print_block.get("module"))

        for candidate in candidates:
            if isinstance(candidate, list):
                return [x for x in candidate if isinstance(x, dict)]
        return []

    @property
    def printer_type(self) -> str | None:
        modules = self.modules
        for mod in modules:
            mapped = PRODUCT_NAME_TO_PRINTER.get(_normalize_product_name(mod.get("product_name")))
            if mapped:
                return mapped

        ap_module = next(
            (
                m
                for m in modules
                if isinstance(m.get("hw_ver"), str) and m.get("hw_ver", "").startswith("AP0")
            ),
            None,
        )
        if isinstance(ap_module, dict):
            hw_ver = str(ap_module.get("hw_ver", "")).strip().upper()
            project_name = str(ap_module.get("project_name", "")).strip().upper()
            if hw_ver == "AP02":
                return "X1E"
            if project_name == "N1":
                return "A1MINI"
            if hw_ver == "AP04":
                if project_name == "C11":
                    return "P1P"
                if project_name == "C12":
                    return "P1S"
            if hw_ver == "AP05":
                if project_name == "N2S":
                    return "A1"
                if project_name == "":
                    return "X1C"

        dtype = to_int(self.print_block.get("device", {}).get("type"))
        mapping = {
            0: "X1",
            1: "X1C",
            2: "P1P",
            3: "P1S",
            4: "A1",
            5: "A1MINI",
        }
        if dtype in mapping:
            return mapping[dtype]

        model_id = self.print_block.get("model_id")
        if isinstance(model_id, str) and model_id.strip():
            return model_id.strip().upper().replace(" ", "")
        return None

    @property
    def model_name(self) -> str | None:
        return self.printer_type

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
        value = to_int(self.print_block.get("mc_stage"))
        return float(value) if value is not None else None

    @property
    def mc_print_sub_stage(self) -> float | None:
        value = to_int(self.print_block.get("mc_print_sub_stage"))
        return float(value) if value is not None else None

    @property
    def print_real_action(self) -> float | None:
        value = to_int(self.print_block.get("print_real_action"))
        return float(value) if value is not None else None

    @property
    def print_gcode_action(self) -> float | None:
        value = to_int(self.print_block.get("print_gcode_action"))
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
        value = to_int(self.print_block.get("ams_status"))
        return float(value) if value is not None else None

    @property
    def ams_rfid_status(self) -> float | None:
        value = to_int(self.print_block.get("ams_rfid_status"))
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
        value = to_int(self.print_block.get("spd_lvl"))
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
        return to_int(self.print_block.get("mc_print_error_code"))

    @property
    def print_error(self) -> float | None:
        value = to_int(self.print_block.get("print_error"))
        return float(value) if value is not None else None

    @property
    def ap_err(self) -> float | None:
        value = to_int(self.print_block.get("ap_err"))
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
    def home_flags(self) -> dict[str, bool | None]:
        return decode_home_flags(self.print_block.get("home_flag"))

    @property
    def stat_flags(self) -> dict[str, bool | None]:
        return decode_stat_flags(self.print_block.get("stat"))

    @property
    def sdcard_status(self) -> str | None:
        """SD card status from direct field or home_flag bits."""
        value = self.print_block.get("sdcard")
        if isinstance(value, bool):
            return "present" if value else "absent"
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

        hf = to_int(self.print_block.get("home_flag"))
        if hf is None:
            return None

        present = (hf & SD_CARD_PRESENT_MASK) != 0
        abnormal = (hf & SD_CARD_ABNORMAL_MASK) != 0
        if present and abnormal:
            return "abnormal"
        return "present" if present else "absent"

    @property
    def door_open(self) -> float | None:
        """1.0 if door is open, 0.0 if closed.

        Source selection mirrors upstream behavior:
        - Direct `door_open` value if present
        - X1/X1C prefer `home_flag` bitmask
        - Other models prefer `stat` hex bitmask
        - Fallback to whichever bitmask source is available
        """
        val = self.print_block.get("door_open")
        if isinstance(val, bool):
            return 1.0 if val else 0.0
        if isinstance(val, (int, float)):
            return 1.0 if val else 0.0

        home_flag = to_int(self.print_block.get("home_flag"))
        stat_flag = to_hex_int(self.print_block.get("stat"))
        ptype = self.printer_type

        if ptype in X1_HOMEFLAG_MODELS:
            if home_flag is not None:
                return 1.0 if (home_flag & DOOR_OPEN_MASK) else 0.0
            if stat_flag is not None:
                return 1.0 if (stat_flag & DOOR_OPEN_MASK) else 0.0
            return None

        if stat_flag is not None:
            return 1.0 if (stat_flag & DOOR_OPEN_MASK) else 0.0
        if home_flag is not None:
            return 1.0 if (home_flag & DOOR_OPEN_MASK) else 0.0
        return None

    @property
    def filament_loaded(self) -> float | None:
        """1.0 if filament is loaded (extruder has filament). From ctt or ams."""
        val = to_int(self.print_block.get("ctt"))
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
        return to_int(self.print_block.get("stg_cur"))

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
