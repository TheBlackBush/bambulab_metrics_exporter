"""Tests for the per-model capability table and model code normalization."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bambulab_metrics_exporter.capabilities import (
    CAPABILITIES,
    DOOR_HOME_FLAG,
    DOOR_STAT,
    UNKNOWN,
    capabilities_for,
)
from bambulab_metrics_exporter.models import KNOWN_PRINTER_MODELS, PrinterSnapshot, normalize_model_hint

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "printers"


def test_every_known_model_has_capabilities() -> None:
    assert KNOWN_PRINTER_MODELS <= set(CAPABILITIES)


@pytest.mark.parametrize(
    ("model", "door", "chamber", "heater", "dual", "rack", "aux"),
    [
        ("X1C", DOOR_HOME_FLAG, True, False, False, False, True),
        ("X1E", DOOR_HOME_FLAG, True, True, False, False, True),
        ("P1S", None, False, False, False, False, True),
        ("A1", None, False, False, False, False, False),
        ("A2L", None, False, False, False, False, False),
        ("P2S", DOOR_STAT, True, False, False, False, True),
        ("X2D", DOOR_STAT, True, True, True, False, True),
        ("H2D", DOOR_STAT, True, True, True, False, True),
        ("H2S", DOOR_STAT, True, True, False, False, True),
        ("H2C", DOOR_STAT, True, True, True, True, True),
    ],
)
def test_capability_table(model, door, chamber, heater, dual, rack, aux) -> None:
    caps = capabilities_for(model)
    assert (caps.door_source, caps.chamber_sensor, caps.chamber_heater) == (door, chamber, heater)
    assert (caps.dual_extruder, caps.hotend_rack, caps.aux_fan) == (dual, rack, aux)


def test_unknown_model_is_permissive() -> None:
    assert capabilities_for(None) is UNKNOWN
    assert capabilities_for("FUTURE") is UNKNOWN
    assert UNKNOWN.chamber_sensor and UNKNOWN.aux_fan and UNKNOWN.door_source == "auto"


def test_r1_laser_has_no_fdm_hardware() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"chamber_temper": 5, "big_fan1_speed": "0"}},
        configured_serial="35FFIXTURE000001",
    )
    assert snap.model_name == "R1"
    assert snap.capabilities.fdm is False
    assert snap.chamber_temp is None and snap.fan_big_1_percent is None


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("O2D", "H2DPRO"),
        ("H2DP", "H2DPRO"),
        ("A1M", "A1MINI"),
        ("A04", "A1MINI"),
        ("A11", "A1"),
        ("N2", "A1MINI"),
        ("N6-V2", "X2D"),
        ("o1c2-v2", "H2C"),
        ("O1D-V2", "H2D"),
        ("N8", "R1"),
        ("N2D", None),  # unannounced; not mapped
        ("ZZ-V2", None),
    ],
)
def test_alternate_model_codes(hint: str, expected: str | None) -> None:
    assert normalize_model_hint(hint) == expected


def _snap(name: str) -> PrinterSnapshot:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return PrinterSnapshot(connected=True, raw={**fixture["pushall"], **(fixture.get("get_version") or {})})


@pytest.mark.parametrize("name", ["a1", "a2l"])
def test_a_series_reports_no_aux_or_chamber_fan(name: str) -> None:
    snap = _snap(name)
    assert snap.fan_big_1_percent is None and snap.fan_big_2_percent is None


def test_x1_door_never_falls_back_to_stat() -> None:
    """stat bit 23 is always set on X1C; without home_flag the door is unknown."""
    snap = PrinterSnapshot(
        connected=True, raw={"print": {"stat": "00800000"}}, configured_serial="00MFIXTURE000001"
    )
    assert snap.door_open is None


@pytest.mark.parametrize(("name", "lid"), [("h2d", True), ("x2d", False), ("p2s", False)])
def test_lid_only_on_h2_family(name: str, lid: bool) -> None:
    snap = _snap(name)
    value = snap.lid_open
    assert (value is not None) is lid
    if value is not None:
        assert not math.isnan(value)
