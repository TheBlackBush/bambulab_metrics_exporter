from __future__ import annotations

from typing import Any

DOOR_OPEN_MASK = 0x00800000
SD_CARD_PRESENT_MASK = 0x00000100
SD_CARD_ABNORMAL_MASK = 0x00000200

# Home flag masks (full parity set currently modeled from upstream constants).
HOME_FLAG_MASKS: dict[str, int] = {
    "x_axis": 0x00000001,
    "y_axis": 0x00000002,
    "z_axis": 0x00000004,
    "voltage220": 0x00000008,
    "xcam_auto_recovery_step_loss": 0x00000010,
    "camera_recording": 0x00000020,
    "ams_calibrate_remaining": 0x00000080,
    "sd_card_present": SD_CARD_PRESENT_MASK,
    "sd_card_abnormal": SD_CARD_ABNORMAL_MASK,
    "ams_auto_switch": 0x00000400,
    "xcam_allow_prompt_sound": 0x00020000,
    "wired_network": 0x00040000,
    "filament_tangle_detect_supported": 0x00080000,
    "filament_tangle_detected": 0x00100000,
    "supports_motor_calibration": 0x00200000,
    "door_open": DOOR_OPEN_MASK,
    "installed_plus": 0x04000000,
    "supported_plus": 0x08000000,
}

# Stat flag masks.
STAT_FLAG_MASKS: dict[str, int] = {
    "door_open": DOOR_OPEN_MASK,
}


def to_int(value: Any) -> int | None:
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


def to_hex_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text, 16)
        except ValueError:
            return None
    return None


def is_flag_set(raw_value: int | None, mask: int) -> bool | None:
    if raw_value is None:
        return None
    return (raw_value & mask) != 0


def decode_home_flags(home_flag: Any) -> dict[str, bool | None]:
    parsed = to_int(home_flag)
    return {name: is_flag_set(parsed, mask) for name, mask in HOME_FLAG_MASKS.items()}


def decode_stat_flags(stat: Any) -> dict[str, bool | None]:
    parsed = to_hex_int(stat)
    return {name: is_flag_set(parsed, mask) for name, mask in STAT_FLAG_MASKS.items()}
