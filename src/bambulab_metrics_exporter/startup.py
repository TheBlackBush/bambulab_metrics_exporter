from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.cloud_auth import (
    CloudAuthError,
    CloudAuthInvalidError,
    CloudAuthTransientError,
    login_with_code,
    refresh_access_token,
    send_code,
)
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials
from bambulab_metrics_exporter.env_sync import sync_env_file
from bambulab_metrics_exporter.reauth import (
    apply_credentials,
    credentials_path,
    differs_from_settings,
    load_stored_credentials,
    save_login_result,
)

logger = logging.getLogger(__name__)


class ReauthRequiredError(RuntimeError):
    """Cloud credentials were rejected and no automatic recovery worked."""


# Probe outcomes. Only a broker refusal (CONNACK 4/5) means the credentials are bad; a
# connection failure, timeout, or a printer that does not answer is an outage to retry.
PROBE_OK = "ok"
PROBE_REJECTED = "rejected"
PROBE_UNREACHABLE = "unreachable"

# The legacy env flow sends at most one verification email and tries each
# BAMBULAB_CLOUD_CODE value at most once per process, however often validation re-runs.
_legacy_lock = threading.Lock()
_legacy_state: dict[str, object] = {"code_sent": False, "codes_tried": set()}


def startup_validate(settings: Settings) -> None:
    if settings.bambulab_transport == "local_mqtt":
        _validate_local(settings)
        return

    if settings.bambulab_transport == "cloud_mqtt":
        _validate_cloud(settings)
        return


def _probe(settings: Settings) -> str:
    """Connect once and request a snapshot; classify the result (PROBE_*)."""
    client = build_client(settings)
    try:
        client.connect()
        snapshot = client.fetch_snapshot(settings.request_timeout_seconds)
        if snapshot.connected and snapshot.raw:
            return PROBE_OK
        return PROBE_REJECTED if getattr(client, "auth_rejected", False) else PROBE_UNREACHABLE
    except Exception:
        logger.exception("Connectivity probe failed")
        return PROBE_REJECTED if getattr(client, "auth_rejected", False) else PROBE_UNREACHABLE
    finally:
        try:
            client.disconnect()
        except Exception:
            logger.exception("Client disconnect failed during probe")


def _probe_connection(settings: Settings) -> bool:
    return _probe(settings) == PROBE_OK


def _outage(stage: str) -> RuntimeError:
    return RuntimeError(
        f"Bambu Cloud MQTT is unreachable or the printer did not respond ({stage}). "
        "Credentials were not rejected; retrying automatically."
    )


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
    """Get working cloud credentials into ``settings`` (updated in place).

    Order: current credentials, then the encrypted store (it may hold newer, rotated tokens
    than stale container env vars), then the refresh token, then the legacy
    BAMBULAB_CLOUD_EMAIL/BAMBULAB_CLOUD_CODE login. If all fail, the caller waits for new
    credentials (the /auth page or ``bambulab-reauth``) instead of exiting, so a restart
    policy cannot loop or resend codes.

    Raises:
        ReauthRequiredError: credentials are rejected; the caller waits for new ones.
        RuntimeError: a network/API outage; the caller retries later.
    """
    has_uid = bool(settings.bambulab_cloud_user_id)
    has_token = bool(settings.bambulab_cloud_access_token)

    if has_uid and has_token:
        result = _probe(settings)
        if result == PROBE_OK:
            return
        if result == PROBE_UNREACHABLE:
            raise _outage("current credentials")

    stored = load_stored_credentials(settings)
    if stored and differs_from_settings(settings, stored):
        logger.info("Current cloud credentials rejected; trying the encrypted credential store")
        apply_credentials(settings, stored)
        result = _probe(settings)
        if result == PROBE_OK:
            logger.info("Using cloud credentials from the encrypted store")
            return
        if result == PROBE_UNREACHABLE:
            raise _outage("stored credentials")

    refresh_token = settings.bambulab_cloud_refresh_token
    if refresh_token:
        logger.info("Cloud access token rejected; attempting refresh with the stored refresh token")
        try:
            _try_token_refresh(settings, refresh_token)
            result = _probe(settings)
            if result == PROBE_OK:
                logger.info("Token refresh succeeded; cloud connection restored")
                return
            if result == PROBE_UNREACHABLE:
                raise _outage("after token refresh")
            logger.warning("Refreshed tokens were also rejected by the cloud MQTT broker")
        except CloudAuthTransientError as exc:
            # Only network/server failures: the token may still be valid. Retry later;
            # no verification email is sent.
            raise RuntimeError(
                f"Cloud token refresh failed due to a network or API outage: {exc}. "
                "Credentials were not rejected; check connectivity. Retrying automatically."
            ) from exc
        except CloudAuthInvalidError:
            logger.warning("Refresh token rejected by the cloud API; re-authentication required")
    else:
        logger.warning("No refresh token available; re-authentication required")

    if _try_legacy_env_login(settings):
        result = _probe(settings)
        if result == PROBE_OK:
            logger.info("Logged in with BAMBULAB_CLOUD_CODE; cloud connection restored")
            return
        if result == PROBE_UNREACHABLE:
            raise _outage("after login")

    raise ReauthRequiredError("the Bambu Cloud token expired or was revoked")


