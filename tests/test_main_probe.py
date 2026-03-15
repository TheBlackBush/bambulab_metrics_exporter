from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from bambulab_metrics_exporter import main


def test_main_run_metadata_discovery_from_cloud(monkeypatch) -> None:
    """Test that metadata is discovered from cloud and updates env"""
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-token")
    monkeypatch.delenv("PRINTER_NAME_LABEL", raising=False)

    mock_devices = [
        {"dev_id": "S123", "name": "CloudName", "model": "P1S"}
    ]
    
    mock_collector = MagicMock()
    mock_app = MagicMock()

    with patch("bambulab_metrics_exporter.main.get_bind_devices", return_value=mock_devices):
        with patch("bambulab_metrics_exporter.main.PollingCollector", return_value=mock_collector):
            with patch("bambulab_metrics_exporter.main.build_app", return_value=mock_app):
                with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                    with patch("bambulab_metrics_exporter.main.sync_env_file"):
                        with patch("bambulab_metrics_exporter.main.startup_validate"):
                            main.run()

    assert os.environ.get("BAMBULAB_PRINTER_NAME") == "CloudName"
    assert os.environ.get("BAMBULAB_PRINTER_MODEL") == "P1S"


def test_main_run_cloud_discovery_fails_gracefully(monkeypatch, caplog) -> None:
    """Test that cloud metadata discovery failure is non-fatal"""
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-token")

    with patch("bambulab_metrics_exporter.main.get_bind_devices", side_effect=Exception("API error")):
        with patch("bambulab_metrics_exporter.main.PollingCollector"):
            with patch("bambulab_metrics_exporter.main.build_app"):
                with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                    with patch("bambulab_metrics_exporter.main.sync_env_file"):
                        with patch("bambulab_metrics_exporter.main.startup_validate"):
                            main.run()

    assert "Metadata discovery from cloud failed (non-fatal)" in caplog.text


def test_main_shutdown_handler(monkeypatch) -> None:
    """Test that shutdown handler is registered"""
    monkeypatch.setenv("BAMBULAB_HOST", "192.168.1.100")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "A123")
    monkeypatch.setenv("BAMBULAB_USERNAME", "bblp")

    mock_collector = MagicMock()
    mock_app = MagicMock()
    shutdown_handlers = []

    def capture_on_event(event_name):
        def decorator(func):
            if event_name == "shutdown":
                shutdown_handlers.append(func)
            return func
        return decorator

    mock_app.on_event = capture_on_event

    with patch("bambulab_metrics_exporter.main.PollingCollector", return_value=mock_collector):
        with patch("bambulab_metrics_exporter.main.build_app", return_value=mock_app):
            with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                with patch("bambulab_metrics_exporter.main.sync_env_file"):
                    with patch("bambulab_metrics_exporter.main.startup_validate"):
                        main.run()

    # Verify shutdown handler was registered and call it
    assert len(shutdown_handlers) == 1
    shutdown_handlers[0]()
    mock_collector.stop.assert_called_once()
