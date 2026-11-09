"""Tests for the saved printer list and per-printer settings."""
from __future__ import annotations

import logging
import stat
from dataclasses import asdict
from pathlib import Path

import pytest

from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials
from bambulab_metrics_exporter.printers import (
    PrinterConfig,
    PrinterStore,
    mask_serial,
    printer_id_for,
    printer_settings,
)
from bambulab_metrics_exporter.security import encrypt_json

SECRET = "fake-development-key-never-use"
LAN = PrinterConfig(
    serial="FAKE00TEST000001", transport="local_mqtt", host="192.0.2.25",
    access_code="fake-access-code", name="Test LAN",
)
CLOUD = PrinterConfig(serial="FAKE00TEST000002", transport="cloud_mqtt", name="Test Cloud", model="H2D")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)
    monkeypatch.delenv("PRINTER_NAME_LABEL", raising=False)


def test_printer_id_is_stable_and_hides_serial() -> None:
    assert printer_id_for("FAKE00TEST000001") == LAN.printer_id
    assert len(LAN.printer_id) == 12
    assert "FAKE" not in LAN.printer_id
    assert LAN.printer_id != CLOUD.printer_id


def test_label_falls_back_to_masked_serial() -> None:
    assert LAN.label == "Test LAN"
    assert PrinterConfig(serial="FAKE00TEST000001", transport="cloud_mqtt").label == mask_serial(
        "FAKE00TEST000001"
    )


def test_store_absent_is_none() -> None:
    assert PrinterStore().load() is None


def test_store_roundtrip_is_encrypted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    assert PrinterStore().save([LAN, CLOUD]) is True
    assert PrinterStore().load() == [LAN, CLOUD]
    blob = (tmp_path / "printers.enc.json").read_bytes()
    assert b"fake-access-code" not in blob
    assert (tmp_path / "printers.enc.json").stat().st_mode & 0o777 == 0o600


def test_store_without_key_lives_in_memory(tmp_path: Path) -> None:
    store = PrinterStore()
    assert store.save([LAN]) is False
    assert store.load() == [LAN]
    assert not (tmp_path / "printers.enc.json").exists()
    assert PrinterStore().load() is None


