from __future__ import annotations

from bambulab_metrics_exporter import main
from bambulab_metrics_exporter.config import Settings


class _CollectorStub:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


def test_run_wires_components(monkeypatch) -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL1",
        bambulab_cloud_user_id="uid",
        bambulab_cloud_access_token="token",
    )

    monkeypatch.setattr("bambulab_metrics_exporter.main._safe_load_dotenv", lambda: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main._bootstrap_cloud_credentials", lambda: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main.Settings", lambda: settings)
    monkeypatch.setattr("bambulab_metrics_exporter.main.startup_validate", lambda s: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main._persist_runtime_env", lambda p: None)
    monkeypatch.setattr("bambulab_metrics_exporter.main.build_client", lambda s: object())

    collector = _CollectorStub()
    monkeypatch.setattr("bambulab_metrics_exporter.main.PollingCollector", lambda client, metrics, settings: collector)

    app_holder = {}

    class _AppStub:
        def on_event(self, _name):
            def deco(fn):
                app_holder["shutdown"] = fn
                return fn

            return deco

    monkeypatch.setattr("bambulab_metrics_exporter.main.build_app", lambda metrics, collector: _AppStub())
    monkeypatch.setattr("bambulab_metrics_exporter.main.uvicorn.run", lambda *a, **k: None)

    main.run()

    assert collector.started is True
    assert "shutdown" in app_holder
