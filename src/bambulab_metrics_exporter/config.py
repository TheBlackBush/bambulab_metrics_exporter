import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment variables are the primary source.
    # .env loading is handled in main with a safe best-effort loader.
    model_config = SettingsConfigDict(case_sensitive=False)

    app_name: str = "bambulab-metrics-exporter"
    log_level: str = "INFO"

    bambulab_transport: str = "local_mqtt"
    bambulab_host: str = Field(default="", description="Printer IP / hostname for LAN MQTT")
    bambulab_port: int = 8883
    bambulab_serial: str = Field(default="", description="Printer device serial/id used in MQTT topic")
    bambulab_access_code: str = Field(default="", description="LAN access code (password)")
    bambulab_username: str = "bblp"
    bambulab_request_pushall: bool = True

    bambulab_cloud_mqtt_host: str = "us.mqtt.bambulab.com"
    bambulab_cloud_mqtt_port: int = 8883
    bambulab_cloud_user_id: str = ""
    bambulab_cloud_access_token: str = ""
    bambulab_cloud_refresh_token: str = ""

    bambulab_config_dir: str = "/config/bambulab-metrics-exporter"
    bambulab_credentials_file: str = "credentials.enc.json"
    bambulab_secret_key: str = ""

    polling_interval_seconds: float = 10.0
    request_timeout_seconds: float = 8.0
    reconnect_interval_seconds: float = 5.0

    listen_host: str = "0.0.0.0"
    listen_port: int = 9109

    printer_name: str = "bambulab"
    site: str = ""
    location: str = ""

    @field_validator("polling_interval_seconds")
    @classmethod
    def validate_polling(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("polling_interval_seconds must be > 0")
        return value

    @field_validator("request_timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("request_timeout_seconds must be > 0")
        return value

    @field_validator("bambulab_transport")
    @classmethod
    def validate_transport(cls, value: str) -> str:
        supported = {"local_mqtt", "cloud_mqtt"}
        if value not in supported:
            raise ValueError(f"Unsupported transport '{value}', supported: {sorted(supported)}")
        return value

    def require_transport_config(self) -> None:
        if self.bambulab_transport == "local_mqtt":
            missing = [
                key
                for key, raw in {
                    "BAMBULAB_HOST": self.bambulab_host,
                    "BAMBULAB_SERIAL": self.bambulab_serial,
                    "BAMBULAB_ACCESS_CODE": self.bambulab_access_code,
                }.items()
                if not raw
            ]
            if missing:
                raise ValueError(f"Missing required env vars for local_mqtt: {', '.join(missing)}")

        if self.bambulab_transport == "cloud_mqtt":
            if not self.bambulab_serial:
                raise ValueError("Missing required env vars for cloud_mqtt: BAMBULAB_SERIAL")

            has_token_pair = bool(self.bambulab_cloud_user_id and self.bambulab_cloud_access_token)
            has_email_for_reauth = bool(os.getenv("BAMBULAB_CLOUD_EMAIL"))

            if not has_token_pair and not has_email_for_reauth:
                raise ValueError(
                    "Missing cloud auth inputs: provide either "
                    "(BAMBULAB_CLOUD_USER_ID + BAMBULAB_CLOUD_ACCESS_TOKEN) "
                    "or BAMBULAB_CLOUD_EMAIL for startup re-auth flow"
                )
