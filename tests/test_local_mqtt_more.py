from __future__ import annotations

import json
from types import SimpleNamespace

from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient
from bambulab_metrics_exporter.config import Settings


class _FakeMQTTClient:
    def __init__(self) -> None:
        self.published = []
        self.connected = False

    def username_pw_set(self, *args, **kwargs):
        pass

    def tls_set(self, *args, **kwargs):
        pass

    def tls_insecure_set(self, *args, **kwargs):
        pass

    def enable_logger(self, *args, **kwargs):
        pass

    def connect(self, *args, **kwargs):
        self.connected = True

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        self.connected = False

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))

    def subscribe(self, *args, **kwargs):
        pass


def _settings() -> Settings:
    return Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial="SERIALX",
        bambulab_access_code="ACCESS",
        request_timeout_seconds=0.2,
    )


def test_fetch_snapshot_timeout_returns_partial(monkeypatch) -> None:
    fake = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake)
    client = LocalMqttBambuClient(_settings())

    snap = client.fetch_snapshot(0.01)
    assert snap.raw == {}


def test_request_pushall_publish(monkeypatch) -> None:
    fake = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake)
    client = LocalMqttBambuClient(_settings())

    client._request_pushall()
    assert fake.published
    topic, payload, qos = fake.published[0]
    assert topic == "device/SERIALX/request"
    assert qos == 1
    assert json.loads(payload)["pushing"]["command"] == "pushall"


def test_on_connect_failure_does_not_set_connected(monkeypatch) -> None:
    fake = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake)
    client = LocalMqttBambuClient(_settings())

    client._on_connect(fake, None, None, 5, None)
    assert client._connected is False


def test_on_message_invalid_json(monkeypatch) -> None:
    fake = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake)
    client = LocalMqttBambuClient(_settings())

    msg = SimpleNamespace(topic="device/SERIALX/report", payload=b"not-json")
    client._on_message(None, None, msg)
    assert client._latest_state == {}
