"""Connection settings saved from the /auth page.

They are stored encrypted next to the cloud credentials and take precedence over
environment variables (including container templates), so a choice made on the page
survives restarts. Clearing them returns control to the environment.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from bambulab_metrics_exporter.credentials_store import (
    load_encrypted_credentials,
    save_encrypted_credentials,
)
from bambulab_metrics_exporter.security import ensure_parent

logger = logging.getLogger(__name__)

OVERRIDES_FILE = "connection-overrides.enc.json"
DEFAULT_CONFIG_DIR = "/config/bambulab-metrics-exporter"

OVERRIDE_KEYS: tuple[str, ...] = (
    "BAMBULAB_TRANSPORT",
    "BAMBULAB_HOST",
    "BAMBULAB_PORT",
    "BAMBULAB_SERIAL",
    "BAMBULAB_ACCESS_CODE",
    "BAMBULAB_USERNAME",
)

# Values the container started with, recorded before the first override so "reset"
# can restore them without a restart.
_ORIGINAL_ENV: dict[str, str | None] = {}


def set_env(key: str, value: str) -> None:
    if key not in _ORIGINAL_ENV:
        _ORIGINAL_ENV[key] = os.environ.get(key)
    os.environ[key] = value


def restore_original_env() -> None:
    for key, value in _ORIGINAL_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _ORIGINAL_ENV.clear()


def overrides_path() -> Path:
    return Path(os.getenv("BAMBULAB_CONFIG_DIR", DEFAULT_CONFIG_DIR)) / OVERRIDES_FILE


def _secret() -> str:
    return os.getenv("BAMBULAB_SECRET_KEY", "")


def load_overrides() -> dict[str, str]:
    """Return saved overrides, or an empty dict when none are usable."""
    path = overrides_path()
    secret = _secret()
    if not secret or not path.exists():
        return {}
    try:
        raw = load_encrypted_credentials(path, secret)
    except Exception:  # noqa: BLE001 - unreadable means "no overrides"
        logger.warning("Saved /auth page settings could not be read; using environment variables")
        return {}
    return {k: str(raw[k]) for k in OVERRIDE_KEYS if isinstance(raw.get(k), str) and raw[k]}


def apply_overrides_to_env() -> list[str]:
    """Copy saved overrides into the process environment; return the keys applied."""
    values = load_overrides()
    for key, value in values.items():
        set_env(key, value)
    if values:
        logger.info(
            "Using connection settings saved from the /auth page (override env vars): %s",
            ", ".join(sorted(values)),
        )
    return sorted(values)


def save_overrides(values: dict[str, str]) -> bool:
    """Persist overrides (merged over existing ones). Returns False when no
    BAMBULAB_SECRET_KEY is set; the caller then applies them for this session only."""
    secret = _secret()
    if not secret:
        return False
    merged = {**load_overrides(), **{k: v for k, v in values.items() if k in OVERRIDE_KEYS}}
    path = overrides_path()
    ensure_parent(path)
    save_encrypted_credentials(path, secret, merged)
    return True


def clear_overrides() -> bool:
    path = overrides_path()
    if not path.exists():
        return False
    path.unlink()
    return True
