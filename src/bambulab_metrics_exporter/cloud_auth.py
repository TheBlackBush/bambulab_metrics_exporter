from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials
from bambulab_metrics_exporter.env_sync import sync_env_file

DEFAULT_API_BASES = [
    "https://api.bambulab.com",
    "https://api-eu.bambulab.com",
]
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RETRIES = 3

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://bambulab.com",
    "Referer": "https://bambulab.com/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass(slots=True)
class LoginResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: str


class CloudAuthError(RuntimeError):
    pass


def _post_json(
    api_base: str,
    path: str,
    payload: dict[str, object],
    timeout_seconds: int,
    retries: int,
) -> dict[str, object]:
    req = request.Request(
        f"{api_base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=DEFAULT_HEADERS,
        method="POST",
    )

    attempt = 0
    while True:
        try:
            with request.urlopen(req, timeout=timeout_seconds) as res:
                body = res.read().decode("utf-8")
                return json.loads(body) if body else {}
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            should_retry = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
            if attempt >= retries or not should_retry:
                if exc.code == 403 and "1010" in body:
                    raise CloudAuthError(
                        f"Cloud auth blocked on {api_base} (HTTP 403 code 1010). "
                        "Likely network/region/fingerprint restriction."
                    ) from exc
                raise CloudAuthError(f"{api_base} -> HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            if attempt >= retries:
                raise CloudAuthError(f"{api_base} -> Network error: {exc}") from exc

        attempt += 1
        backoff = min(2**attempt, 8) + random.uniform(0, 0.5)
        time.sleep(backoff)


def _post_json_multi_base(
    path: str,
    payload: dict[str, object],
    timeout_seconds: int,
    retries: int,
    api_bases: list[str],
) -> dict[str, object]:
    errors: list[str] = []
    for api_base in api_bases:
        try:
            return _post_json(api_base, path, payload, timeout_seconds=timeout_seconds, retries=retries)
        except CloudAuthError as exc:
            errors.append(str(exc))

    raise CloudAuthError(
        "All cloud API bases failed. Tried: " + ", ".join(api_bases) + " | errors: " + " || ".join(errors)
    )


def _get_json(
    api_base: str,
    path: str,
    timeout_seconds: int,
    retries: int,
    access_token: str,
) -> dict[str, object]:
    headers = dict(DEFAULT_HEADERS)
    headers["Authorization"] = f"Bearer {access_token}"
    req = request.Request(f"{api_base}{path}", headers=headers, method="GET")

    attempt = 0
    while True:
        try:
            with request.urlopen(req, timeout=timeout_seconds) as res:
                body = res.read().decode("utf-8")
                return json.loads(body) if body else {}
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            should_retry = exc.code in {408, 409, 425, 429, 500, 502, 503, 504}
            if attempt >= retries or not should_retry:
                raise CloudAuthError(f"{api_base} -> HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            if attempt >= retries:
                raise CloudAuthError(f"{api_base} -> Network error: {exc}") from exc

        attempt += 1
        backoff = min(2**attempt, 8) + random.uniform(0, 0.5)
        time.sleep(backoff)


def _resolve_user_id_from_profile(
    access_token: str,
    timeout_seconds: int,
    retries: int,
    api_bases: list[str],
) -> str | None:
    for api_base in api_bases:
        try:
            data = _get_json(
                api_base=api_base,
                path="/v1/user-service/my/profile",
                timeout_seconds=timeout_seconds,
                retries=retries,
                access_token=access_token,
            )
            for key in ("uid", "userId", "id"):
                value = data.get(key)
                if isinstance(value, (str, int)) and str(value):
                    return str(value)
        except CloudAuthError:
            continue
    return None


def send_code(
    email: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    api_bases: list[str] | None = None,
) -> None:
    bases = api_bases or DEFAULT_API_BASES
    _post_json_multi_base(
        "/v1/user-service/user/sendemail/code",
        {"email": email, "type": "codeLogin"},
        timeout_seconds=timeout_seconds,
        retries=retries,
        api_bases=bases,
    )


def _extract_user_id(
    data: dict[str, object],
    access_token: str,
    timeout_seconds: int,
    retries: int,
    api_bases: list[str],
) -> str:
    candidates: list[object] = [
        data.get("uid"),
        data.get("userId"),
        data.get("user_id"),
        (data.get("user") or {}).get("uid") if isinstance(data.get("user"), dict) else None,
        (data.get("user") or {}).get("id") if isinstance(data.get("user"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, (str, int)) and str(candidate):
            return str(candidate)

    # best effort: extract from JWT payload if present
    parts = access_token.split(".")
    if len(parts) >= 2:
        import base64

        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            raw = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
            import json as _json

            claims = _json.loads(raw)
            for key in ("uid", "userId", "sub"):
                value = claims.get(key)
                if isinstance(value, (str, int)) and str(value):
                    return str(value)
        except Exception:
            pass

    profile_uid = _resolve_user_id_from_profile(
        access_token=access_token,
        timeout_seconds=timeout_seconds,
        retries=retries,
        api_bases=api_bases,
    )
    if profile_uid:
        return profile_uid

    raise CloudAuthError("Missing user id in login/profile response")


def login_with_code(
    email: str,
    code: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    api_bases: list[str] | None = None,
) -> LoginResult:
    bases = api_bases or DEFAULT_API_BASES
    data = _post_json_multi_base(
        "/v1/user-service/user/login",
        {"account": email, "code": code},
        timeout_seconds=timeout_seconds,
        retries=retries,
        api_bases=bases,
    )
    if "error" in data:
        raise CloudAuthError(str(data["error"]))

    try:
        access_token = str(data["accessToken"])
        return LoginResult(
            access_token=access_token,
            refresh_token=str(data.get("refreshToken", "")),
            expires_in=int(data.get("expiresIn", 0)),
            user_id=_extract_user_id(
                data,
                access_token,
                timeout_seconds=timeout_seconds,
                retries=retries,
                api_bases=bases,
            ),
        )
    except KeyError as exc:
        raise CloudAuthError(f"Missing expected response key: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bambu Cloud auth helper")
    parser.add_argument("--email", required=True, help="Bambu account email")
    parser.add_argument("--code", help="2FA code from email")
    parser.add_argument("--send-code", action="store_true", help="Send email verification code")
    parser.add_argument("--save", action="store_true", help="Save encrypted credentials in config dir")
    parser.add_argument("--config-dir", default=os.getenv("BAMBULAB_CONFIG_DIR", "/config/bambulab-metrics-exporter"))
    parser.add_argument("--credentials-file", default=os.getenv("BAMBULAB_CREDENTIALS_FILE", "credentials.enc.json"))
    parser.add_argument("--secret-key", default=os.getenv("BAMBULAB_SECRET_KEY", ""))
    parser.add_argument("--serial", default=os.getenv("BAMBULAB_SERIAL", ""))
    parser.add_argument("--env-file", default=".env", help=".env file to update")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Retries for transient failures")
    parser.add_argument(
        "--api-bases",
        default=",".join(DEFAULT_API_BASES),
        help="Comma-separated API base URLs fallback order",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    try:
        api_bases = [x.strip() for x in args.api_bases.split(",") if x.strip()]
        if args.send_code:
            send_code(args.email, timeout_seconds=args.timeout, retries=args.retries, api_bases=api_bases)
            print("Verification code sent.")
            return 0

        if not args.code:
            print("--code is required unless --send-code is used", file=sys.stderr)
            return 2

        result = login_with_code(
            args.email,
            args.code,
            timeout_seconds=args.timeout,
            retries=args.retries,
            api_bases=api_bases,
        )

        os.environ["BAMBULAB_TRANSPORT"] = "cloud_mqtt"
        if args.serial:
            os.environ["BAMBULAB_SERIAL"] = args.serial
        os.environ["BAMBULAB_CLOUD_USER_ID"] = result.user_id
        os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] = result.access_token
        os.environ["BAMBULAB_CLOUD_REFRESH_TOKEN"] = result.refresh_token
        os.environ.setdefault("BAMBULAB_CLOUD_MQTT_HOST", "us.mqtt.bambulab.com")
        os.environ.setdefault("BAMBULAB_CLOUD_MQTT_PORT", "8883")
        os.environ["BAMBULAB_CONFIG_DIR"] = args.config_dir
        os.environ["BAMBULAB_CREDENTIALS_FILE"] = args.credentials_file
        if args.secret_key:
            os.environ["BAMBULAB_SECRET_KEY"] = args.secret_key

        if args.save:
            if not args.secret_key:
                print("--secret-key (or BAMBULAB_SECRET_KEY) is required with --save", file=sys.stderr)
                return 2
            payload = {
                "BAMBULAB_CLOUD_USER_ID": result.user_id,
                "BAMBULAB_CLOUD_ACCESS_TOKEN": result.access_token,
                "BAMBULAB_CLOUD_REFRESH_TOKEN": result.refresh_token,
                "BAMBULAB_CLOUD_MQTT_HOST": os.environ["BAMBULAB_CLOUD_MQTT_HOST"],
                "BAMBULAB_CLOUD_MQTT_PORT": os.environ["BAMBULAB_CLOUD_MQTT_PORT"],
            }
            save_encrypted_credentials(Path(args.config_dir) / args.credentials_file, args.secret_key, payload)

        sync_env_file(Path(args.env_file))

        print(f"Updated {args.env_file}")
        print("Cloud credentials ready.")
        return 0
    except CloudAuthError as exc:
        print(f"Cloud auth failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
