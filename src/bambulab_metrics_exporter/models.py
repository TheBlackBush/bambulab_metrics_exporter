from dataclasses import dataclass
from typing import Any

from bambulab_metrics_exporter.flags import (
    HOME_FLAG_MASKS,
    STAT_FLAG_MASKS,
    decode_home_flags,
    decode_stat_flags,
    to_hex_int,
    to_int,
)


X1_HOMEFLAG_MODELS = {"X1", "X1C"}

# product_name → model (priority 1 in resolver)
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
    "bambu lab x1": "X1",
    "bambu lab x1 carbon": "X1C",
    "bambu lab x1e": "X1E",
}

# (hw_ver, project_name) → model (priority 2 in resolver, AP-module path)
_HW_PROJECT_TO_PRINTER: dict[tuple[str, str], str] = {
    ("AP02", ""): "X1E",
    ("AP03", "N1"): "A1MINI",
    ("AP04", "C11"): "P1P",
    ("AP04", "C12"): "P1S",
    ("AP05", "N2S"): "A1",
    ("AP05", ""): "X1C",
}

# SN-prefix → model (priority 3 – only clearly confirmed prefixes)
_SN_PREFIX_TO_PRINTER: dict[str, str] = {
    "00W": "X1",
    "00M": "X1C",
    "03W": "X1E",
    "01S": "P1P",
    "01P": "P1S",
    "030": "A1MINI",
    "039": "A1",
    "22E": "P2S",
    "093": "H2S",
    "094": "H2D",
}

# legacy device.type → model (priority 4)
_DEVICE_TYPE_TO_PRINTER: dict[int, str] = {
    0: "X1",
    1: "X1C",
    2: "P1P",
    3: "P1S",
    4: "A1",
    5: "A1MINI",
}


# AMS serial prefix → model name
AMS_SERIAL_PREFIX_TO_MODEL: dict[str, str] = {
    "006": "ams_1",
    "03C": "ams_lite",
    "19C": "ams_2_pro",
    "19F": "ams_ht",
}

# AMS model → series
AMS_MODEL_TO_SERIES: dict[str, str] = {
    "ams_1": "gen_1",
    "ams_lite": "gen_1",
    "ams_2_pro": "gen_2",
    "ams_ht": "gen_2",
}

# ams_info bits 0-3 ams_type → model name (when valid / nonzero)
AMS_TYPE_TO_MODEL: dict[int, str] = {
    1: "ams_1",
    2: "ams_lite",
    3: "ams_2_pro",
    4: "ams_ht",
}


def _extract_ams_info(ams_unit: dict[str, Any]) -> int | None:
    """Extract AMS info bitfield from known payload keys.

    Supports both:
    - ams_info: int
    - info: str/int (seen in some cloud payloads)
    """
    raw = ams_unit.get("ams_info", ams_unit.get("info"))

    if isinstance(raw, int):
        return raw

    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None

        # Some firmware/cloud payloads send `info` as bare hex string (e.g. "1001").
        # For digit-only strings, try both decimal and hex and prefer a value whose
        # low nibble maps to a known AMS type.
        if s.isdigit():
            candidates: list[int] = []
            try:
                candidates.append(int(s, 10))
            except ValueError:
                pass
            try:
                candidates.append(int(s, 16))
            except ValueError:
                pass

            for candidate in candidates:
                ams_type = candidate & 0xF
                if candidate > 0 and ams_type in AMS_TYPE_TO_MODEL:
                    return candidate

            return candidates[0] if candidates else None

        if s.lower().startswith("0x"):
            s = s[2:]

        if all(ch in "0123456789abcdefABCDEF" for ch in s):
            try:
                return int(s, 16)
            except ValueError:
                return None

    return None


