from abc import ABC, abstractmethod

from bambulab_metrics_exporter.models import PrinterSnapshot


class BambuClient(ABC):
    @property
    def auth_rejected(self) -> bool:
        """True when the broker refused the credentials on the last connect attempt."""
        return False

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        ...
