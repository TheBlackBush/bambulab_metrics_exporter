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


def test_log_banner_frames_lines_at_level(caplog) -> None:
    import logging

    from bambulab_metrics_exporter.logging_utils import BANNER_WIDTH, log_banner

    caplog.set_level(logging.INFO)
    log_banner(logging.getLogger("test.banner"), "TITLE", ["a", "", "b"], level=logging.WARNING)
    records = [r for r in caplog.records if r.name == "test.banner"]
    assert [r.getMessage() for r in records] == ["=" * BANNER_WIDTH, "TITLE", "a", "", "b", "=" * BANNER_WIDTH]
    assert {r.levelno for r in records} == {logging.WARNING}
