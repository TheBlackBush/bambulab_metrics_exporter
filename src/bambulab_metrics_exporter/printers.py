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
    write_private_file,
)
from bambulab_metrics_exporter.overrides import DEFAULT_CONFIG_DIR
from bambulab_metrics_exporter.overrides import lock as overrides_lock

logger = logging.getLogger(__name__)

PRINTERS_FILE = "printers.enc.json"
UNREADABLE_COPY_FILE = f"{PRINTERS_FILE}.bad"
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
        self._unreadable = False
        self._unreadable_logged = False
        self._ignored_logged = False

    @staticmethod
    def _path() -> Path:
        return Path(os.getenv("BAMBULAB_CONFIG_DIR", DEFAULT_CONFIG_DIR)) / PRINTERS_FILE

    @staticmethod
    def _secret() -> str:
        return os.getenv("BAMBULAB_SECRET_KEY", "")

    @property
    def unreadable(self) -> bool:
        """A saved file was there but gave no list at the last read. No I/O and no lock, so
        rendering a page cannot wait on a login that holds the overrides lock."""
        return self._unreadable

    def _mark_unreadable(self, reason: str) -> None:
        self._unreadable = True
        if not self._unreadable_logged:
            self._unreadable_logged = True
            logger.warning(
                "The saved printer list (%s) could not be read (%s); check BAMBULAB_SECRET_KEY. "
                "Using environment variables",
                PRINTERS_FILE,
                reason,
            )

    def _read_file(self) -> list[PrinterConfig] | None:
        """None when there is no list to use; ``unreadable`` tells why. Only the exception
        class is logged: the message could carry file content."""
        self._unreadable = False
        path, secret = self._path(), self._secret()
        try:
            if not path.exists():
                return None
            if not secret:
                self._mark_unreadable("no key set")
                return None
            items = load_encrypted_credentials(path, secret).get("printers")
            if not isinstance(items, list):
                raise ValueError("no printer list in the file")
            configs = [config for config in map(_parse, items) if config is not None]
            if items and not configs:
                raise ValueError("no usable printer in the file")
        except Exception as exc:  # noqa: BLE001 - any failure keeps the env fallback
            self._mark_unreadable(type(exc).__name__)
            return None
        ignored = len(items) - len(configs)
        if ignored and not self._ignored_logged:
            self._ignored_logged = True
            logger.warning("%d of %d saved printers were ignored", ignored, len(items))
        return configs

    def _keep_unreadable_copy(self) -> None:
        """An unreadable file may be fine with the right key, so it is never just replaced.
        A failed copy raises: nothing is lost then, and the save or clear does not happen."""
        self._read_file()
        if self._unreadable:
            path = self._path()
            write_private_file(path.with_name(UNREADABLE_COPY_FILE), path.read_bytes())

    def load(self) -> list[PrinterConfig] | None:
        with overrides_lock:
            if self._session is not None:
                return list(self._session)
            return self._read_file()

    def save(self, configs: list[PrinterConfig]) -> bool:
        with overrides_lock:
            secret = self._secret()
            if not secret:
                self._session = list(configs)
                return False
            self._keep_unreadable_copy()
            save_encrypted_credentials(
                self._path(), secret, {"printers": [asdict(config) for config in configs]}
            )
            self._session = None
            self._unreadable = False
            return True

    def clear(self) -> None:
        with overrides_lock:
            self._keep_unreadable_copy()
            self._session = None
            self._path().unlink(missing_ok=True)
            self._unreadable = False


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
