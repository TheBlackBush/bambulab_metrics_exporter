from bambulab_metrics_exporter.flags import (
    DOOR_OPEN_MASK,
    SD_CARD_ABNORMAL_MASK,
    SD_CARD_PRESENT_MASK,
    decode_home_flags,
    decode_stat_flags,
    is_flag_set,
    to_hex_int,
    to_int,
)


def test_to_int_and_to_hex_int() -> None:
    assert to_int("42") == 42
    assert to_int("bad") is None
    assert to_hex_int("46A58008") == int("46A58008", 16)
    assert to_hex_int("zz") is None


def test_is_flag_set() -> None:
    assert is_flag_set(DOOR_OPEN_MASK, DOOR_OPEN_MASK) is True
    assert is_flag_set(0, DOOR_OPEN_MASK) is False
    assert is_flag_set(None, DOOR_OPEN_MASK) is None


def test_decode_home_flags() -> None:
    value = SD_CARD_PRESENT_MASK | SD_CARD_ABNORMAL_MASK
    decoded = decode_home_flags(value)
    assert decoded["sd_card_present"] is True
    assert decoded["sd_card_abnormal"] is True
    assert decoded["door_open"] is False


def test_decode_stat_flags() -> None:
    decoded = decode_stat_flags("46A58008")
    assert decoded["door_open"] is True
