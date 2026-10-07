"""Cloud credential recovery: encrypted-store helpers, the re-auth banner, and the
interactive ``bambulab-reauth`` command.

The exporter never exits in a restart loop when cloud credentials are rejected. The
runtime logs instructions and waits for new credentials from the /auth page or from
``bambulab-reauth``, which writes the encrypted store from inside the running container.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from pathlib import Path
from typing import Any

from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthError,
    LoginResult,
    login_with_code,
    send_code,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import (
    load_encrypted_credentials,
    save_encrypted_credentials,
)
from bambulab_metrics_exporter.env_sync import sync_env_file

logger = logging.getLogger(__name__)

CREDENTIAL_KEYS: tuple[str, ...] = (
    "BAMBULAB_CLOUD_USER_ID",
    "BAMBULAB_CLOUD_ACCESS_TOKEN",
    "BAMBULAB_CLOUD_REFRESH_TOKEN",
    "BAMBULAB_CLOUD_MQTT_HOST",
    "BAMBULAB_CLOUD_MQTT_PORT",
)

_SETTINGS_FIELDS: dict[str, str] = {
    "BAMBULAB_CLOUD_USER_ID": "bambulab_cloud_user_id",
    "BAMBULAB_CLOUD_ACCESS_TOKEN": "bambulab_cloud_access_token",
    "BAMBULAB_CLOUD_REFRESH_TOKEN": "bambulab_cloud_refresh_token",
    "BAMBULAB_CLOUD_MQTT_HOST": "bambulab_cloud_mqtt_host",
}

REAUTH_COMMAND = "docker exec -it <container> bambulab-reauth"


def credentials_path(settings: Settings) -> Path:
    return Path(settings.bambulab_config_dir) / settings.bambulab_credentials_file


def _secret_key(settings: Settings) -> str:
    return os.getenv("BAMBULAB_SECRET_KEY", "") or settings.bambulab_secret_key


def load_stored_credentials(settings: Settings) -> dict[str, str] | None:
    """Return usable credentials from the encrypted store, or None.

    A missing file, missing secret, undecryptable file or incomplete payload all return
    None; the reason is logged without any credential content.
    """
    path = credentials_path(settings)
    secret = _secret_key(settings)
    if not secret or not path.exists():
        return None
    try:
        raw: dict[str, Any] = load_encrypted_credentials(path, secret)
    except Exception:  # noqa: BLE001 - any decrypt/parse failure means "unusable"
        logger.warning(
            "Encrypted credentials could not be read (wrong BAMBULAB_SECRET_KEY or damaged file)"
        )
        return None
    payload = {k: str(raw[k]) for k in CREDENTIAL_KEYS if isinstance(raw.get(k), str) and raw[k]}
    if "BAMBULAB_CLOUD_USER_ID" not in payload or "BAMBULAB_CLOUD_ACCESS_TOKEN" not in payload:
        logger.warning("Encrypted credentials are incomplete; ignoring them")
        return None
    return payload


def apply_credentials(settings: Settings, payload: dict[str, str]) -> None:
    """Apply credentials to the process environment and to ``settings`` in place, so the
    client built from ``settings`` after startup uses them."""
    for key, value in payload.items():
        os.environ[key] = value
        field = _SETTINGS_FIELDS.get(key)
        if field:
            setattr(settings, field, value)
    port = payload.get("BAMBULAB_CLOUD_MQTT_PORT")
    if port and port.isdigit():
        settings.bambulab_cloud_mqtt_port = int(port)


def differs_from_settings(settings: Settings, payload: dict[str, str]) -> bool:
    return any(
        getattr(settings, field) != payload.get(key)
        for key, field in _SETTINGS_FIELDS.items()
        if key in payload
    )


def _hand_over_to_runtime_user(path: Path) -> None:
    """``docker exec`` runs as root; give files back to the PUID/PGID the exporter runs as."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        return
    uid = os.getenv("PUID", "")
    gid = os.getenv("PGID", "")
    if uid.isdigit() and gid.isdigit() and path.exists():
        try:
            os.chown(path, int(uid), int(gid))
        except OSError:
            logger.warning("Could not change ownership of %s", path.name)


