from abc import ABC, abstractmethod

from bambulab_prometheus_exporter.models import PrinterSnapshot


class BambuClient(ABC):
    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def fetch_snapshot(self, timeout_seconds: float) -> PrinterSnapshot:
        ...
