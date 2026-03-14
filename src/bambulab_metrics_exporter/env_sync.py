from __future__ import annotations

import os
from pathlib import Path

ALLOWED_ENV_KEYS = [
    "BAMBULAB_TRANSPORT",
    "BAMBULAB_HOST",
    "BAMBULAB_PORT",
    "BAMBULAB_SERIAL",
    "BAMBULAB_ACCESS_CODE",
    "BAMBULAB_USERNAME",
    "BAMBULAB_REQUEST_PUSHALL",
    "BAMBULAB_CLOUD_MQTT_HOST",
    "BAMBULAB_CLOUD_MQTT_PORT",
    "BAMBULAB_CLOUD_USER_ID",
    "BAMBULAB_CLOUD_ACCESS_TOKEN",
    "BAMBULAB_CLOUD_REFRESH_TOKEN",
    "BAMBULAB_CLOUD_EMAIL",
    "BAMBULAB_CLOUD_CODE",
    "BAMBULAB_CONFIG_DIR",
    "BAMBULAB_CREDENTIALS_FILE",
    "BAMBULAB_SECRET_KEY",
    "POLLING_INTERVAL_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "RECONNECT_INTERVAL_SECONDS",
    "LISTEN_HOST",
    "LISTEN_PORT",
    "PRINTER_NAME_LABEL",
    "BAMBULAB_PRINTER_NAME",
    "LOG_LEVEL",
]


def _shell_escape(value: str) -> str:
    if value == "":
        return "''"
    if all(ch.isalnum() or ch in "-._:/@" for ch in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def sync_env_file(env_file: Path) -> None:
    existing: dict[str, str] = {}
    lines: list[str] = []

    if env_file.exists():
        lines = env_file.read_text().splitlines()
        for line in lines:
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            existing[key.strip()] = val

    merged = dict(existing)
    for key in ALLOWED_ENV_KEYS:
        if key in os.environ:
            merged[key] = _shell_escape(os.environ[key])

    output_lines: list[str] = []
    written = set()
    for line in lines:
        if not line or line.strip().startswith("#") or "=" not in line:
            output_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in merged:
            output_lines.append(f"{key}={merged[key]}")
            written.add(key)
        else:
            output_lines.append(line)

    for key in ALLOWED_ENV_KEYS:
        if key in merged and key not in written:
            output_lines.append(f"{key}={merged[key]}")

    env_file.write_text("\n".join(output_lines).rstrip() + "\n")
    try:
        env_file.chmod(0o600)
    except OSError:
        pass
