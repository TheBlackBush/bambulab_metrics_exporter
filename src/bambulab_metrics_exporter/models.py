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


# X1-family printers report the door sensor in home_flag; other models use stat.
X1_HOMEFLAG_MODELS = {"X1", "X1C", "X1E"}
H2_MODEL_PREFIX = "H2"

# Models without a chamber temperature sensor or a door sensor. Their firmware still sends
# placeholder values (for example chamber_temper 5), which must not be exported as data.
NO_CHAMBER_SENSOR_MODELS: frozenset[str] = frozenset({"A1", "A1MINI", "A2L", "P1P", "P1S"})
NO_DOOR_SENSOR_MODELS: frozenset[str] = frozenset({"A1", "A1MINI", "A2L", "P1P", "P1S"})

# product_name → model (priority 1 in resolver). Keys are normalized with
# _normalize_product_name, so firmware strings like "Bambu Lab X1-Carbon" match.
PRODUCT_NAME_TO_PRINTER: dict[str, str] = {
    "bambu lab a1": "A1",
    "bambu lab a1 mini": "A1MINI",
    "bambu lab a2l": "A2L",
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
    "bambu lab x2d": "X2D",
}

# Serial prefix → model (priorities 2 and 3). The first three characters of a
# printer serial identify the model; this mirrors the sn_prefix values in Bambu
# Studio's resources/printers/*.json.
_SN_PREFIX_TO_PRINTER: dict[str, str] = {
    "00W": "X1",
    "00M": "X1C",
    "03W": "X1E",
    "01S": "P1P",
    "01P": "P1S",
    "030": "A1MINI",
    "039": "A1",
    "22E": "P2S",
    "20P": "X2D",
    "26A": "A2L",
    "093": "H2S",
    "094": "H2D",
    "239": "H2DPRO",
    "31B": "H2C",
}

# Internal model codes (Bambu Studio printer model ids, also returned by the cloud
# device list as dev_model_name on older models) → model.
_MODEL_CODE_TO_PRINTER: dict[str, str] = {
    "BL-P001": "X1C",
    "BL-P002": "X1",
    "C11": "P1P",
    "C12": "P1S",
    "C13": "X1E",
    "N1": "A1MINI",
    "N2S": "A1",
    "N6": "X2D",
    "N7": "P2S",
    "N9": "A2L",
    "O1C": "H2C",
    "O1C2": "H2C",
    "O1D": "H2D",
    "O1E": "H2DPRO",
    "O1S": "H2S",
}

KNOWN_PRINTER_MODELS: frozenset[str] = frozenset(_SN_PREFIX_TO_PRINTER.values())

# (hw_ver, project_name) → model (priority 5, AP-module path). Only unambiguous
# pairs: hw_ver alone is shared across families (AP05 appears on X1C, H2D, H2S,
# H2C and A1), so an empty project_name is not enough to identify those models.
_HW_PROJECT_TO_PRINTER: dict[tuple[str, str], str] = {
    ("AP02", ""): "X1E",
    ("AP03", "N1"): "A1MINI",
    ("AP04", "C11"): "P1P",
    ("AP04", "C12"): "P1S",
    ("AP05", "N2S"): "A1",
}


# AMS serial prefix → model name
AMS_SERIAL_PREFIX_TO_MODEL: dict[str, str] = {
    "006": "ams_1",
    "03C": "ams_lite",
    "19C": "ams_2_pro",
    "19F": "ams_ht",
}

# get_version module name prefix ("n3f/0") → AMS model, for units without info/sn.
AMS_MODEL_BY_MODULE_PREFIX: dict[str, str] = {
    "ams": "ams_1",
    "ams_f1": "ams_lite",
    "n3f": "ams_2_pro",
    "n3s": "ams_ht",
}

