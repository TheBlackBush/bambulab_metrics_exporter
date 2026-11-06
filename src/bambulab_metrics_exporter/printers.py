"""The list of monitored printers.

With no saved list the process runs the single printer described by env vars and /auth
overrides. The first change on the /auth page saves the list, which then decides what runs.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import (
    load_encrypted_credentials,
    save_encrypted_credentials,
)
from bambulab_metrics_exporter.overrides import DEFAULT_CONFIG_DIR
from bambulab_metrics_exporter.overrides import lock as overrides_lock

logger = logging.getLogger(__name__)

PRINTERS_FILE = "printers.enc.json"
MAX_PRINTERS = 32
TRANSPORT_LOCAL = "local_mqtt"
TRANSPORT_CLOUD = "cloud_mqtt"
_TRANSPORTS = {TRANSPORT_LOCAL, TRANSPORT_CLOUD}


def mask_serial(serial: str) -> str:
    """Show only the model prefix of a serial on the unauthenticated page."""
    return f"{serial[:3]}{'*' * max(len(serial) - 3, 0)}" if serial else ""


def printer_id_for(serial: str) -> str:
    """Opaque id for forms, so the unauthenticated page never carries a raw serial."""
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class PrinterConfig:
    serial: str
    transport: str
    host: str = ""
    port: int = 8883
    access_code: str = ""
    name: str = ""
    model: str = ""
    env_printer: bool = False

    @property
    def printer_id(self) -> str:
        return printer_id_for(self.serial)

    @property
    def label(self) -> str:
        return self.name or mask_serial(self.serial)


def _parse(item: Any) -> PrinterConfig | None:
    if not isinstance(item, dict):
        return None
    serial, transport = item.get("serial"), item.get("transport")
    port = item.get("port", 8883)
    if not isinstance(serial, str) or not serial or transport not in _TRANSPORTS:
        return None
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    text = {
        key: value if isinstance(value := item.get(key, ""), str) else ""
        for key in ("host", "access_code", "name", "model")
    }
    return PrinterConfig(
        serial=serial, transport=transport, port=port,
        env_printer=item.get("env_printer") is True, **text,
    )


class PrinterStore:
    """Encrypted printer list. Without BAMBULAB_SECRET_KEY it lasts until the next restart."""

    def __init__(self) -> None:
        self._session: list[PrinterConfig] | None = None

    @staticmethod
    def _path() -> Path:
        return Path(os.getenv("BAMBULAB_CONFIG_DIR", DEFAULT_CONFIG_DIR)) / PRINTERS_FILE

    @staticmethod
    def _secret() -> str:
        return os.getenv("BAMBULAB_SECRET_KEY", "")

    def load(self) -> list[PrinterConfig] | None:
        with overrides_lock:
            if self._session is not None:
                return list(self._session)
            path, secret = self._path(), self._secret()
            if not secret or not path.exists():
                return None
            try:
                raw = load_encrypted_credentials(path, secret)
            except Exception:  # noqa: BLE001 - unreadable means "no saved list"
                logger.warning(
                    "The saved printer list could not be read; using environment variables"
                )
                return None
            items = raw.get("printers")
            if not isinstance(items, list):
                return None
            parsed = [_parse(item) for item in items]
            return [config for config in parsed if config is not None]

    def save(self, configs: list[PrinterConfig]) -> bool:
        with overrides_lock:
            secret = self._secret()
            if not secret:
                self._session = list(configs)
                return False
            save_encrypted_credentials(
                self._path(), secret, {"printers": [asdict(config) for config in configs]}
            )
            self._session = None
            return True

    def clear(self) -> None:
        with overrides_lock:
            self._session = None
            self._path().unlink(missing_ok=True)


def printer_settings(
    config: PrinterConfig, base: Callable[[], Settings] = Settings
) -> Settings:
    """Settings for one printer: shared values (cloud tokens, timeouts) come from ``base``."""
    settings = base()
    settings.bambulab_transport = config.transport
    settings.bambulab_serial = config.serial
    # The env printer keeps its exact label, even the "bambulab" fallback: the label is part
    # of series identity, so a change would split its history.
    settings.bambulab_printer_name = config.name if config.env_printer else config.label
    settings.bambulab_printer_model = config.model
    if not config.env_printer:
        settings.printer_name_label = ""
    if config.transport == TRANSPORT_LOCAL:
        settings.bambulab_host = config.host
        settings.bambulab_port = config.port
        settings.bambulab_access_code = config.access_code
    return settings
