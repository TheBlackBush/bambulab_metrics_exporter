from dataclasses import dataclass
from typing import Any


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
        value = self.print_block.get("mc_percent")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def remaining_seconds(self) -> float | None:
        value = self.print_block.get("mc_remaining_time")
        if isinstance(value, (int, float)):
            return float(value) * 60.0
        return None

    @property
    def nozzle_temp(self) -> float | None:
        value = self.print_block.get("nozzle_temper")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def nozzle_target_temp(self) -> float | None:
        value = self.print_block.get("nozzle_target_temper")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def bed_temp(self) -> float | None:
        value = self.print_block.get("bed_temper")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def bed_target_temp(self) -> float | None:
        value = self.print_block.get("bed_target_temper")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def chamber_temp(self) -> float | None:
        value = self.print_block.get("chamber_temper")
        if isinstance(value, (int, float)):
            return float(value)
        nested = self.print_block.get("device", {})
        if isinstance(nested, dict):
            ctc = nested.get("ctc", {})
            if isinstance(ctc, dict):
                info = ctc.get("info", {})
                if isinstance(info, dict):
                    temp = info.get("temp")
                    if isinstance(temp, (int, float)):
                        return float(temp)
        return None

    @property
    def layer_current(self) -> float | None:
        value = self.print_block.get("layer_num")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def layer_total(self) -> float | None:
        value = self.print_block.get("total_layer_num")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def layer_progress_percent(self) -> float | None:
        current = self.layer_current
        total = self.layer_total
        if current is None or total is None or total <= 0:
            return None
        return (current / total) * 100.0

    @property
    def fan_gear(self) -> float | None:
        value = self.print_block.get("big_fan1_speed")
        if isinstance(value, (int, float)):
            # Some firmware reports 0..15, map to percent for easier Grafana.
            if value <= 15:
                return float(value) / 15.0 * 100.0
            return float(value)
        return None

    @property
    def print_error_code(self) -> int | None:
        value = self.print_block.get("mc_print_error_code")
        return int(value) if isinstance(value, int) else None

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
