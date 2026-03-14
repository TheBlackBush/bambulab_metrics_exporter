from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from bambulab_metrics_exporter import main
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_main_run_probe_discovers_name(monkeypatch) -> None:
    """Test that probe discovers printer name and updates env"""
    monkeypatch.setenv("BAMBULAB_HOST", "192.168.1.100")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "A123")
    monkeypatch.setenv("BAMBULAB_USERNAME", "bblp")
    monkeypatch.delenv("PRINTER_NAME_LABEL", raising=False)

    mock_client = MagicMock()
    mock_snapshot = PrinterSnapshot(connected=True, raw={"print": {"dev_name": "MyPrinter"}})
    mock_client.fetch_snapshot.return_value = mock_snapshot

    mock_collector = MagicMock()
    mock_app = MagicMock()

    with patch("bambulab_metrics_exporter.main.build_client", return_value=mock_client):
        with patch("bambulab_metrics_exporter.main.PollingCollector", return_value=mock_collector):
            with patch("bambulab_metrics_exporter.main.build_app", return_value=mock_app):
                with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                    with patch("bambulab_metrics_exporter.main.sync_env_file"):
                        with patch("bambulab_metrics_exporter.main.startup_validate"):
                            main.run()

    # Verify name was discovered and set
    assert os.environ.get("BAMBULAB_PRINTER_NAME") == "MyPrinter"
    mock_client.connect.assert_called()
    mock_client.disconnect.assert_called()


def test_main_run_probe_fails_gracefully(monkeypatch, caplog) -> None:
    """Test that probe failure is non-fatal"""
    monkeypatch.setenv("BAMBULAB_HOST", "192.168.1.100")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "A123")
    monkeypatch.setenv("BAMBULAB_USERNAME", "bblp")

    mock_client = MagicMock()
    mock_client.fetch_snapshot.side_effect = Exception("probe failed")

    mock_collector = MagicMock()
    mock_app = MagicMock()

    with patch("bambulab_metrics_exporter.main.build_client", return_value=mock_client):
        with patch("bambulab_metrics_exporter.main.PollingCollector", return_value=mock_collector):
            with patch("bambulab_metrics_exporter.main.build_app", return_value=mock_app):
                with patch("bambulab_metrics_exporter.main.uvicorn.run"):
                    with patch("bambulab_metrics_exporter.main.sync_env_file"):
                        with patch("bambulab_metrics_exporter.main.startup_validate"):
                            main.run()

    assert "Initial name discovery probe failed (non-fatal)" in caplog.text
    mock_client.disconnect.assert_called()


def test_main_shutdown_handler(monkeypatch) -> None:
    """Test that shutdown handler is registered"""
    monkeypatch.setenv("BAMBULAB_HOST", "192.168.1.100")
    monkeypatch.setenv("BAMBULAB_SERIAL", "S123")
    monkeypatch.setenv("BAMBULAB_ACCESS_CODE", "A123")
    monkeypatch.setenv("BAMBULAB_USERNAME", "bblp")

    mock_client = MagicMock()
    mock_client.fetch_snapshot.return_value = PrinterSnapshot(connected=False, raw={})

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

    with patch("bambulab_metrics_exporter.main.build_client", return_value=mock_client):
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
