from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.client.local_mqtt import LocalMqttBambuClient
from bambulab_metrics_exporter.config import Settings


def build_client(settings: Settings) -> BambuClient:
    if settings.bambulab_transport == "local_mqtt":
        return LocalMqttBambuClient(settings)
    raise ValueError(f"Unsupported transport: {settings.bambulab_transport}")
