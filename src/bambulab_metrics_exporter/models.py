from dataclasses import dataclass
from typing import Any


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
        return _to_float(self.print_block.get("wifi_signal"))

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
    def ams_units(self) -> list[dict[str, Any]]:
        ams = self.print_block.get("ams", {})
        if not isinstance(ams, dict):
            return []
        units = ams.get("ams")
        if isinstance(units, list):
            return [x for x in units if isinstance(x, dict)]
        return []
