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
