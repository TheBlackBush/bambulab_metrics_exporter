from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from copy import deepcopy
from typing import Any

import paho.mqtt.client as mqtt

from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.models import PrinterSnapshot

logger = logging.getLogger(__name__)


class LocalMqttBambuClient(BambuClient):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._topic_report = f"device/{settings.bambulab_serial}/report"
        self._topic_request = f"device/{settings.bambulab_serial}/request"

        self._lock = threading.Lock()
        self._latest_state: dict[str, Any] = {}
        self._connected = False
        self._auth_rejected = False
        self._last_message_ts = 0.0

        # paho v2 callback API (typed loosely for compatibility across stub versions)
        if hasattr(mqtt, "CallbackAPIVersion"):
            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        else:
            self._client = mqtt.Client()
        self._client.username_pw_set(settings.bambulab_username, settings.bambulab_access_code)
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)
        self._client.tls_insecure_set(True)
        self._client.enable_logger(logger)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        logger.info(
            "Connecting to printer mqtt: host=%s port=%s user=%s topic=%s",
            self._settings.bambulab_host,
            self._settings.bambulab_port,
            self._settings.bambulab_username,
            self._topic_report,
        )
        self._client.connect(self._settings.bambulab_host, self._settings.bambulab_port, keepalive=20)
        self._client.loop_start()

    @property
    def auth_rejected(self) -> bool:
        with self._lock:
            return self._auth_rejected

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
                    return self._build_snapshot()
            time.sleep(0.1)

        with self._lock:
            return self._build_snapshot()

    def _build_snapshot(self) -> PrinterSnapshot:
        """Build a snapshot from the merged state. Caller must hold `self._lock`."""
        return PrinterSnapshot(
            connected=self._connected,
            raw=deepcopy(self._latest_state),
            configured_serial=self._settings.bambulab_serial or None,
            configured_model=self._settings.bambulab_printer_model or None,
        )

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

    def _request_version(self) -> None:
        """Ask for the module list (read-only, no printer control).

        The reply arrives on the report topic as `info.module` and carries the
        product name used for model detection.
        """
        payload = {"info": {"sequence_id": "0", "command": "get_version"}}
        self._client.publish(self._topic_request, json.dumps(payload), qos=1)

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object | None,
    ) -> None:
        if reason_code != 0:
            with self._lock:
                self._auth_rejected = _is_auth_rejection(reason_code)
            logger.error(
                "MQTT connect failed: reason=%s host=%s port=%s user=%s topic=%s",
                str(reason_code),
                self._settings.bambulab_host,
                self._settings.bambulab_port,
                self._settings.bambulab_username,
                self._topic_report,
            )
            return
        with self._lock:
            self._connected = True
            self._auth_rejected = False
        logger.info("MQTT connected")
        _client.subscribe(self._topic_report, qos=1)
        if self._settings.bambulab_request_pushall:
            self._request_version()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: object,
        _flags: object,
        reason_code: object,
        _properties: object | None,
    ) -> None:
        with self._lock:
            self._connected = False
        logger.warning("MQTT disconnected: reason=%s", str(reason_code))

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


# CONNACK codes for refused credentials: MQTT 3.1.1 (4, 5) and the MQTT 5 values paho v2
# reports for them (134 bad user name or password, 135 not authorized).
_AUTH_REJECTION_CODES = {4, 5, 134, 135}


def _is_auth_rejection(reason_code: object) -> bool:
    value = getattr(reason_code, "value", reason_code)
    if isinstance(value, int) and value in _AUTH_REJECTION_CODES:
        return True
    return str(reason_code).strip().lower() in {"not authorized", "bad user name or password"}


def _deep_merge_in_place(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, source_value in source.items():
        target_value = target.get(key)
        if isinstance(source_value, dict):
            if not isinstance(target_value, dict):
                target[key] = {}
            _deep_merge_in_place(target[key], source_value)
            continue
        target[key] = source_value
