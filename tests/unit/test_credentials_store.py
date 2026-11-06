import os
import stat
from pathlib import Path

import pytest

from bambulab_metrics_exporter.credentials_store import (
    load_encrypted_credentials,
    save_encrypted_credentials,
)


def test_encrypted_credentials_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "credentials.enc.json"
    secret = "super-secret"
    payload = {"BAMBULAB_CLOUD_USER_ID": "123", "BAMBULAB_CLOUD_ACCESS_TOKEN": "abc"}

    save_encrypted_credentials(path, secret, payload)
    out = load_encrypted_credentials(path, secret)

    assert out == payload


def test_save_replaces_the_file_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "credentials.enc.json"
    path.write_bytes(b"old")
    path.chmod(0o644)

    save_encrypted_credentials(path, "super-secret", {"key": "value"})

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_encrypted_credentials(path, "super-secret") == {"key": "value"}


def test_new_file_is_0600_with_a_loose_umask(tmp_path: Path) -> None:
    path = tmp_path / "credentials.enc.json"
    previous = os.umask(0)
    try:
        save_encrypted_credentials(path, "super-secret", {"key": "value"})
    finally:
        os.umask(previous)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("step", ["fsync", "replace"])
def test_failed_save_keeps_the_old_file_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    path = tmp_path / "credentials.enc.json"
    save_encrypted_credentials(path, "super-secret", {"key": "old"})

    def fail(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, step, fail)
    with pytest.raises(OSError, match="disk full"):
        save_encrypted_credentials(path, "super-secret", {"key": "new"})
    monkeypatch.undo()

    assert load_encrypted_credentials(path, "super-secret") == {"key": "old"}
    assert [item.name for item in tmp_path.iterdir()] == [path.name]


def test_save_syncs_before_it_replaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        calls.append("fsync")
        real_fsync(fd)

    def replace(src: str, dst: Path) -> None:
        calls.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    save_encrypted_credentials(tmp_path / "credentials.enc.json", "super-secret", {"k": "v"})
    assert calls == ["fsync", "replace"]
