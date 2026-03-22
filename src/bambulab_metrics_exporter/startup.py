from __future__ import annotations

import logging
import os
from pathlib import Path

from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthInvalidError,
    CloudAuthTransientError,
    login_with_code,
    refresh_access_token,
    send_code,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials
from bambulab_metrics_exporter.env_sync import sync_env_file

logger = logging.getLogger(__name__)


def startup_validate(settings: Settings) -> None:
    if settings.bambulab_transport == "local_mqtt":
        _validate_local(settings)
        return

    if settings.bambulab_transport == "cloud_mqtt":
        _validate_cloud(settings)
        return


def _probe_connection(settings: Settings) -> bool:
    client = build_client(settings)
    try:
        client.connect()
        snapshot = client.fetch_snapshot(settings.request_timeout_seconds)
        return bool(snapshot.connected and snapshot.raw)
    except Exception:
        logger.exception("Connectivity probe failed")
        return False
    finally:
        try:
            client.disconnect()
        except Exception:
            logger.exception("Client disconnect failed during probe")


def _validate_local(settings: Settings) -> None:
    missing = [
        key
        for key, val in {
            "BAMBULAB_HOST": settings.bambulab_host,
            "BAMBULAB_SERIAL": settings.bambulab_serial,
            "BAMBULAB_ACCESS_CODE": settings.bambulab_access_code,
        }.items()
        if not val
    ]
    if missing:
        raise RuntimeError(
            "Local MQTT selected but required env vars are missing: "
            + ", ".join(missing)
        )

    if not _probe_connection(settings):
        raise RuntimeError(
            "Local MQTT connection test failed. Check BAMBULAB_HOST/BAMBULAB_SERIAL/"
            "BAMBULAB_ACCESS_CODE and LAN mode in printer settings."
        )


def _validate_cloud(settings: Settings) -> None:
    has_uid = bool(settings.bambulab_cloud_user_id)
    has_token = bool(settings.bambulab_cloud_access_token)

    if has_uid and has_token and _probe_connection(settings):
        return

    # Probe failed (or credentials missing). Try refresh token before 2FA reauth.
    refresh_token = settings.bambulab_cloud_refresh_token
    if refresh_token:
        logger.info("Access token invalid; attempting refresh using BAMBULAB_CLOUD_REFRESH_TOKEN")
        try:
            _try_token_refresh(settings, refresh_token)
            refreshed = Settings()
            if _probe_connection(refreshed):
                logger.info("Token refresh succeeded; cloud connection restored")
                return
            logger.warning("Refresh produced new tokens but probe still failed; falling back to re-auth")
        except CloudAuthTransientError as exc:
            # Network/server issue — don't force 2FA; surface the transient error clearly
            raise RuntimeError(
                f"Cloud token refresh failed due to a transient network or API issue: {exc}. "
                "Will not force 2FA. Check network connectivity and retry."
            ) from exc
        except CloudAuthInvalidError:
            logger.warning("Refresh token is invalid or expired; falling back to email/code re-auth")
        # CloudAuthInvalidError => fall through to email/code reauth below
    else:
        logger.warning("No refresh token available; skipping refresh and attempting cloud re-auth")

    logger.warning("Cloud credentials missing or invalid, attempting cloud re-auth")
    _try_cloud_reauth(settings)

    refreshed = Settings()
    refreshed.require_transport_config()
    if not _probe_connection(refreshed):
        raise RuntimeError(
            "Cloud connection failed after re-auth. Verify BAMBULAB_SERIAL and that 2FA code is fresh."
        )


def _try_token_refresh(settings: Settings, refresh_token: str) -> None:
    """Exchange ``refresh_token`` for new credentials and persist them.

    Raises:
        CloudAuthInvalidError: Token definitively rejected — caller should fall back to 2FA.
        CloudAuthTransientError: Network/API issue — caller should NOT force 2FA.
    """
    result = refresh_access_token(refresh_token)  # may raise CloudAuthInvalidError / CloudAuthTransientError

    os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] = result.access_token
    os.environ["BAMBULAB_CLOUD_REFRESH_TOKEN"] = result.refresh_token
    if result.user_id:
        os.environ["BAMBULAB_CLOUD_USER_ID"] = result.user_id

    secret_key = os.getenv("BAMBULAB_SECRET_KEY", settings.bambulab_secret_key)
    if secret_key:
        cred_path = Path(settings.bambulab_config_dir) / settings.bambulab_credentials_file
        save_encrypted_credentials(
            path=cred_path,
            secret=secret_key,
            payload={
                "BAMBULAB_CLOUD_USER_ID": result.user_id or settings.bambulab_cloud_user_id,
                "BAMBULAB_CLOUD_ACCESS_TOKEN": result.access_token,
                "BAMBULAB_CLOUD_REFRESH_TOKEN": result.refresh_token,
                "BAMBULAB_CLOUD_MQTT_HOST": settings.bambulab_cloud_mqtt_host,
                "BAMBULAB_CLOUD_MQTT_PORT": str(settings.bambulab_cloud_mqtt_port),
            },
        )
        sync_env_file(Path(".env"))
        logger.info("Refreshed cloud credentials persisted to encrypted store")
    else:
        logger.warning(
            "BAMBULAB_SECRET_KEY not set; refreshed tokens applied to env only (not persisted to disk)"
        )


def _try_cloud_reauth(settings: Settings) -> None:
    email = os.getenv("BAMBULAB_CLOUD_EMAIL", "")
    code = os.getenv("BAMBULAB_CLOUD_CODE", "")
    secret_key = os.getenv("BAMBULAB_SECRET_KEY", settings.bambulab_secret_key)

    if not email:
        raise RuntimeError(
            "Cloud auth recovery requires BAMBULAB_CLOUD_EMAIL. "
            "Set it and optionally BAMBULAB_CLOUD_CODE for automatic login."
        )

    if not code:
        send_code(email)
        raise RuntimeError(
            "Cloud 2FA code was sent to email. Set BAMBULAB_CLOUD_CODE and restart container."
        )

    result = login_with_code(email=email, code=code)

    os.environ["BAMBULAB_CLOUD_USER_ID"] = result.user_id
    os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] = result.access_token
    os.environ["BAMBULAB_CLOUD_REFRESH_TOKEN"] = result.refresh_token

    if not secret_key:
        raise RuntimeError(
            "BAMBULAB_SECRET_KEY is required to store cloud credentials securely for next runs."
        )

    cred_path = Path(settings.bambulab_config_dir) / settings.bambulab_credentials_file
    save_encrypted_credentials(
        path=cred_path,
        secret=secret_key,
        payload={
            "BAMBULAB_CLOUD_USER_ID": result.user_id,
            "BAMBULAB_CLOUD_ACCESS_TOKEN": result.access_token,
            "BAMBULAB_CLOUD_REFRESH_TOKEN": result.refresh_token,
            "BAMBULAB_CLOUD_MQTT_HOST": settings.bambulab_cloud_mqtt_host,
            "BAMBULAB_CLOUD_MQTT_PORT": str(settings.bambulab_cloud_mqtt_port),
        },
    )

    sync_env_file(Path(".env"))
    logger.info("Cloud credentials re-authenticated and persisted")
