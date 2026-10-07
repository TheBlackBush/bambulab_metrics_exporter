"""Tests for bambulab_metrics_exporter.reauth."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from bambulab_metrics_exporter import reauth
from bambulab_metrics_exporter.cloud_auth import CloudAuthError, LoginResult
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials

SECRET = "fake-development-key-never-use"


def _settings(tmp_path: Path, **overrides) -> Settings:
    values: dict = dict(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="FAKE00TEST000001",
        bambulab_cloud_user_id="u",
        bambulab_cloud_access_token="stale_token",
        bambulab_cloud_refresh_token="stale_refresh",
        bambulab_config_dir=str(tmp_path),
        bambulab_credentials_file="credentials.enc.json",
    )
    values.update(overrides)
    return Settings(**values)


def _store(tmp_path: Path, payload: dict, secret: str = SECRET) -> Path:
    path = tmp_path / "credentials.enc.json"
    save_encrypted_credentials(path, secret, payload)
    return path


_GOOD = {
    "BAMBULAB_CLOUD_USER_ID": "u",
    "BAMBULAB_CLOUD_ACCESS_TOKEN": "fresh_token",
    "BAMBULAB_CLOUD_REFRESH_TOKEN": "fresh_refresh",
    "BAMBULAB_CLOUD_MQTT_HOST": "us.mqtt.bambulab.com",
    "BAMBULAB_CLOUD_MQTT_PORT": "8883",
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in (*reauth.CREDENTIAL_KEYS, "BAMBULAB_SECRET_KEY", "BAMBULAB_CLOUD_EMAIL"):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# load_stored_credentials / apply_credentials
# ---------------------------------------------------------------------------

def test_load_stored_credentials_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _store(tmp_path, {**_GOOD, "UNRELATED": "ignored"})
    assert reauth.load_stored_credentials(_settings(tmp_path)) == _GOOD


@pytest.mark.parametrize(
    "case",
    ["no_secret", "no_file", "wrong_secret", "incomplete"],
)
def test_load_stored_credentials_unusable_returns_none(tmp_path: Path, monkeypatch, case) -> None:
    if case != "no_secret":
        monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    if case in ("no_secret", "incomplete"):
        _store(tmp_path, {"BAMBULAB_CLOUD_USER_ID": "u"} if case == "incomplete" else _GOOD)
    if case == "wrong_secret":
        _store(tmp_path, _GOOD, secret="another-fake-key")
    assert reauth.load_stored_credentials(_settings(tmp_path)) is None


def test_load_stored_credentials_logs_without_secrets(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _store(tmp_path, _GOOD, secret="another-fake-key")
    reauth.load_stored_credentials(_settings(tmp_path))
    assert "could not be read" in caplog.text
    assert SECRET not in caplog.text and "fresh_token" not in caplog.text


def test_apply_credentials_updates_env_and_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    reauth.apply_credentials(settings, {**_GOOD, "BAMBULAB_CLOUD_MQTT_PORT": "1883"})
    assert os.environ["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"
    assert settings.bambulab_cloud_access_token == "fresh_token"
    assert settings.bambulab_cloud_refresh_token == "fresh_refresh"
    assert settings.bambulab_cloud_mqtt_port == 1883


def test_differs_from_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert reauth.differs_from_settings(settings, _GOOD) is True
    same = {"BAMBULAB_CLOUD_USER_ID": "u", "BAMBULAB_CLOUD_ACCESS_TOKEN": "stale_token"}
    assert reauth.differs_from_settings(settings, same) is False


# ---------------------------------------------------------------------------
# save_login_result
# ---------------------------------------------------------------------------

def _login() -> LoginResult:
    return LoginResult(access_token="fresh_token", refresh_token="fresh_refresh", expires_in=1, user_id="u")


def test_save_login_result_persists_and_applies(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    settings = _settings(tmp_path)
    reauth.save_login_result(settings, _login())

    assert reauth.load_stored_credentials(settings)["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"
    assert settings.bambulab_cloud_access_token == "fresh_token"
    assert (tmp_path / "credentials.enc.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / ".env").exists()


def test_save_login_result_requires_secret(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BAMBULAB_SECRET_KEY"):
        reauth.save_login_result(_settings(tmp_path), _login())


def test_save_login_result_hands_files_to_runtime_user(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("PUID", "1234")
    monkeypatch.setenv("PGID", "5678")
    monkeypatch.setattr(reauth.os, "geteuid", lambda: 0)
    chowned: list[tuple[str, int, int]] = []
    monkeypatch.setattr(reauth.os, "chown", lambda p, u, g: chowned.append((Path(p).name, u, g)))

    reauth.save_login_result(_settings(tmp_path), _login())

    assert ("credentials.enc.json", 1234, 5678) in chowned
    assert (".env", 1234, 5678) in chowned


def test_hand_over_skipped_when_not_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(reauth.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(reauth.os, "chown", lambda *a: pytest.fail("must not chown as non-root"))
    path = tmp_path / "f"
    path.write_text("x")
    reauth._hand_over_to_runtime_user(path)


# ---------------------------------------------------------------------------
# log_reauth_banner
# ---------------------------------------------------------------------------

def test_banner_points_to_page_and_command(caplog) -> None:
    reauth.log_reauth_banner("token expired", port=9110)
    assert "RE-AUTHENTICATION REQUIRED" in caplog.text
    assert "http://<docker-host>:9110/auth" in caplog.text
    assert "9110 is the container port" in caplog.text
    assert "docker exec -it <container> bambulab-reauth" in caplog.text


# ---------------------------------------------------------------------------
# bambulab-reauth command
# ---------------------------------------------------------------------------

class _Tty:
    def isatty(self) -> bool:
        return True


def _interactive(monkeypatch, inputs: list[str], secrets: list[str]) -> None:
    monkeypatch.setattr(reauth.sys, "stdin", _Tty())
    answers = iter(inputs)
    codes = iter(secrets)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(reauth.getpass, "getpass", lambda prompt="": next(codes))


def test_main_requires_tty(monkeypatch, capsys) -> None:
    class _NoTty:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(reauth.sys, "stdin", _NoTty())
    assert reauth.main() == 2
    assert "docker exec -it" in capsys.readouterr().err


def test_main_requires_secret_key(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(reauth.sys, "stdin", _Tty())
    assert reauth.main() == 2
    assert "BAMBULAB_SECRET_KEY" in capsys.readouterr().err


def test_main_sends_code_logs_in_and_saves(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_SERIAL", "FAKE00TEST000001")
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "operator@example.invalid")
    _interactive(monkeypatch, inputs=[""], secrets=["", "000000"])  # default email, new code
    sent: list[str] = []
    monkeypatch.setattr(reauth, "send_code", sent.append)
    monkeypatch.setattr(reauth, "login_with_code", lambda email, code: _login())

    assert reauth.main() == 0
    assert sent == ["operator@example.invalid"]
    stored = reauth.load_stored_credentials(Settings())
    assert stored is not None and stored["BAMBULAB_CLOUD_ACCESS_TOKEN"] == "fresh_token"


def test_main_existing_code_skips_send(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    _interactive(monkeypatch, inputs=["operator@example.invalid"], secrets=["000000"])
    monkeypatch.setattr(reauth, "send_code", lambda e: pytest.fail("code already entered"))
    monkeypatch.setattr(reauth, "login_with_code", lambda email, code: _login())
    assert reauth.main() == 0


def test_main_login_failure_returns_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _interactive(monkeypatch, inputs=["operator@example.invalid"], secrets=["000000"])

    def reject(email: str, code: str):
        raise CloudAuthError("code expired")

    monkeypatch.setattr(reauth, "login_with_code", reject)
    assert reauth.main() == 1
    assert "Authentication failed" in capsys.readouterr().err


def test_main_missing_email_or_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _interactive(monkeypatch, inputs=[""], secrets=[])
    assert reauth.main() == 2

    _interactive(monkeypatch, inputs=["operator@example.invalid"], secrets=["", ""])
    monkeypatch.setattr(reauth, "send_code", lambda e: None)
    assert reauth.main() == 2
