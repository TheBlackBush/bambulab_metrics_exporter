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

API_BASE = "https://api.bambulab.com"
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


def _post_json(path: str, payload: dict[str, object], timeout_seconds: int, retries: int) -> dict[str, object]:
    req = request.Request(
        f"{API_BASE}{path}",
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
                        "Cloud auth blocked (HTTP 403 code 1010). "
                        "Likely network/region/fingerprint restriction. "
                        "Try running bambulab-cloud-auth from your home host network."
                    ) from exc
                raise CloudAuthError(f"HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            if attempt >= retries:
                raise CloudAuthError(f"Network error: {exc}") from exc

        attempt += 1
        backoff = min(2**attempt, 8) + random.uniform(0, 0.5)
        time.sleep(backoff)


def send_code(email: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, retries: int = DEFAULT_RETRIES) -> None:
    _post_json(
        "/v1/user-service/user/sendemail/code",
        {"email": email, "type": "codeLogin"},
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def login_with_code(
    email: str,
    code: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> LoginResult:
    data = _post_json(
        "/v1/user-service/user/login",
        {"account": email, "code": code},
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    if "error" in data:
        raise CloudAuthError(str(data["error"]))

    try:
        return LoginResult(
            access_token=str(data["accessToken"]),
            refresh_token=str(data.get("refreshToken", "")),
            expires_in=int(data.get("expiresIn", 0)),
            user_id=str(data["uid"]),
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
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    try:
        if args.send_code:
            send_code(args.email, timeout_seconds=args.timeout, retries=args.retries)
            print("Verification code sent.")
            return 0

        if not args.code:
            print("--code is required unless --send-code is used", file=sys.stderr)
            return 2

        result = login_with_code(args.email, args.code, timeout_seconds=args.timeout, retries=args.retries)

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
