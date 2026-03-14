from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from bambulab_metrics_exporter import main


def test_bootstrap_cloud_credentials_skips_when_not_cloud(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "local_mqtt")
    main._bootstrap_cloud_credentials()  # should no-op


def test_bootstrap_cloud_credentials_skips_when_has_tokens(monkeypatch) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.setenv("BAMBULAB_CLOUD_USER_ID", "uid")
    monkeypatch.setenv("BAMBULAB_CLOUD_ACCESS_TOKEN", "token")
    main._bootstrap_cloud_credentials()  # should no-op


def test_bootstrap_cloud_credentials_skips_without_secret_or_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.delenv("BAMBULAB_CLOUD_USER_ID", raising=False)
    monkeypatch.delenv("BAMBULAB_CLOUD_ACCESS_TOKEN", raising=False)

    # no secret
    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_CREDENTIALS_FILE", "cred.json")
    monkeypatch.delenv("BAMBULAB_SECRET_KEY", raising=False)
    main._bootstrap_cloud_credentials()

    # secret but file missing
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "sek")
    main._bootstrap_cloud_credentials()


def test_bootstrap_cloud_credentials_loads_and_sets_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAMBULAB_TRANSPORT", "cloud_mqtt")
    monkeypatch.delenv("BAMBULAB_CLOUD_USER_ID", raising=False)
    monkeypatch.delenv("BAMBULAB_CLOUD_ACCESS_TOKEN", raising=False)

    cred_path = tmp_path / "credentials.enc.json"
    cred_path.write_text("dummy")

    monkeypatch.setenv("BAMBULAB_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BAMBULAB_CREDENTIALS_FILE", "credentials.enc.json")
    monkeypatch.setenv("BAMBULAB_SECRET_KEY", "sek")

    payload = {
        "BAMBULAB_CLOUD_USER_ID": "uid2",
        "BAMBULAB_CLOUD_ACCESS_TOKEN": "tok2",
        "BAMBULAB_CLOUD_REFRESH_TOKEN": "ref2",
        "BAMBULAB_CLOUD_MQTT_HOST": "host2",
        "BAMBULAB_CLOUD_MQTT_PORT": "8883",
    }

    with patch("bambulab_metrics_exporter.main.load_encrypted_credentials", return_value=payload):
        main._bootstrap_cloud_credentials()

    assert os.environ.get("BAMBULAB_CLOUD_USER_ID") == "uid2"
    assert os.environ.get("BAMBULAB_CLOUD_ACCESS_TOKEN") == "tok2"
