from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "bambulab-prometheus-exporter"
    log_level: str = "INFO"

    bambulab_transport: str = "local_mqtt"
    bambulab_host: str = Field(default="", description="Printer IP / hostname for LAN MQTT")
    bambulab_port: int = 8883
    bambulab_serial: str = Field(default="", description="Printer device serial/id used in MQTT topic")
    bambulab_access_code: str = Field(default="", description="LAN access code (password)")
    bambulab_username: str = "bblp"
    bambulab_request_pushall: bool = True

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
        supported = {"local_mqtt"}
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
