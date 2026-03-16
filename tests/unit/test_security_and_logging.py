from __future__ import annotations

import logging
from pathlib import Path

from bambulab_metrics_exporter.logging_utils import configure_logging
from bambulab_metrics_exporter.security import decrypt_json, encrypt_json, ensure_parent


def test_encrypt_decrypt_roundtrip() -> None:
    secret = "secret-key"
    payload = '{"ok":true}'
    blob = encrypt_json(secret, payload)
    assert decrypt_json(secret, blob) == payload


def test_ensure_parent_ignores_chmod_oserror(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "file.txt"

    def _raise(_self, _: int) -> None:
        raise OSError("chmod blocked")

    monkeypatch.setattr(Path, "chmod", _raise)
    ensure_parent(target)
    assert target.parent.exists()


def test_configure_logging_unknown_level_defaults_to_info(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)
    configure_logging("not-a-real-level")

    assert captured["level"] == logging.INFO
    assert "%(asctime)s" in str(captured["format"])