def resolve_ams_model(ams_unit: dict[str, Any]) -> str:
    """Resolve AMS model name for a single AMS unit dict.

    Precedence:
    1. ams_info/info bits 0-3 (ams_type) when valid (nonzero and known)
    2. AMS serial prefix mapping
    3. 'unknown' fallback
    """
    # 1. ams_info ams_type bits 0-3
    ams_info_raw = _extract_ams_info(ams_unit)
    if isinstance(ams_info_raw, int) and ams_info_raw > 0:
        ams_type = ams_info_raw & 0xF  # bits 0-3
        if ams_type in AMS_TYPE_TO_MODEL:
            return AMS_TYPE_TO_MODEL[ams_type]

    # 2. AMS serial prefix (support multiple key names)
    ams_serial = ams_unit.get("sn", ams_unit.get("serial", ""))
    if isinstance(ams_serial, str) and ams_serial.strip():
        serial_upper = ams_serial.strip().upper()
        for prefix, model in AMS_SERIAL_PREFIX_TO_MODEL.items():
            if serial_upper.startswith(prefix.upper()):
                return model

    # 3. Fallback
    return "unknown"


def resolve_ams_series(ams_model: str) -> str:
    """Resolve AMS generation/series from model name."""
    return AMS_MODEL_TO_SERIES.get(ams_model, "unknown")


def parse_ams_info(ams_info: int) -> dict[str, int]:
    """Parse ams_info bitmask into structured fields.

    Bit layout:
      bits 0-3:   ams_type
      bits 4-7:   dry/heater state
      bits 18-19: dry fan1 state
      bits 20-21: dry fan2 state
      bits 22-25: dry sub-status
    """
    return {
        "ams_type": ams_info & 0xF,
        "dry_heater_state": (ams_info >> 4) & 0xF,
        "dry_fan1": (ams_info >> 18) & 0x3,
        "dry_fan2": (ams_info >> 20) & 0x3,
        "dry_sub_status": (ams_info >> 22) & 0xF,
    }


# AMS status code → human-readable name (from synman parseAMSStatus)
AMS_STATUS_NAMES: dict[int, str] = {
    0: "idle",
    1: "filament_change",
    2: "rfid_identifying",
    3: "assist",
    4: "calibration",
    0x100: "self_check",
    0x200: "debug",
    0xFF00: "unknown_device",
}

# AMS RFID status code → human-readable name (from synman parseRFIDStatus)
AMS_RFID_STATUS_NAMES: dict[int, str] = {
    0: "idle",
    1: "reading",
    2: "writing",
    3: "identifying",
    4: "close",
    5: "unknown_rfid",
}


def _ams_status_name(code: int) -> str:
    """Return human-readable AMS status name or 'unknown_<hex>' fallback."""
    if code in AMS_STATUS_NAMES:
        return AMS_STATUS_NAMES[code]
    return f"unknown_{code}"


def _ams_rfid_status_name(code: int) -> str:
    """Return human-readable AMS RFID status name or 'unknown_<hex>' fallback."""
    if code in AMS_RFID_STATUS_NAMES:
        return AMS_RFID_STATUS_NAMES[code]
    return f"unknown_{code}"