def _try_token_refresh(settings: Settings, refresh_token: str) -> None:
    """Exchange ``refresh_token`` for new credentials, apply them to ``settings`` and persist.

    Raises:
        CloudAuthInvalidError: Token definitively rejected; caller should fall back to re-auth.
        CloudAuthTransientError: Network/API issue; caller should NOT force re-auth.
    """
    result = refresh_access_token(refresh_token)
    payload = {
        "BAMBULAB_CLOUD_USER_ID": result.user_id or settings.bambulab_cloud_user_id,
        "BAMBULAB_CLOUD_ACCESS_TOKEN": result.access_token,
        "BAMBULAB_CLOUD_REFRESH_TOKEN": result.refresh_token,
    }
    apply_credentials(settings, payload)

    secret_key = os.getenv("BAMBULAB_SECRET_KEY", settings.bambulab_secret_key)
    if secret_key:
        # The tokens already rotated; failing to persist them must not fail the refresh.
        try:
            save_encrypted_credentials(
                path=credentials_path(settings),
                secret=secret_key,
                payload={
                    **payload,
                    "BAMBULAB_CLOUD_MQTT_HOST": settings.bambulab_cloud_mqtt_host,
                    "BAMBULAB_CLOUD_MQTT_PORT": str(settings.bambulab_cloud_mqtt_port),
                },
            )
            logger.info("Refreshed cloud credentials persisted to encrypted store")
        except OSError as exc:
            logger.warning("Could not persist refreshed credentials: %s", exc.strerror or exc)
        try:
            sync_env_file(Path(".env"))
        except OSError:
            logger.warning("Skipping .env sync (not writable)")
    else:
        logger.warning(
            "BAMBULAB_SECRET_KEY not set; refreshed tokens applied to env only (not persisted to disk)"
        )


def _try_legacy_env_login(settings: Settings) -> bool:
    """Log in with BAMBULAB_CLOUD_EMAIL + BAMBULAB_CLOUD_CODE when both are set.

    When only the email is set, send one verification code for this process and return
    False. Validation re-runs (retries, page saves) never send another code, and a code that
    already failed is not retried, since codes are single-use.
    """
    email = os.getenv("BAMBULAB_CLOUD_EMAIL", "")
    code = os.getenv("BAMBULAB_CLOUD_CODE", "")
    if not email:
        return False

    if not code:
        with _legacy_lock:
            if _legacy_state["code_sent"]:
                return False
            _legacy_state["code_sent"] = True
        try:
            send_code(email)
            logger.warning(
                "A verification code was sent to the BAMBULAB_CLOUD_EMAIL inbox; enter it "
                "with bambulab-reauth (or set BAMBULAB_CLOUD_CODE and recreate the container)"
            )
        except CloudAuthError as exc:
            logger.warning("Could not send a verification code: %s", exc)
        return False

    with _legacy_lock:
        tried = _legacy_state["codes_tried"]
        assert isinstance(tried, set)
        if code in tried:
            return False
        tried.add(code)
    try:
        result = login_with_code(email=email, code=code)
    except CloudAuthError as exc:
        logger.warning(
            "Login with BAMBULAB_CLOUD_CODE failed (codes are single-use and expire): %s", exc
        )
        return False
    save_login_result(settings, result)
    logger.info("Cloud credentials re-authenticated and persisted")
    return True


def reset_legacy_login_state() -> None:
    """Forget sent codes and tried codes (tests, or after a successful page login)."""
    with _legacy_lock:
        _legacy_state["code_sent"] = False
        _legacy_state["codes_tried"] = set()
