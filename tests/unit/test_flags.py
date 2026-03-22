from bambulab_metrics_exporter.flags import (
    HOME_FLAG_MASKS,
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
    door = HOME_FLAG_MASKS["door_open"]
    assert is_flag_set(door, door) is True
    assert is_flag_set(0, door) is False
    assert is_flag_set(None, door) is None


def test_decode_home_flags() -> None:
    value = HOME_FLAG_MASKS["sd_card_present"] | HOME_FLAG_MASKS["sd_card_abnormal"]
    decoded = decode_home_flags(value)
    assert decoded["sd_card_present"] is True
    assert decoded["sd_card_abnormal"] is True
    assert decoded["door_open"] is False


def test_decode_stat_flags() -> None:
    decoded = decode_stat_flags("46A58008")
    assert decoded["door_open"] is True
    assert decoded["lid_open"] is False


def test_decode_stat_flags_lid_open_bit() -> None:
    decoded = decode_stat_flags("47A58008")
    assert decoded["lid_open"] is True