# AMS Lite has no temperature or humidity sensor; it reports fixed placeholders.
AMS_MODELS_WITHOUT_SENSORS: frozenset[str] = frozenset({"ams_lite"})
# Only these units have a dryer, so drying telemetry is meaningless on the others.
AMS_MODELS_WITH_DRYER: frozenset[str] = frozenset({"ams_2_pro", "ams_ht"})

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
    5: "ams_lite",  # AMS Lite on the A2L ("mixed" type)
}

HOTEND_RACK_SLOT_IDS: tuple[int, ...] = (16, 17, 18, 19, 20, 21)

HOTEND_RACK_HOLDER_POSITION_NAMES: dict[int, str] = {
    1: "a_top",
    2: "b_top",
    3: "centre",
}

HOTEND_RACK_HOLDER_STATE_NAMES: dict[int, str] = {
    0: "idle",
    1: "hotend_centre",
    2: "toolhead_centre",
    3: "calibrate_hotend_rack",
    4: "cut_material",
    5: "unlock_hotend",
    6: "lift_hotend_rack",
    7: "place_hotend",
    8: "pick_hotend",
    9: "lock_hotend",
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

        # String `info` is always hexadecimal, even when it only contains digits
        # ("2003" is AMS 2 Pro with dry status 0, not decimal 2003). Reading it as
        # decimal corrupted the drying state of AMS 2 Pro / AMS HT units.
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
      bits 22-23: dry sub-status (2 bits; bits 24-27 are the filament switcher input)
    """
    return {
        "ams_type": ams_info & 0xF,
        "dry_heater_state": (ams_info >> 4) & 0xF,
        "dry_fan1": (ams_info >> 18) & 0x3,
        "dry_fan2": (ams_info >> 20) & 0x3,
        "dry_sub_status": (ams_info >> 22) & 0x3,
    }


# AMS status code → human-readable name.
# The raw ams_status field encodes sub-state in bits 15-8; the status category
# is extracted as (raw >> 8) & 0xFF before looking up in this table.
AMS_STATUS_NAMES: dict[int, str] = {
    0x00: "idle",
    0x01: "filament_change",
    0x02: "rfid_identifying",
    0x03: "assist",
    0x04: "calibration",
    0x10: "self_check",
    0x20: "debug",
    0xFF: "unknown_device",
}

# AMS RFID status code → human-readable name.
AMS_RFID_STATUS_NAMES: dict[int, str] = {
    0: "idle",
    1: "reading",
    2: "writing",
    3: "identifying",
    4: "close",
    5: "unknown_rfid",
    6: "reading_stop",
}

# AMS dry status (ams_info bits 4-7), names per Bambu Studio / Bambu Handy.
AMS_DRY_HEATER_STATE_NAMES: dict[int, str] = {
    0: "off",
    1: "self_check",
    2: "drying",
    3: "cooling",
    4: "stopped",
    5: "error",
    6: "thermal_runaway",
    7: "test_mode",
}

# AMS dry sub-status (ams_info bits 22-23).
AMS_DRY_SUB_STATUS_NAMES: dict[int, str] = {
    0: "none",
    1: "heating",
    2: "dehumidifying",
}


def ams_dry_state_name(code: int) -> str:
    return AMS_DRY_HEATER_STATE_NAMES.get(code, f"unknown_{code}")


def ams_dry_sub_status_name(code: int) -> str:
    return AMS_DRY_SUB_STATUS_NAMES.get(code, f"unknown_{code}")


def _ams_status_name(code: int) -> str:
    """Return human-readable AMS status name or 'unknown_<hex>' fallback.

    The raw ams_status field packs sub-state in the lower byte and the status
    category in bits 15-8.  Extract the category byte before mapping.
    """
    category = (code >> 8) & 0xFF
    if category in AMS_STATUS_NAMES:
        return AMS_STATUS_NAMES[category]
    return f"unknown_{code:#x}"


def _ams_rfid_status_name(code: int) -> str:
    """Return human-readable AMS RFID status name or 'unknown_<code>' fallback."""
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
    6: "paused_filament_runout",
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
    17: "paused_front_cover_falling",
    18: "calibrating_micro_lidar",
    19: "calibrating_extrusion_flow",
    20: "paused_nozzle_temperature_malfunction",
    21: "paused_heat_bed_temperature_malfunction",
    22: "filament_unloading",
    23: "paused_skipped_step",
    24: "filament_loading",
    25: "calibrating_motor_noise",
    26: "paused_ams_lost",
    27: "paused_low_fan_speed_heat_break",
    28: "paused_chamber_temperature_control_error",
    29: "cooling_chamber",
    30: "paused_user_gcode",
    31: "motor_noise_showoff",
    32: "paused_nozzle_filament_covered_detected",
    33: "paused_cutter_error",
    34: "paused_first_layer_error",
    35: "paused_nozzle_clog",
    36: "check_absolute_accuracy_before_calibration",
    37: "absolute_accuracy_calibration",
    38: "check_absolute_accuracy_after_calibration",
    39: "calibrate_nozzle_offset",
    40: "bed_level_high_temperature",
    41: "check_quick_release",
    42: "check_door_and_cover",
    43: "laser_calibration",
    44: "check_plaform",
    45: "check_birdeye_camera_position",
    46: "calibrate_birdeye_camera",
    47: "bed_level_phase_1",
    48: "bed_level_phase_2",
    49: "heating_chamber",
    50: "heated_bedcooling",
    51: "print_calibration_lines",
    52: "check_material",
    53: "calibrating_live_view_camera",
    54: "waiting_for_heatbed_temperature",
    55: "check_material_position",
    56: "calibrating_cutter_model_offset",
    57: "measuring_surface",
    58: "thermal_preconditioning",
    255: "idle",
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


def _unpack_temperature(value: Any) -> tuple[float | None, float | None]:
    """Unpack packed temperature integer into (actual, target).

    Follows the H2D telemetry convention used by community implementations:
    - low 16 bits: actual temperature
    - high 16 bits: target temperature
    """
    raw = to_int(value)
    if raw is None:
        return None, None
    actual = float(raw & 0xFFFF)
    target = float((raw >> 16) & 0xFFFF)
    return actual, target


def _fan_percent_normalized(value: Any) -> float | None:
    """Normalize fan speed to percent with step-aware rounding.

    Normalization logic for raw 0..15 fan steps: (raw/15)*100 rounded to nearest 10.
    For already-percent values (>15), pass through as percent and still round to nearest 10.
    """
    raw = _to_float(value)
    if raw is None:
        return None
    if raw <= 15.0:
        percent = (raw / 15.0) * 100.0
    else:
        percent = raw
    return float(round(percent / 10.0) * 10)


# Backward-compatible aliases for legacy tests/importers.
_to_int = to_int
_to_hex_int = to_hex_int


def _normalize_product_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().replace("-", " ").split())


def _model_from_serial(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _SN_PREFIX_TO_PRINTER.get(value.strip().upper()[:3])


def normalize_model_hint(value: Any) -> str | None:
    """Map a free-form model string to a known model, or None.

    Accepts the forms seen in configuration and the cloud device list: marketing
    names with or without the "Bambu Lab" prefix ("X1 Carbon", "Bambu Lab H2D Pro"),
    internal codes ("BL-P001", "N6") and normalized names ("H2DPRO"). Anything
    unrecognized returns None so raw strings never become label values.
    """
    name = _normalize_product_name(value)
    if not name:
        return None
    if name.startswith("bambu lab "):
        name = name[len("bambu lab "):]
    mapped = PRODUCT_NAME_TO_PRINTER.get(f"bambu lab {name}")
    if mapped:
        return mapped
    code = str(value).strip().upper()
    if code in _MODEL_CODE_TO_PRINTER:
        return _MODEL_CODE_TO_PRINTER[code]
    compact = name.replace(" ", "").upper()
    return compact if compact in KNOWN_PRINTER_MODELS else None


@dataclass(slots=True)
class PrinterSnapshot:
    connected: bool
    raw: dict[str, Any]
    # Serial from configuration (BAMBULAB_SERIAL). Regular pushall reports omit
    # print.sn, so the configured serial is usually the reliable identity source.
    configured_serial: str | None = None
    # Model from configuration or cloud discovery (BAMBULAB_PRINTER_MODEL); used
    # only after normalization through the known-model tables.
    configured_model: str | None = None

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
        """Resolve the printer model from the most reliable source available.

        Order: get_version product_name, payload serial prefix, configured serial
        prefix, configured/cloud model, then unambiguous legacy hw_ver pairs.
        print.device.type is deliberately not used: it is a mode bitmask
        (FDM=0x1, laser=0x10, cut=0x100) that reads 1 on every FDM printer.
        print.model_id is not used either: it carries an opaque per-job id.
        """
        # --- Step 1: product_name mapping (get_version module list) ---
        modules = self.modules
        for mod in modules:
            mapped = PRODUCT_NAME_TO_PRINTER.get(_normalize_product_name(mod.get("product_name")))
            if mapped:
                return mapped

        # --- Steps 2-3: serial prefix (payload first, then configuration) ---
        for serial in (self.sn, self.configured_serial):
            mapped = _model_from_serial(serial)
            if mapped:
                # Early H2C units shipped with the H2D prefix 094; the hotend rack
                # only exists on the H2C.
                if mapped == "H2D" and self.hotend_rack_present:
                    return "H2C"
                return mapped

        # --- Step 4: configured or cloud-discovered model ---
        mapped = normalize_model_hint(self.configured_model)
        if mapped:
            return mapped

        # --- Step 5: legacy hw_ver + project_name mapping ---
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
        """Chamber temperature in °C.

        New firmware reports `device.ctc.info.temp` packed as (target << 16) | current
        while the chamber heater has a target (H2S sample: 3932220 = 60 °C / 60 °C).
        Models without a chamber sensor send a placeholder and report None.
        """
        if self.printer_type in NO_CHAMBER_SENSOR_MODELS:
            return None
        raw: Any = None
        device = self.print_block.get("device")
        if isinstance(device, dict):
            ctc = device.get("ctc")
            if isinstance(ctc, dict) and isinstance(ctc.get("info"), dict):
                raw = ctc["info"].get("temp")
        if raw is None:
            raw = self.print_block.get("chamber_temper")
        value = _to_float(raw)
        if value is None:
            return None
        if value > 0xFFFF and value.is_integer():
            return float(int(value) & 0xFFFF)
        return value

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
    def fan_big_1_percent(self) -> float | None:
        return _fan_percent_normalized(self.print_block.get("big_fan1_speed"))

    @property
    def fan_big_2_percent(self) -> float | None:
        return _fan_percent_normalized(self.print_block.get("big_fan2_speed"))

    @property
    def fan_cooling_percent(self) -> float | None:
        return _fan_percent_normalized(self.print_block.get("cooling_fan_speed"))

    @property
    def fan_heatbreak_percent(self) -> float | None:
        return _fan_percent_normalized(self.print_block.get("heatbreak_fan_speed"))

    @property
    def fan_secondary_aux_percent(self) -> float | None:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return None
        airduct = device.get("airduct")
        if not isinstance(airduct, dict):
            return None
        parts = airduct.get("parts")
        if not isinstance(parts, list):
            return None
        for entry in parts:
            if not isinstance(entry, dict):
                continue
            # Part id packs the fan number in bits 4-11; fan 10 (id 160) is the
            # secondary aux fan. Its `state` is already a 0-100 percentage.
            part_id = to_int(entry.get("id"))
            if part_id is None or (part_id >> 4) & 0xFF != 10:
                continue
            state = to_int(entry.get("state"))
            if state is not None:
                return float(state & 0xFF)
            return _fan_percent_normalized(entry.get("value"))
        return None

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
    def ams_tray_now(self) -> int | None:
        ams = self.print_block.get("ams")
        if isinstance(ams, dict):
            value = ams.get("tray_now")
            if isinstance(value, (int, str)):
                try:
                    return int(value)
                except (ValueError, TypeError):
                    pass
        return None

    @property
    def active_filament_source(self) -> tuple[str, int, int] | None:
        """Filament currently loaded for printing: ("ams", ams_id, slot_id),
        ("external", -1, -1) or ("none", -1, -1); None without data.

        New firmware reports the loaded slot per extruder in
        `device.extruder.info[].snow` = (ams_id << 8) | slot, where 0xFF00 is the
        external spool and 0xFFFF / 0xFEFF mean nothing loaded; the active extruder's
        entry wins. `ams.tray_now` only holds the local slot on those printers, so it
        is used only for older payloads: 255 none, 254 external, 0x80-0x87 an AMS HT
        unit id, otherwise ams_id = tray_now >> 2 and slot = tray_now & 3.
        """
        entries = [e for e in self.extruder_entries if to_int(e.get("snow")) is not None]
        if entries:
            active = self.active_extruder_index
            chosen = next(
                (e for e in entries if active is not None and to_int(e.get("id")) == int(active)),
                entries[0],
            )
            snow = to_int(chosen.get("snow"))
            assert snow is not None
            ams_id, slot = (snow >> 8) & 0xFF, snow & 0xFF
            if ams_id == 0xFF and slot == 0xFF or (ams_id, slot) == (0xFE, 0xFF):
                return ("none", -1, -1)
            if ams_id == 0xFF:
                return ("external", -1, -1)
            return ("ams", ams_id, slot)

        ams = self.print_block.get("ams")
        if not isinstance(ams, dict):
            return None
        tray_now = to_int(ams.get("tray_now"))
        if tray_now is None:
            return None
        if tray_now == 255:
            return ("none", -1, -1)
        if tray_now == 254:
            return ("external", -1, -1)
        if 0x80 <= tray_now <= 0x87:
            return ("ams", tray_now, 0)
        return ("ams", tray_now >> 2, tray_now & 0x3)

    @property
    def external_spool_active(self) -> float | None:
        """1 when the external spool feeds the active extruder, else 0; None without data."""
        source = self.active_filament_source
        if source is None:
            return None
        return 1.0 if source[0] == "external" else 0.0

    @property
    def external_spool_entries(self) -> list[dict[str, Any]]:
        """Return normalized external spool entries from vir_slot/vt_tray payloads."""

        def _norm(entry: dict[str, Any]) -> dict[str, Any] | None:
            ext_id = to_int(entry.get("id"))
            if ext_id not in {254, 255}:
                return None
            # New firmware always lists both virtual slots; skip ones with no spool.
            tray_type = str(entry.get("tray_type", "")).strip()
            tray_idx = str(entry.get("tray_info_idx", "")).strip()
            if not tray_type and not tray_idx:
                return None
            return {
                "id": str(ext_id),
                "tray_type": str(entry.get("tray_type", "")).strip(),
                "tray_info_idx": str(entry.get("tray_info_idx", "")).strip(),
                "tray_color": str(entry.get("tray_color", "")).strip().upper(),
            }

        vir_slot = self.print_block.get("vir_slot")
        if isinstance(vir_slot, list):
            entries: list[dict[str, Any]] = []
            for item in vir_slot:
                if not isinstance(item, dict):
                    continue
                normalized = _norm(item)
                if normalized is not None:
                    entries.append(normalized)
            if entries:
                return entries

        vt_tray = self.print_block.get("vt_tray")
        if isinstance(vt_tray, dict):
            normalized = _norm(vt_tray)
            if normalized is not None:
                return [normalized]

        return []

    @property
    def extruder_state_raw(self) -> int | None:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return None
        extruder = device.get("extruder")
        if not isinstance(extruder, dict):
            return None
        return to_int(extruder.get("state"))

    @property
    def active_extruder_index(self) -> float | None:
        raw = self.extruder_state_raw
        if raw is None:
            return None
        return float((raw >> 4) & 0xF)

    @property
    def extruder_entries(self) -> list[dict[str, Any]]:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return []
        extruder = device.get("extruder")
        if not isinstance(extruder, dict):
            return []
        info = extruder.get("info")
        if not isinstance(info, list):
            return []

        out: list[dict[str, Any]] = []
        for item in info:
            if not isinstance(item, dict):
                continue
            extruder_id = to_int(item.get("id"))
            if extruder_id is None:
                continue
            actual_temp, target_temp = _unpack_temperature(item.get("temp"))
            out.append(
                {
                    "id": str(extruder_id),
                    "actual_temp": actual_temp,
                    "target_temp": target_temp,
                    "hnow": to_int(item.get("hnow")),
                    # Loaded slot: (ams_id << 8) | slot, see active_filament_source.
                    "snow": to_int(item.get("snow")),
                }
            )
        return out

    @property
    def extruder_nozzle_info_entries(self) -> list[dict[str, Any]]:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return self._legacy_nozzle_entries()

        nozzle = device.get("nozzle")
        if not isinstance(nozzle, dict):
            return self._legacy_nozzle_entries()
        nozzle_info = nozzle.get("info")
        if not isinstance(nozzle_info, list):
            return self._legacy_nozzle_entries()

        nozzle_by_id: dict[int, dict[str, Any]] = {}
        for item in nozzle_info:
            if not isinstance(item, dict):
                continue
            nid = to_int(item.get("id"))
            if nid is None:
                continue
            nozzle_by_id[nid] = item

        entries: list[dict[str, Any]] = []
        for ext in self.extruder_entries:
            ext_id = to_int(ext.get("id"))
            if ext_id is None:
                continue
            nozzle_id = to_int(ext.get("hnow"))
            chosen = nozzle_by_id.get(nozzle_id) if nozzle_id is not None else None
            if chosen is None:
                chosen = nozzle_by_id.get(ext_id)
            if chosen is None:
                continue
            entries.append(
                {
                    "id": str(ext_id),
                    "nozzle_type": str(chosen.get("type", "")).strip(),
                    "nozzle_diameter": _to_float(chosen.get("diameter")),
                }
            )

        if entries:
            return entries

        # fallback for payloads exposing only nozzle.info ids 0/1 without extruder.info
        for fallback_id in (0, 1):
            chosen = nozzle_by_id.get(fallback_id)
            if chosen is None:
                continue
            entries.append(
                {
                    "id": str(fallback_id),
                    "nozzle_type": str(chosen.get("type", "")).strip(),
                    "nozzle_diameter": _to_float(chosen.get("diameter")),
                }
            )
        return entries

    def _legacy_nozzle_entries(self) -> list[dict[str, Any]]:
        """Single-nozzle printers without `device.nozzle` (A1, P1, older X1) report the
        nozzle in top-level `nozzle_type` / `nozzle_diameter`."""
        nozzle_type = self.print_block.get("nozzle_type")
        if not isinstance(nozzle_type, str) or not nozzle_type.strip():
            return []
        return [
            {
                "id": "0",
                "nozzle_type": nozzle_type.strip(),
                "nozzle_diameter": _to_float(self.print_block.get("nozzle_diameter")),
            }
        ]

    @property
    def active_nozzle_entry(self) -> dict[str, Any] | None:
        active = to_int(self.active_extruder_index)
        if active is None:
            # Single-nozzle printers without extruder state: the only nozzle is active.
            entries = self.extruder_nozzle_info_entries
            return entries[0] if len(entries) == 1 else None
        for item in self.extruder_nozzle_info_entries:
            if to_int(item.get("id")) == active:
                return item
        return None

    @property
    def hotend_rack_present(self) -> bool:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return False

        holder = device.get("holder")
        if isinstance(holder, dict):
            return True

        nozzle = device.get("nozzle")
        if not isinstance(nozzle, dict):
            return False

        exist = to_int(nozzle.get("exist"))
        if isinstance(exist, int):
            for slot_id in HOTEND_RACK_SLOT_IDS:
                if (exist & (1 << slot_id)) != 0:
                    return True

        info = nozzle.get("info")
        if isinstance(info, list):
            for item in info:
                if not isinstance(item, dict):
                    continue
                nozzle_id = to_int(item.get("id"))
                if nozzle_id in HOTEND_RACK_SLOT_IDS:
                    return True

        return False

    @property
    def hotend_rack_holder_position_name(self) -> str | None:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return None
        holder = device.get("holder")
        if not isinstance(holder, dict):
            return None
        pos = to_int(holder.get("pos"))
        if pos is None:
            return None
        return HOTEND_RACK_HOLDER_POSITION_NAMES.get(pos, "unknown")

    @property
    def hotend_rack_holder_state_name(self) -> str | None:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return None
        holder = device.get("holder")
        if not isinstance(holder, dict):
            return None
        stat = to_int(holder.get("stat"))
        if stat is None:
            return None
        return HOTEND_RACK_HOLDER_STATE_NAMES.get(stat, "unknown")

    @property
    def hotend_rack_slot_entries(self) -> list[dict[str, str]]:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return []
        nozzle = device.get("nozzle")
        if not isinstance(nozzle, dict):
            return []

        exist = to_int(nozzle.get("exist"))
        tar_id = to_int(nozzle.get("tar_id"))
        if exist is None and tar_id is None:
            return []

        out: list[dict[str, str]] = []
        for slot_id in HOTEND_RACK_SLOT_IDS:
            if tar_id == slot_id:
                state = "mounted"
            elif isinstance(exist, int) and (exist & (1 << slot_id)) != 0:
                state = "docked"
            else:
                state = "empty"
            out.append({"slot_id": str(slot_id), "state": state})
        return out

    @property
    def hotend_rack_hotend_entries(self) -> list[dict[str, Any]]:
        device = self.print_block.get("device")
        if not isinstance(device, dict):
            return []
        nozzle = device.get("nozzle")
        if not isinstance(nozzle, dict):
            return []
        info = nozzle.get("info")
        if not isinstance(info, list):
            return []

        out: list[dict[str, Any]] = []
        for item in info:
            if not isinstance(item, dict):
                continue
            nozzle_id = to_int(item.get("id"))
            if nozzle_id not in HOTEND_RACK_SLOT_IDS:
                continue
            out.append(
                {
                    "slot_id": str(nozzle_id),
                    "nozzle_type": str(item.get("type", "")).strip(),
                    "nozzle_diameter": _to_float(item.get("diameter")),
                    "wear": _to_float(item.get("wear")),
                    # `tm` is the hotend's maximum temperature (°C), `p_t` its total
                    # print time in seconds (ha-bambulab, Bambu Studio).
                    "max_temperature": _to_float(item.get("tm")),
                    "print_time_seconds": _to_float(item.get("p_t")),
                }
            )
        return out

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
    def xcam_halt_print_sensitivity(self) -> str | None:
        """Return the halt_print_sensitivity value from xcam block.

        Normalizes to lowercase. Returns None when missing, not a string,
        or not one of the expected values (low/medium/high).
        """
        xcam = self.print_block.get("xcam")
        if not isinstance(xcam, dict):
            return None
        raw = xcam.get("halt_print_sensitivity")
        if not isinstance(raw, str):
            return None
        normalized = raw.strip().lower()
        if normalized not in {"low", "medium", "high"}:
            return None
        return normalized
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

        # P1 and A1-family printers have no door sensor; their flag bits are not a door.
        if self.printer_type in NO_DOOR_SENSOR_MODELS:
            return None

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
    def lid_open(self) -> float | None:
        """1.0 if lid is open, 0.0 if closed.

        Source selection:
        - Direct `lid_open` value if present (preferred)
        - H2-family models use `stat` bitmask (`lid_open`, 0x01000000)
        - Non-H2 models without direct `lid_open` return None
        """
        val = self.print_block.get("lid_open")
        if isinstance(val, bool):
            return 1.0 if val else 0.0
        if isinstance(val, (int, float)):
            return 1.0 if val else 0.0

        ptype = self.printer_type
        if isinstance(ptype, str) and ptype.startswith(H2_MODEL_PREFIX):
            stat_flag = to_hex_int(self.print_block.get("stat"))
            if stat_flag is not None:
                return 1.0 if (stat_flag & STAT_FLAG_MASKS["lid_open"]) else 0.0

        return None

    @property
    def stg_cur(self) -> int | None:
        """Current print stage ID.

        Mirrors Home Assistant stage selection behavior:
        - prefer `print.stage._id` when available
        - otherwise use `print.stg_cur`
        - normalize idle payload edge-case (`print_type == idle` and stage id 0) to 255
        """
        stage_block = self.print_block.get("stage")
        stage_id = to_int(stage_block.get("_id")) if isinstance(stage_block, dict) else None
        if stage_id is None:
            stage_id = to_int(self.print_block.get("stg_cur"))
        if stage_id is None:
            return None

        print_type = self.print_block.get("print_type")
        if isinstance(print_type, str) and print_type.strip().lower() == "idle" and stage_id == 0:
            return 255

        return stage_id

    @property
    def stg_cur_name(self) -> str | None:
        """Human-readable name for the current print stage."""
        stage_id = self.stg_cur
        if stage_id is None:
            return None
        return STG_CUR_NAMES.get(stage_id, f"unknown_{stage_id}")

    @property
    def filament_tangle_detection_enabled(self) -> float | None:
        """Tangle-detection setting (home_flag bit 20), only when the printer reports the
        feature as supported (bit 19); otherwise the bit carries no meaning."""
        flags = self.home_flags
        if not flags.get("filament_tangle_detect_supported"):
            return None
        enabled = flags.get("filament_tangle_detection_enabled")
        return None if enabled is None else (1.0 if enabled else 0.0)

    @property
    def camera_recording(self) -> float | None:
        """1 when the camera records. `ipcam.ipcam_record` ("enable"/"disable") is the
        camera's own setting; newer firmware no longer sets home_flag bit 5 (verified on
        an X1C with firmware 01.12.00.00), so the flag is only a fallback."""
        ipcam = self.print_block.get("ipcam")
        if isinstance(ipcam, dict):
            record = ipcam.get("ipcam_record")
            if isinstance(record, str) and record.strip().lower() in {"enable", "disable"}:
                return 1.0 if record.strip().lower() == "enable" else 0.0
        flag = self.home_flags.get("camera_recording")
        return None if flag is None else (1.0 if flag else 0.0)

    @property
    def ams_units(self) -> list[dict[str, Any]]:
        ams = self.print_block.get("ams", {})
        if not isinstance(ams, dict):
            return []
        units = ams.get("ams")
        if isinstance(units, list):
            return [x for x in units if isinstance(x, dict)]
        return []

    def _ams_models_from_modules(self) -> dict[str, str]:
        """AMS unit id → model from get_version module names such as "n3f/0"."""
        models: dict[str, str] = {}
        for mod in self.modules:
            name = mod.get("name")
            if not isinstance(name, str) or "/" not in name:
                continue
            prefix, _, unit_id = name.partition("/")
            model = AMS_MODEL_BY_MODULE_PREFIX.get(prefix.strip().lower())
            if model and unit_id.strip().isdigit():
                models[str(int(unit_id))] = model
        return models

    @property
    def ams_units_with_model(self) -> list[dict[str, Any]]:
        """Return AMS units enriched with resolved ams_model and ams_series."""
        result = []
        module_models = self._ams_models_from_modules()
        for unit in self.ams_units:
            enriched = dict(unit)
            ams_model = resolve_ams_model(unit)
            if ams_model == "unknown":
                ams_model = module_models.get(str(unit.get("id", "")).strip(), "unknown")
            enriched["ams_model"] = ams_model
            enriched["ams_series"] = resolve_ams_series(ams_model)
            result.append(enriched)
        return result
