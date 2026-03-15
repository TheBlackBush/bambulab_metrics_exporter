"""Tests for bambulab_metrics_exporter.client.factory and logging_utils."""
from __future__ import annotations

import pytest

from bambulab_metrics_exporter.client.cloud_mqtt import CloudMqttBambuClient
from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.logging_utils import configure_logging


# ---------------------------------------------------------------------------
# Shared fake MQTT client used by multiple tests
# ---------------------------------------------------------------------------

class _FakeMQTTClient:
    def username_pw_set(self, *args, **kwargs): pass
    def tls_set(self, *args, **kwargs): pass
    def tls_insecure_set(self, *args, **kwargs): pass
    def enable_logger(self, *args, **kwargs): pass
    def connect(self, *args, **kwargs): pass
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def publish(self, *args, **kwargs): pass
    def subscribe(self, *args, **kwargs): pass


# ---------------------------------------------------------------------------
# build_client
# ---------------------------------------------------------------------------

def test_build_client_local() -> None:
    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SERIAL",
        bambulab_access_code="ACCESS",
    )
    client = build_client(settings)
    assert isinstance(client, LocalMqttBambuClient)


def test_build_client_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: _FakeMQTTClient())
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL",
        bambulab_cloud_user_id="123",
        bambulab_cloud_access_token="token",
    )
    client = build_client(settings)
    assert isinstance(client, CloudMqttBambuClient)


def test_build_client_unsupported() -> None:
    with pytest.raises(ValueError):
        build_client(Settings.model_construct(bambulab_transport="unsupported"))


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------

def test_configure_logging_smoke() -> None:
    configure_logging("INFO")
