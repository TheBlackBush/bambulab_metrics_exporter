from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from bambulab_metrics_exporter import cloud_auth


def test_main_send_code_flow(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code=None, send_code=True, save=False,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="", env_file=".env", timeout=1, retries=0, api_bases="https://api"
        )})(),
    )
    called = {"ok": False}
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.send_code", lambda *a, **k: called.__setitem__("ok", True))

    rc = cloud_auth.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert called["ok"] is True
    assert "Verification code sent" in out


def test_main_requires_code_when_not_send_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code=None, send_code=False, save=False,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="", env_file=".env", timeout=1, retries=0, api_bases="https://api"
        )})(),
    )
    rc = cloud_auth.main()
    err = capsys.readouterr().err
    assert rc == 2
    assert "--code is required" in err


def test_main_save_requires_secret(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code="123456", send_code=False, save=True,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="SERIAL", env_file=".env", timeout=1, retries=0, api_bases="https://api"
        )})(),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.login_with_code",
        lambda *a, **k: cloud_auth.LoginResult("acc", "ref", 3600, "uid"),
    )
    rc = cloud_auth.main()
    err = capsys.readouterr().err
    assert rc == 2
    assert "--secret-key" in err


def test_main_success_save_and_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code="123456", send_code=False, save=True,
            config_dir=str(tmp_path), credentials_file="c.json", secret_key="sec",
            serial="SERIAL", env_file=str(env_file), timeout=1, retries=0, api_bases="https://api"
        )})(),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.login_with_code",
        lambda *a, **k: cloud_auth.LoginResult("acc", "ref", 3600, "uid"),
    )
    called = {"saved": False, "synced": False}
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.save_encrypted_credentials",
        lambda *a, **k: called.__setitem__("saved", True),
    )
    monkeypatch.setattr("bambulab_metrics_exporter.cloud_auth.sync_env_file", lambda *a, **k: called.__setitem__("synced", True))

    rc = cloud_auth.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert called["saved"] is True
    assert called["synced"] is True
    assert "Cloud credentials ready" in out


def test_main_cloud_auth_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth._build_parser",
        lambda: type("P", (), {"parse_args": lambda self: Namespace(
            email="u@example.com", code="123456", send_code=False, save=False,
            config_dir="/tmp", credentials_file="c.json", secret_key="",
            serial="", env_file=".env", timeout=1, retries=0, api_bases="https://api"
        )})(),
    )
    monkeypatch.setattr(
        "bambulab_metrics_exporter.cloud_auth.login_with_code",
        lambda *a, **k: (_ for _ in ()).throw(cloud_auth.CloudAuthError("boom")),
    )
    rc = cloud_auth.main()
    err = capsys.readouterr().err
    assert rc == 1
    assert "Cloud auth failed" in err