def test_store_empty_list_is_not_none(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    PrinterStore().save([])
    assert PrinterStore().load() == []


def test_store_clear(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    store = PrinterStore()
    store.save([LAN])
    store.clear()
    assert store.load() is None
    assert not (tmp_path / "printers.enc.json").exists()


def test_store_wrong_key_means_no_store(monkeypatch, caplog) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    PrinterStore().save([LAN])
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "another-fake-key")
    assert PrinterStore().load() is None
    assert "could not be read" in caplog.text
    assert "fake-access-code" not in caplog.text


def test_store_skips_malformed_records(monkeypatch, tmp_path: Path) -> None:
    from bambulab_metrics_exporter.credentials_store import save_encrypted_credentials

    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    save_encrypted_credentials(
        tmp_path / "printers.enc.json", SECRET,
        {"printers": [
            {"serial": "FAKE00TEST000001", "transport": "local_mqtt", "port": 8883},
            {"serial": "", "transport": "local_mqtt"},
            {"serial": "FAKE00TEST000003", "transport": "carrier_pigeon"},
            {"serial": "FAKE00TEST000004", "transport": "local_mqtt", "port": "bad"},
            "garbage",
        ]},
    )
    assert [p.serial for p in PrinterStore().load() or []] == ["FAKE00TEST000001"]


def test_settings_overlay_local(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_SERIAL", "ENVSERIAL0000000")
    monkeypatch.setenv("BAMBULAB_HOST", "192.0.2.99")
    settings = printer_settings(LAN)
    assert settings.bambulab_transport == "local_mqtt"
    assert settings.bambulab_serial == LAN.serial
    assert settings.bambulab_host == "192.0.2.25"
    assert settings.bambulab_access_code == "fake-access-code"
    assert settings.bambulab_printer_name == "Test LAN"


def test_settings_overlay_cloud_keeps_shared_tokens(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "fake-access-token")
    settings = printer_settings(CLOUD)
    assert settings.bambulab_transport == "cloud_mqtt"
    assert settings.bambulab_cloud_access_token == "fake-access-token"
    assert settings.bambulab_printer_model == "H2D"


def test_saved_env_printer_keeps_its_series_identity(monkeypatch) -> None:
    from bambulab_metrics_exporter.runtime import printer_label

    monkeypatch.setenv("BAMBULAB_SERIAL", LAN.serial)
    monkeypatch.delenv("BAMBULAB_PRINTER_NAME", raising=False)
    before = printer_label(Settings())
    assert before == "bambulab"
    saved = PrinterConfig(serial=LAN.serial, transport="local_mqtt", env_printer=True)
    assert printer_label(printer_settings(saved)) == before


def test_name_label_only_for_env_printer(monkeypatch) -> None:
    monkeypatch.setenv("PRINTER_NAME_LABEL", "operator-label")
    assert printer_settings(LAN).printer_name_label == ""
    env_printer = PrinterConfig(serial=LAN.serial, transport="local_mqtt", env_printer=True)
    assert printer_settings(env_printer).printer_name_label == "operator-label"


# ---------------------------------------------------------------------------
# unreadable saved list
# ---------------------------------------------------------------------------

def _store_path(tmp_path: Path) -> Path:
    return tmp_path / "printers.enc.json"


def _wrong_key(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_encrypted_credentials(path, "fake-other-key", {"printers": [asdict(LAN)]})


def _truncated(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_encrypted_credentials(path, SECRET, {"printers": [asdict(LAN)]})
    path.write_bytes(path.read_bytes()[:20])


def _bad_json(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path.write_bytes(encrypt_json(SECRET, "{not json"))


def _not_a_list(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_encrypted_credentials(path, SECRET, {"printers": {"serial": "FAKE00TEST000001"}})


def _no_printers_key(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_encrypted_credentials(path, SECRET, {"other": 1})


def _nothing_parses(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_encrypted_credentials(path, SECRET, {"printers": [{"serial": ""}, "junk"]})


def _no_key(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_encrypted_credentials(path, SECRET, {"printers": [asdict(LAN)]})
    monkeypatch.delenv("BAMBULAB_SECRET_KEY")


_UNREADABLE = [
    _wrong_key, _truncated, _bad_json, _not_a_list, _no_printers_key, _nothing_parses, _no_key,
]


@pytest.mark.parametrize("damage", _UNREADABLE)
def test_unreadable_list_falls_back_and_warns_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, damage
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    damage(_store_path(tmp_path), monkeypatch)
    store = PrinterStore()
    with caplog.at_level(logging.WARNING):
        assert store.load() is None
        assert store.load() is None
    assert store.unreadable is True
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "printers.enc.json" in warnings[0] and "BAMBULAB_SECRET_KEY" in warnings[0]


def test_unreadable_warning_names_the_class_never_the_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _store_path(tmp_path).write_bytes(b"x")

    def boom(_path: Path, _secret: str) -> dict:
        raise KeyError("fake-sensitive-detail")

    monkeypatch.setattr("bambulab_metrics_exporter.printers.load_encrypted_credentials", boom)
    with caplog.at_level(logging.WARNING):
        assert PrinterStore().load() is None
    assert "KeyError" in caplog.text and "fake-sensitive-detail" not in caplog.text


def test_absent_file_is_not_unreadable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    store = PrinterStore()
    with caplog.at_level(logging.WARNING):
        assert store.load() is None
    assert store.unreadable is False and caplog.text == ""


def test_saved_empty_list_is_not_unreadable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    store = PrinterStore()
    store.save([])
    with caplog.at_level(logging.WARNING):
        assert store.load() == []
    assert store.unreadable is False and caplog.text == ""


def test_store_is_unreadable_only_after_a_failed_load_and_recovers_on_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _wrong_key(_store_path(tmp_path), monkeypatch)
    store = PrinterStore()
    assert store.load() is None and store.unreadable is True
    store.save([LAN])
    assert store.unreadable is False and store.load() == [LAN]


@pytest.mark.parametrize("damage", [d for d in _UNREADABLE if d is not _no_key])
def test_first_save_over_an_unreadable_file_keeps_a_private_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    path = _store_path(tmp_path)
    damage(path, monkeypatch)
    original = path.read_bytes()
    store = PrinterStore()
    store.save([LAN])
    bad = tmp_path / "printers.enc.json.bad"
    assert bad.read_bytes() == original
    assert stat.S_IMODE(bad.stat().st_mode) == 0o600

    store.save([CLOUD])  # The file is readable now: the copy stays as it was.
    assert bad.read_bytes() == original
    assert store.load() == [CLOUD]


def test_save_over_a_readable_file_keeps_no_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    store = PrinterStore()
    store.save([LAN])
    store.save([CLOUD])
    assert not (tmp_path / "printers.enc.json.bad").exists()


def test_save_is_refused_when_the_copy_cannot_be_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    path = _store_path(tmp_path)
    _wrong_key(path, monkeypatch)
    original = path.read_bytes()
    (tmp_path / "printers.enc.json.bad").mkdir()  # os.replace onto a directory fails

    with pytest.raises(OSError):
        PrinterStore().save([LAN])
    assert path.read_bytes() == original


def test_session_save_without_a_key_leaves_the_unreadable_file_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _store_path(tmp_path)
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    _no_key(path, monkeypatch)
    original = path.read_bytes()
    store = PrinterStore()
    assert store.load() is None
    assert store.save([CLOUD]) is False
    assert store.load() == [CLOUD]
    assert path.read_bytes() == original
    assert store.unreadable is True
    assert not (tmp_path / "printers.enc.json.bad").exists()


def test_clear_keeps_a_copy_of_an_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    path = _store_path(tmp_path)
    _wrong_key(path, monkeypatch)
    original = path.read_bytes()
    store = PrinterStore()
    store.clear()
    assert not path.exists() and store.unreadable is False
    assert (tmp_path / "printers.enc.json.bad").read_bytes() == original


def test_ignored_entries_are_counted_once_without_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", SECRET)
    bad = {"serial": "FAKE00TEST000009", "transport": "carrier_pigeon"}
    save_encrypted_credentials(
        _store_path(tmp_path), SECRET, {"printers": [asdict(LAN), bad, "junk"]}
    )
    store = PrinterStore()
    with caplog.at_level(logging.WARNING):
        assert store.load() == [LAN]
        assert store.load() == [LAN]
    assert store.unreadable is False
    assert caplog.messages == ["2 of 3 saved printers were ignored"]
