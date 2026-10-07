"""Per-model hardware capabilities.

One table instead of scattered model checks. Values come from Bambu Studio printer and
machine profiles (support_chamber, support_chamber_temp_edit, extruder counts,
printer_modes) and ha-bambulab feature gates (door sensor, fans), cross-checked
against sanitized payloads in tests/fixtures/printers. Detection is not hardware
validation: only the X1C is validated on real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

DOOR_HOME_FLAG = "home_flag"  # home_flag bit 23 (X1 family)
DOOR_STAT = "stat"  # stat bit 23 (P2S, H2 family, X2D)
DOOR_AUTO = "auto"  # unknown model: whichever source is present


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    chamber_sensor: bool = True
    chamber_heater: bool = False
    door_source: str | None = DOOR_AUTO  # None: no door sensor
    lid_sensor: bool = False  # top lid via stat bit 24 (H2 family)
    aux_fan: bool = True  # big_fan1
    chamber_fan: bool = True  # big_fan2
    dual_extruder: bool = False
    hotend_rack: bool = False
    laser_cut: bool = False  # laser / cutter tool heads
    fdm: bool = True


_X1 = ModelCapabilities(door_source=DOOR_HOME_FLAG)
_P1 = ModelCapabilities(chamber_sensor=False, door_source=None)
_A_SERIES = ModelCapabilities(
    chamber_sensor=False, door_source=None, aux_fan=False, chamber_fan=False
)
_H2 = ModelCapabilities(
    chamber_heater=True, door_source=DOOR_STAT, lid_sensor=True, dual_extruder=True,
    laser_cut=True,
)

CAPABILITIES: dict[str, ModelCapabilities] = {
    "X1": _X1,
    "X1C": _X1,
    "X1E": ModelCapabilities(chamber_heater=True, door_source=DOOR_HOME_FLAG),
    "X2D": ModelCapabilities(chamber_heater=True, door_source=DOOR_STAT, dual_extruder=True),
    "P1P": _P1,
    "P1S": _P1,
    "P2S": ModelCapabilities(door_source=DOOR_STAT),
    "A1": _A_SERIES,
    "A1MINI": _A_SERIES,
    "A2L": _A_SERIES,
    "H2D": _H2,
    "H2DPRO": _H2,
    "H2S": ModelCapabilities(
        chamber_heater=True, door_source=DOOR_STAT, lid_sensor=True, laser_cut=True
    ),
    "H2C": ModelCapabilities(
        chamber_heater=True, door_source=DOOR_STAT, lid_sensor=True, dual_extruder=True,
        hotend_rack=True, laser_cut=True,
    ),
    # Laser engraver (Bambu Studio code N8, serial prefix 35F): no FDM hardware.
    "R1": ModelCapabilities(
        chamber_sensor=False, door_source=DOOR_AUTO, aux_fan=False, chamber_fan=False,
        laser_cut=True, fdm=False,
    ),
}

# Unknown or undetected models: export whatever the payload carries.
UNKNOWN = ModelCapabilities()


def capabilities_for(model: str | None) -> ModelCapabilities:
    if model is None:
        return UNKNOWN
    return CAPABILITIES.get(model, UNKNOWN)
