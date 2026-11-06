from __future__ import annotations

import logging

from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.printers import mask_serial

logger = logging.getLogger(__name__)


class CloudMqttBambuClient(LocalMqttBambuClient):
    """Cloud MQTT transport.

    Reuses the same topic/payload logic as local MQTT, but authenticates against
    Bambu cloud broker using user id + access token.
    """

    def __init__(self, settings: Settings) -> None:
        cloud_settings = settings.model_copy(deep=True)
        cloud_settings.bambulab_host = settings.bambulab_cloud_mqtt_host
        cloud_settings.bambulab_port = settings.bambulab_cloud_mqtt_port
        cloud_settings.bambulab_username = f"u_{settings.bambulab_cloud_user_id}"
        cloud_settings.bambulab_access_code = settings.bambulab_cloud_access_token
        super().__init__(cloud_settings)
        logger.info(
            "Cloud MQTT client initialized",
            extra={
                "mqtt_host": settings.bambulab_cloud_mqtt_host,
                "serial": mask_serial(settings.bambulab_serial),
            },
        )
