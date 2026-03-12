from __future__ import annotations

import pytest

from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.startup import _probe_connection, _validate_cloud, startup_validate


class _ClientOK:
    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def fetch_snapshot(self, _timeout: float):
        from bambulab_metrics_exporter.models import PrinterSnapshot

        return PrinterSnapshot(connected=True, raw={"print": {"mc_percent": 1}})


class _ClientFail:
    def connect(self) -> None:
        raise RuntimeError("boom")

    def disconnect(self) -> None:
        pass

    def fetch_snapshot(self, _timeout: float):
        raise RuntimeError("boom")


def test_probe_connection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(bambulab_transport="cloud_mqtt", bambulab_serial="S", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t")
    monkeypatch.setattr("bambulab_metrics_exporter.startup.build_client", lambda s: _ClientOK())
    assert _probe_connection(settings) is True


def test_probe_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(bambulab_transport="cloud_mqtt", bambulab_serial="S", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t")
    monkeypatch.setattr("bambulab_metrics_exporter.startup.build_client", lambda s: _ClientFail())
    assert _probe_connection(settings) is False


def test_validate_cloud_raises_after_failed_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(bambulab_transport="cloud_mqtt", bambulab_serial="S", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t")
    monkeypatch.setattr("bambulab_metrics_exporter.startup._probe_connection", lambda s: False)
    monkeypatch.setattr("bambulab_metrics_exporter.startup._try_cloud_reauth", lambda s: None)
    with pytest.raises(RuntimeError):
        _validate_cloud(settings)


def test_startup_validate_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"local": 0, "cloud": 0}
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_local", lambda s: calls.__setitem__("local", 1))
    monkeypatch.setattr("bambulab_metrics_exporter.startup._validate_cloud", lambda s: calls.__setitem__("cloud", 1))

    startup_validate(Settings(bambulab_transport="local_mqtt", bambulab_host="h", bambulab_serial="s", bambulab_access_code="a"))
    startup_validate(Settings(bambulab_transport="cloud_mqtt", bambulab_serial="s", bambulab_cloud_user_id="u", bambulab_cloud_access_token="t"))

    assert calls["local"] == 1
    assert calls["cloud"] == 1
