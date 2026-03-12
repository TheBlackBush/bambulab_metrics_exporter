import pytest

from bambulab_metrics_exporter.config import Settings


def test_missing_required_local_mqtt_fields() -> None:
    settings = Settings(
        bambulab_transport="local_mqtt",
        bambulab_host="",
        bambulab_serial="",
        bambulab_access_code="",
    )
    with pytest.raises(ValueError):
        settings.require_transport_config()


def test_missing_required_cloud_serial() -> None:
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="",
    )
    with pytest.raises(ValueError):
        settings.require_transport_config()


def test_cloud_allows_email_reauth_when_tokens_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAMBULAB_CLOUD_EMAIL", "user@example.com")
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL123",
        bambulab_cloud_user_id="",
        bambulab_cloud_access_token="",
    )
    settings.require_transport_config()


def test_cloud_requires_tokens_or_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAMBULAB_CLOUD_EMAIL", raising=False)
    settings = Settings(
        bambulab_transport="cloud_mqtt",
        bambulab_serial="SERIAL123",
        bambulab_cloud_user_id="",
        bambulab_cloud_access_token="",
    )
    with pytest.raises(ValueError):
        settings.require_transport_config()
