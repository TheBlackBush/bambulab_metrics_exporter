"""Tests for bambulab_metrics_exporter.client.local_mqtt."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient, _deep_merge_in_place
from bambulab_metrics_exporter.config import Settings


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _SubClient:
    def __init__(self) -> None:
        self.subscribed: list[tuple[str, int]] = []

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append((topic, qos))


class _FakeMQTTClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, int]] = []
        self.connected = False

    def username_pw_set(self, *args, **kwargs): pass
    def tls_set(self, *args, **kwargs): pass
    def tls_insecure_set(self, *args, **kwargs): pass
    def enable_logger(self, *args, **kwargs): pass
    def connect(self, *args, **kwargs): self.connected = True
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): self.connected = False
    def publish(self, topic, payload, qos=0): self.published.append((topic, payload, qos))
    def subscribe(self, *args, **kwargs): pass


def _settings(serial: str = "SERIAL1", request_timeout: float | None = None) -> Settings:
    kwargs: dict = dict(
        bambulab_transport="local_mqtt",
        bambulab_host="127.0.0.1",
        bambulab_serial=serial,
        bambulab_access_code="abc",
    )
    if request_timeout is not None:
        kwargs["request_timeout_seconds"] = request_timeout
    return Settings(**kwargs)


# ---------------------------------------------------------------------------
# _deep_merge_in_place
# ---------------------------------------------------------------------------

def test_deep_merge_in_place() -> None:
    target = {"print": {"a": 1, "b": {"x": 1}}}
    source = {"print": {"b": {"y": 2}, "c": 3}}
    _deep_merge_in_place(target, source)
    assert target["print"]["a"] == 1
    assert target["print"]["b"]["x"] == 1
    assert target["print"]["b"]["y"] == 2
    assert target["print"]["c"] == 3


# ---------------------------------------------------------------------------
# _on_connect / _on_disconnect callbacks
# ---------------------------------------------------------------------------

def test_on_connect_success_subscribes() -> None:
    client = LocalMqttBambuClient(_settings())
    fake = _SubClient()

    client._on_connect(fake, None, None, 0, None)

    assert client._connected is True
    assert fake.subscribed[0][0] == "device/SERIAL1/report"


def test_on_connect_failure_does_not_set_connected(monkeypatch) -> None:
    fake_mqtt = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake_mqtt)
    client = LocalMqttBambuClient(_settings(serial="SERIALX"))

    client._on_connect(fake_mqtt, None, None, 5, None)
    assert client._connected is False


def test_on_connect_success_and_disconnect_callbacks(monkeypatch) -> None:
    """Covers _on_connect success + _on_disconnect via MagicMock."""
    settings = Settings(
        bambulab_host="localhost",
        bambulab_serial="S1",
        bambulab_access_code="A1",
    )
    client = LocalMqttBambuClient(settings)
    mqtt_mock = MagicMock()

    # failure
    client._on_connect(mqtt_mock, None, None, 1, None)
    assert not client._connected

    # success
    client._on_connect(mqtt_mock, None, None, 0, None)
    assert client._connected

    # disconnect
    client._on_disconnect(mqtt_mock, None, None, 0, None)
    assert not client._connected


# ---------------------------------------------------------------------------
# _on_message callback
# ---------------------------------------------------------------------------

def test_on_message_updates_state() -> None:
    client = LocalMqttBambuClient(_settings())
    payload = {"print": {"mc_percent": 55}}
    msg = SimpleNamespace(topic="device/SERIAL1/report", payload=json.dumps(payload).encode("utf-8"))

    client._on_message(None, None, msg)

    assert client._latest_state["print"]["mc_percent"] == 55


def test_on_message_wrong_topic_ignored(monkeypatch) -> None:
    fake_mqtt = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake_mqtt)
    client = LocalMqttBambuClient(_settings(serial="SERIALX"))

    msg_wrong = MagicMock()
    msg_wrong.topic = "wrong"
    client._on_message(fake_mqtt, None, msg_wrong)
    # No crash and state unchanged
    assert client._latest_state == {}


def test_on_message_invalid_json(monkeypatch) -> None:
    fake_mqtt = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake_mqtt)
    client = LocalMqttBambuClient(_settings(serial="SERIALX"))

    msg = SimpleNamespace(topic="device/SERIALX/report", payload=b"not-json")
    client._on_message(None, None, msg)
    assert client._latest_state == {}


# ---------------------------------------------------------------------------
# fetch_snapshot / _request_pushall
# ---------------------------------------------------------------------------

def test_fetch_snapshot_timeout_returns_partial(monkeypatch) -> None:
    fake = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake)
    client = LocalMqttBambuClient(_settings(serial="SERIALX", request_timeout=0.2))

    snap = client.fetch_snapshot(0.01)
    assert snap.raw == {}


def test_request_pushall_publish(monkeypatch) -> None:
    fake = _FakeMQTTClient()
    monkeypatch.setattr("bambulab_metrics_exporter.client.local_mqtt.mqtt.Client", lambda *a, **k: fake)
    client = LocalMqttBambuClient(_settings(serial="SERIALX", request_timeout=0.2))

    client._request_pushall()
    assert fake.published
    topic, payload, qos = fake.published[0]
    assert topic == "device/SERIALX/request"
    assert qos == 1
    assert json.loads(payload)["pushing"]["command"] == "pushall"
