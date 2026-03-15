from __future__ import annotations

from typing import Any

DOOR_OPEN_MASK = 0x00800000
SD_CARD_PRESENT_MASK = 0x00000100
SD_CARD_ABNORMAL_MASK = 0x00000200

# Upstream-derived home/stat flag map. Kept compact for phased rollout.
FLAG_MASKS: dict[str, int] = {
    "door_open": DOOR_OPEN_MASK,
    "sd_card_present": SD_CARD_PRESENT_MASK,
    "sd_card_abnormal": SD_CARD_ABNORMAL_MASK,
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
    return {name: is_flag_set(parsed, mask) for name, mask in FLAG_MASKS.items()}


def decode_stat_flags(stat: Any) -> dict[str, bool | None]:
    parsed = to_hex_int(stat)
    return {name: is_flag_set(parsed, mask) for name, mask in FLAG_MASKS.items()}
