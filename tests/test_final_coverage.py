from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bambulab_metrics_exporter import startup
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_probe_disconnect_exception(caplog) -> None:
    """Cover line 38-39: disconnect exception during probe"""
    settings = Settings(
        bambulab_host="192.168.1.100",
        bambulab_serial="S1",
        bambulab_access_code="A1"
    )
    mock_client = MagicMock()
    mock_client.disconnect.side_effect = Exception("disconnect failed")
    mock_client.fetch_snapshot.side_effect = Exception("connect failed")

    with patch("bambulab_metrics_exporter.startup.build_client", return_value=mock_client):
        result = startup._probe_connection(settings)

    assert result is False
    assert "Client disconnect failed during probe" in caplog.text


def test_validate_local_probe_fails() -> None:
    """Cover line 59: probe connection fails"""
    settings = Settings(
        bambulab_host="192.168.1.100",
        bambulab_serial="S1",
        bambulab_access_code="A1"
    )

    with patch("bambulab_metrics_exporter.startup._probe_connection", return_value=False):
        with pytest.raises(RuntimeError, match="Local MQTT connection test failed"):
            startup._validate_local(settings)


def test_models_fan_gear_above_15() -> None:
    """Cover line 127: fan_gear > 15 returns raw value"""
    snap = PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 20.0}})
    assert snap.fan_gear == 20.0


def test_models_ams_tray_now_string() -> None:
    """Cover lines 250-252: ams_tray_now with string value"""
    snap = PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "255"}}})
    assert snap.ams_tray_now == "255"


def test_models_subtask_name_strip() -> None:
    """Cover line 272: subtask_name strips whitespace"""
    snap = PrinterSnapshot(connected=True, raw={"print": {"subtask_name": "  test.gcode  "}})
    assert snap.subtask_name == "test.gcode"


def test_models_sn_empty() -> None:
    """Cover line 287: sn returns None for empty/whitespace"""
    snap = PrinterSnapshot(connected=True, raw={"print": {"sn": "   "}})
    assert snap.sn is None


def test_models_nozzle_temp_missing() -> None:
    """Cover line 100: nozzle_temp when missing nested data"""
    snap = PrinterSnapshot(connected=True, raw={"print": {"upgrade_state": {"nozzle_ctc": {"ctc": {}}}}})
    # This should return None because info dict is missing
    assert snap.nozzle_temp is None
