import os
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from bambulab_metrics_exporter import main, env_sync, models
from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.models import PrinterSnapshot

def test_local_mqtt_callbacks_coverage():
    settings = Settings(
        bambulab_host="localhost",
        bambulab_serial="S1",
        bambulab_access_code="A1"
    )
    client = LocalMqttBambuClient(settings)
    
    # Mock MQTT client
    mqtt_mock = MagicMock()
    
    # Test _on_connect with failure
    client._on_connect(mqtt_mock, None, None, 1, None)
    assert not client._connected
    
    # Test _on_connect success
    client._on_connect(mqtt_mock, None, None, 0, None)
    assert client._connected
    
    # Test _on_disconnect
    client._on_disconnect(mqtt_mock, None, None, 0, None)
    assert not client._connected
    
    # Test _on_message with wrong topic
    msg_wrong = MagicMock()
    msg_wrong.topic = "wrong"
    client._on_message(mqtt_mock, None, msg_wrong)
    
    # Test _on_message with invalid JSON
    msg_bad_json = MagicMock()
    msg_bad_json.topic = client._topic_report
    msg_bad_json.payload = b"invalid"
    client._on_message(mqtt_mock, None, msg_bad_json)

def test_main_env_permission_coverage(caplog):
    # Test _safe_load_dotenv permission error
    with caplog.at_level(logging.WARNING):
        with patch("bambulab_metrics_exporter.main.Path.exists", return_value=True):
            with patch("bambulab_metrics_exporter.main.load_dotenv", side_effect=PermissionError):
                 main._safe_load_dotenv()
    assert "Skipping .env load due to permission error" in caplog.text
    
    caplog.clear()
    # Test _persist_runtime_env permission error
    with caplog.at_level(logging.WARNING):
        with patch("bambulab_metrics_exporter.main.sync_env_file", side_effect=PermissionError):
            main._persist_runtime_env(Path(".env"))
    assert "Skipping .env sync due to permission error" in caplog.text

def test_env_sync_edge_cases(tmp_path):
    # Test shell escape
    assert env_sync._shell_escape("") == "''"
    assert env_sync._shell_escape("val'with'quotes") == "'val'\\''with'\\''quotes'"
    
    # Test sync_env_file with chmod error
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=VAL")
    with patch.object(Path, "chmod", side_effect=OSError):
        env_sync.sync_env_file(env_file)

def test_models_parsing_edges():
    # Parsing helpers
    assert models._to_float("  ") is None
    assert models._to_int(True) == 1
    assert models._to_int(1.5) == 1
    assert models._to_int("  ") is None
    assert models._to_int("not-int") is None
    
    # Snapshot properties
    snap = PrinterSnapshot(connected=True, raw={"print": {"total_layer_num": 0}})
    assert snap.layer_progress_percent is None
    
    snap2 = PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 15}})
    assert snap2.fan_gear == 100.0  # (15/15)*100
    
    snap3 = PrinterSnapshot(connected=True, raw={"print": {"online": "not-a-dict"}})
    assert snap3.online_ahb is None
    
    snap4 = PrinterSnapshot(connected=True, raw={"print": {"online": {"ahb": "not-bool"}}})
    assert snap4.online_ahb is None
    
    snap5 = PrinterSnapshot(connected=True, raw={"print": {"ams": "not-a-dict"}})
    assert snap5.ams_tray_now is None
    assert snap5.ams_units == []
    
    snap6 = PrinterSnapshot(connected=True, raw={"print": {"subtask_name": 123}})
    assert snap6.subtask_name is None
    
    snap7 = PrinterSnapshot(connected=True, raw={})
    assert snap7.name is None