STG_CUR_NAMES: dict[int, str] = {
    -1: "idle",
    0: "printing",
    1: "auto_bed_leveling",
    2: "heatbed_preheating",
    3: "sweeping_xy_mech_mode",
    4: "changing_filament",
    5: "m400_pause",
    6: "filament_runout_pause",
    7: "heating_hotend",
    8: "calibrating_extrusion",
    9: "scanning_bed_surface",
    10: "inspecting_first_layer",
    11: "identifying_build_plate_type",
    12: "calibrating_micro_lidar",
    13: "homing_toolhead",
    14: "cleaning_nozzle_tip",
    15: "checking_extruder_temperature",
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
    31: "bed_leveling_wip",
    32: "change_cartridge",
    33: "vibration_compensation_calibrating",
    34: "standby",
    35: "idle",
    255: "unknown",
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
        # --- Step 1: product_name mapping ---
        modules = self.modules
        for mod in modules:
            mapped = PRODUCT_NAME_TO_PRINTER.get(_normalize_product_name(mod.get("product_name")))
            if mapped:
                return mapped

        # --- Step 2: hw_ver + project_name mapping ---
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
            key = (hw_ver, project_name)
            if key in _HW_PROJECT_TO_PRINTER:
                return _HW_PROJECT_TO_PRINTER[key]
            # fallback: project_name=N1 regardless of hw_ver
            if project_name == "N1":
                return "A1MINI"

        # --- Step 3: SN-prefix mapping ---
        sn = self.sn
        if sn:
            for prefix, model in _SN_PREFIX_TO_PRINTER.items():
                if sn.upper().startswith(prefix.upper()):
                    return model

        # --- Step 4: legacy device.type ---
        device = self.print_block.get("device")
        dtype = to_int(device.get("type") if isinstance(device, dict) else None)
        if dtype is not None and dtype in _DEVICE_TYPE_TO_PRINTER:
            return _DEVICE_TYPE_TO_PRINTER[dtype]

        # --- Step 5: model_id fallback ---
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
    def ams_status_name(self) -> str | None:
        """Human-readable AMS status name, or 'unknown_<code>' for unknown codes."""
        code = to_int(self.print_block.get("ams_status"))
        if code is None:
            return None
        return _ams_status_name(code)

    @property
    def ams_rfid_status(self) -> float | None:
        value = to_int(self.print_block.get("ams_rfid_status"))
        return float(value) if value is not None else None

    @property
    def ams_rfid_status_name(self) -> str | None:
        """Human-readable AMS RFID status name, or 'unknown_<code>' for unknown codes."""
        code = to_int(self.print_block.get("ams_rfid_status"))
        if code is None:
            return None
        return _ams_rfid_status_name(code)


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
    def home_flags(self) -> dict[str, bool | None]:
        return decode_home_flags(self.print_block.get("home_flag"))

    @property
    def stat_flags(self) -> dict[str, bool | None]:
        return decode_stat_flags(self.print_block.get("stat"))

    @property
    def wired_network(self) -> float | None:
        """Best-effort wired network state from print.net.info.

        Current payloads typically expose adapters in `print.net.info` as:
        - index 0: WLAN
        - index 1: wired/LAN

        Emit only when this structure is present.
        """
        net = self.print_block.get("net")
        if not isinstance(net, dict):
            return None

        info = net.get("info")
        if not isinstance(info, list) or len(info) < 2:
            return None

        wired_entry = info[1]
        if not isinstance(wired_entry, dict):
            return None

        wired_ip = to_int(wired_entry.get("ip"))
        if wired_ip is None:
            return None

        return 1.0 if wired_ip > 0 else 0.0

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

        present = (hf & HOME_FLAG_MASKS["sd_card_present"]) != 0
        abnormal = (hf & HOME_FLAG_MASKS["sd_card_abnormal"]) != 0
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
                return 1.0 if (home_flag & HOME_FLAG_MASKS["door_open"]) else 0.0
            if stat_flag is not None:
                return 1.0 if (stat_flag & STAT_FLAG_MASKS["door_open"]) else 0.0
            return None

        if stat_flag is not None:
            return 1.0 if (stat_flag & STAT_FLAG_MASKS["door_open"]) else 0.0
        if home_flag is not None:
            return 1.0 if (home_flag & HOME_FLAG_MASKS["door_open"]) else 0.0
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

    @property
    def ams_units_with_model(self) -> list[dict[str, Any]]:
        """Return AMS units enriched with resolved ams_model and ams_series."""
        result = []
        for unit in self.ams_units:
            enriched = dict(unit)
            ams_model = resolve_ams_model(unit)
            enriched["ams_model"] = ams_model
            enriched["ams_series"] = resolve_ams_series(ams_model)
            result.append(enriched)
        return result
