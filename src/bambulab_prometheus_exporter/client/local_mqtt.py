from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from copy import deepcopy
from typing import Any

import paho.mqtt.client as mqtt

from bambulab_prometheus_exporter.config import Settings
from bambulab_prometheus_exporter.models import PrinterSnapshot

logger = logging.getLogger(__name__)


class LocalMqttBambuClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._topic_report = f"device/{settings.bambulab_serial}/report"
        self._topic_request = f"device/{settings.bambulab_serial}/request"

        self._lock = threading.Lock()
        self._latest_state: dict[str, Any] = {}
        self._connected = False
        self._last_message_ts = 0.0

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.username_pw_set(settings.bambulab_username, settings.bambulab_access_code)
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)
        self._client.tls_insecure_set(True)
        self._client.enable_logger(logger)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        logger.info("Connecting to printer mqtt", extra={"host": self._settings.bambulab_host})
        self._client.connect(self._settings.bambulab_host, self._settings.bambulab_port, keepalive=20)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        if self._settings.bambulab_request_pushall:
            self._request_pushall()

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest_state:
                    return PrinterSnapshot(connected=self._connected, raw=deepcopy(self._latest_state))
            time.sleep(0.1)

        with self._lock:
            return PrinterSnapshot(connected=self._connected, raw=deepcopy(self._latest_state))

    def _request_pushall(self) -> None:
        payload = {
            "pushing": {
                "sequence_id": "0",
                "command": "pushall",
                "version": 1,
                "push_target": 1,
            }
        }
        self._client.publish(self._topic_request, json.dumps(payload), qos=1)

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code != 0:
            logger.error("MQTT connect failed", extra={"reason": str(reason_code)})
            return
        with self._lock:
            self._connected = True
        logger.info("MQTT connected")
        _client.subscribe(self._topic_report, qos=1)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        with self._lock:
            self._connected = False
        logger.warning("MQTT disconnected", extra={"reason": str(reason_code)})

    def _on_message(self, _client: mqtt.Client, _userdata: object, msg: mqtt.MQTTMessage) -> None:
        if msg.topic != self._topic_report:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            logger.exception("Failed to decode MQTT payload")
            return

        with self._lock:
            _deep_merge_in_place(self._latest_state, payload)
            self._last_message_ts = time.time()


def _deep_merge_in_place(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, source_value in source.items():
        target_value = target.get(key)
        if isinstance(source_value, dict):
            if not isinstance(target_value, dict):
                target[key] = {}
            _deep_merge_in_place(target[key], source_value)
            continue
        target[key] = source_value