def save_login_result(settings: Settings, result: LoginResult) -> dict[str, str]:
    """Persist a fresh login to the encrypted store and ``.env``; return the payload."""
    secret = _secret_key(settings)
    if not secret:
        raise RuntimeError(
            "BAMBULAB_SECRET_KEY is required to store cloud credentials for the next start."
        )
    payload = {
        "BAMBULAB_CLOUD_USER_ID": result.user_id or settings.bambulab_cloud_user_id,
        "BAMBULAB_CLOUD_ACCESS_TOKEN": result.access_token,
        "BAMBULAB_CLOUD_REFRESH_TOKEN": result.refresh_token,
        "BAMBULAB_CLOUD_MQTT_HOST": settings.bambulab_cloud_mqtt_host,
        "BAMBULAB_CLOUD_MQTT_PORT": str(settings.bambulab_cloud_mqtt_port),
    }
    path = credentials_path(settings)
    save_encrypted_credentials(path=path, secret=secret, payload=payload)
    _hand_over_to_runtime_user(path)
    apply_credentials(settings, payload)
    env_file = Path(".env")
    try:
        sync_env_file(env_file)
        _hand_over_to_runtime_user(env_file)
    except OSError:
        logger.warning("Skipping .env sync (not writable); encrypted credentials were saved")
    return payload


def log_reauth_banner(reason: str) -> None:
    lines = [
        "=" * 72,
        "BAMBU CLOUD RE-AUTHENTICATION REQUIRED",
        f"Reason: {reason}",
        "",
        "The exporter is waiting and will resume automatically, no restart needed.",
        "Either open the connection page in a browser:",
        "",
        "    http://<docker-host>:<port>/auth",
        "",
        "or run from the Docker host:",
        "",
        f"    {REAUTH_COMMAND}",
        "",
        "Both send a verification code to your Bambu account email and save",
        "encrypted credentials that this exporter picks up.",
        "",
        "Legacy alternative: set BAMBULAB_CLOUD_EMAIL and BAMBULAB_CLOUD_CODE,",
        "then recreate the container (on Unraid: Edit, then Apply).",
        "=" * 72,
    ]
    for line in lines:
        logger.error(line)


# ---------------------------------------------------------------------------
# bambulab-reauth command
# ---------------------------------------------------------------------------


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def main() -> int:
    """Interactive re-authentication, run inside the exporter container."""
    if not sys.stdin.isatty():
        print(
            "bambulab-reauth is interactive. Run it with: " + REAUTH_COMMAND,
            file=sys.stderr,
        )
        return 2

    settings = Settings()
    if not _secret_key(settings):
        print(
            "BAMBULAB_SECRET_KEY is not set in this container. Set a stable secret key, "
            "recreate the container, then run this command again.",
            file=sys.stderr,
        )
        return 2

    print("Bambu Cloud re-authentication")
    print("Credentials are saved encrypted to the exporter's config directory.\n")
    email = _prompt("Bambu account email", os.getenv("BAMBULAB_CLOUD_EMAIL", ""))
    if not email:
        print("An email address is required.", file=sys.stderr)
        return 2

    code = getpass.getpass(
        "If you already received a verification code, enter it now "
        "(or press Enter to send a new one): "
    ).strip()
    try:
        if not code:
            send_code(email)
            print("A verification code was sent to your email.")
            code = getpass.getpass("Verification code: ").strip()
        if not code:
            print("No code entered; nothing was changed.", file=sys.stderr)
            return 2
        result = login_with_code(email=email, code=code)
        save_login_result(settings, result)
    except CloudAuthError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("\nCredentials saved. A waiting exporter resumes within a few seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
