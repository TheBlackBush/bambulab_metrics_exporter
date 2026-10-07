"""Connection settings saved from the /auth page.

They are stored encrypted next to the cloud credentials and take precedence over
environment variables (including container templates), so a choice made on the page
survives restarts. Clearing them returns control to the environment.
"""

from __future__ import annotations

import logging
import os
import threading
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

# Cloud credentials written by a page login. They live in the encrypted store, never in
# .env, so "Reset to env vars" can always return to the container's own credentials.
CLOUD_CREDENTIAL_KEYS: tuple[str, ...] = (
    "BAMBULAB_CLOUD_USER_ID",
    "BAMBULAB_CLOUD_ACCESS_TOKEN",
    "BAMBULAB_CLOUD_REFRESH_TOKEN",
    "BAMBULAB_CLOUD_MQTT_HOST",
    "BAMBULAB_CLOUD_MQTT_PORT",
)
DEFAULT_CREDENTIALS_FILE = "credentials.enc.json"

# Values the container started with, recorded before the first override so "reset"
# can restore them without a restart.
_ORIGINAL_ENV: dict[str, str | None] = {}

# Serializes /auth page changes (env writes, file saves, reset) across request threads.
lock = threading.RLock()


def remember_original(key: str) -> None:
    """Record the container's value of ``key`` before the page changes it."""
    with lock:
        if key not in _ORIGINAL_ENV:
            _ORIGINAL_ENV[key] = os.environ.get(key)


def set_env(key: str, value: str) -> None:
    with lock:
        remember_original(key)
        os.environ[key] = value


def page_login_active() -> bool:
    """True while cloud credentials from an /auth page login are in use: in this process
    (originals recorded) or from an earlier run (credentials backup present)."""
    with lock:
        if any(k in _ORIGINAL_ENV for k in CLOUD_CREDENTIAL_KEYS):
            return True
    return _backup_path(default_credentials_path()).exists()


def overridden_keys() -> set[str]:
    """Keys whose current value comes from the /auth page; kept out of .env."""
    with lock:
        keys = {k for k in _ORIGINAL_ENV if k in OVERRIDE_KEYS}
    if page_login_active():
        keys.update(CLOUD_CREDENTIAL_KEYS)
    return keys


def restore_original_env() -> None:
    with lock:
        for key, value in _ORIGINAL_ENV.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _ORIGINAL_ENV.clear()


def default_credentials_path() -> Path:
    return Path(os.getenv("BAMBULAB_CONFIG_DIR", DEFAULT_CONFIG_DIR)) / os.getenv(
        "BAMBULAB_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_FILE
    )


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
    with lock:
        merged = {**load_overrides(), **{k: v for k, v in values.items() if k in OVERRIDE_KEYS}}
        path = overrides_path()
        ensure_parent(path)
        save_encrypted_credentials(path, secret, merged)
    return True


def clear_overrides() -> bool:
    with lock:
        path = overrides_path()
        if not path.exists():
            return False
        path.unlink()
        return True


BACKUP_SUFFIX = ".before-auth-page"


def _backup_path(credentials: Path) -> Path:
    return credentials.with_name(credentials.name + BACKUP_SUFFIX)


def backup_credentials(credentials: Path) -> None:
    """Keep the credentials that existed before the first /auth page cloud login, so reset
    can put them back. An empty backup means "there were none"."""
    with lock:
        backup = _backup_path(credentials)
        if backup.exists():
            return
        ensure_parent(backup)
        data = credentials.read_bytes() if credentials.exists() else b""
        backup.write_bytes(data)
        backup.chmod(0o600)


def restore_credentials_backup(credentials: Path) -> bool:
    """Undo /auth page cloud logins. Returns True when a backup was restored."""
    with lock:
        backup = _backup_path(credentials)
        if not backup.exists():
            return False
        data = backup.read_bytes()
        if data:
            credentials.write_bytes(data)
            credentials.chmod(0o600)
        elif credentials.exists():
            credentials.unlink()
        backup.unlink()
        return True
