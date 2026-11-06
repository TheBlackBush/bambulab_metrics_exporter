"""Tests for the saved printer list and per-printer settings."""
from __future__ import annotations

from pathlib import Path

import pytest

from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.printers import (
    PrinterConfig,
    PrinterStore,
    mask_serial,
    printer_id_for,
    printer_settings,
)

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
