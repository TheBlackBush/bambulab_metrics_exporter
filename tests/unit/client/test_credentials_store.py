from pathlib import Path

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
