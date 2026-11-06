"""Runs one ExporterRuntime per printer and merges their metrics.

Each printer keeps its own thread, retries, client and private registry, so a failing printer
cannot affect the others and stale-series clearing stays per printer.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator

from prometheus_client import CollectorRegistry
from prometheus_client.metrics_core import Metric

from bambulab_metrics_exporter.client.base import BambuClient
from bambulab_metrics_exporter.client.factory import build_client
from bambulab_metrics_exporter.config import Settings
from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.printers import (
    TRANSPORT_CLOUD,
    PrinterConfig,
    PrinterStore,
    mask_serial,
    printer_settings,
)
from bambulab_metrics_exporter.runtime import (
    STATE_AUTH_REQUIRED,
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_RUNNING,
    STATE_SETUP_REQUIRED,
    STATE_STARTING,
    ExporterRuntime,
)
from bambulab_metrics_exporter.startup import startup_validate

logger = logging.getLogger(__name__)

ENV_RUNTIME_ID = "env"
# Worst first: the summary state for the status page.
_STATE_ORDER = (
    STATE_ERROR,
    STATE_AUTH_REQUIRED,
    STATE_SETUP_REQUIRED,
    STATE_CONNECTING,
    STATE_STARTING,
    STATE_RUNNING,
)


class MergedCollector:
    """Joins families with the same name so HELP and TYPE appear once per metric."""

    def __init__(self, registries: Callable[[], list[CollectorRegistry]]) -> None:
        self._registries = registries

    def collect(self) -> Iterator[Metric]:
        merged: dict[str, Metric] = {}
        for registry in self._registries():
            try:
                families = list(registry.collect())
            except Exception:  # noqa: BLE001 - one printer must not break the scrape
                logger.exception("Collecting one printer's metrics failed; skipping it")
                continue
            for family in families:
                target = merged.get(family.name)
                if target is None:
                    target = Metric(family.name, family.documentation, family.type, family.unit)
                    merged[family.name] = target
                target.samples.extend(family.samples)
        return iter(merged.values())


class PrinterFleet:
    """Offers the runtime surface api.py uses, plus printer list management."""

    def __init__(
        self,
        store: PrinterStore,
        settings_factory: Callable[[], Settings] = Settings,
        validate: Callable[[Settings], None] = startup_validate,
        client_factory: Callable[[Settings], BambuClient] = build_client,
    ) -> None:
        self._store = store
        self._settings_factory = settings_factory
        self._validate_fn = validate
        self._client_factory = client_factory
        self._lock = threading.RLock()
        self._cloud_lock = threading.Lock()
        self._runtimes: dict[str, ExporterRuntime] = {}
        self._configs: dict[str, PrinterConfig] = {}
        self._retiring: list[threading.Thread] = []
        self._started = False
        self._idle_metrics = ExporterMetrics(printer_name="", serial="")
        self._registry = CollectorRegistry(auto_describe=False)
        self._registry.register(MergedCollector(self._registries))
        saved = store.load()
        if saved is None:
            self._runtimes[ENV_RUNTIME_ID] = self._env_runtime()
        else:
            for config in saved:
                self._add(config)

    # -- building runtimes ------------------------------------------------

    def _validate(self, settings: Settings) -> None:
        """Cloud printers share one account: one validation at a time, each starting from
        the newest tokens, so a refresh by one printer is reused by the rest."""
        if settings.bambulab_transport != TRANSPORT_CLOUD:
            self._validate_fn(settings)
            return
        with self._cloud_lock:
            current = self._settings_factory()
            settings.bambulab_cloud_user_id = current.bambulab_cloud_user_id
            settings.bambulab_cloud_access_token = current.bambulab_cloud_access_token
            settings.bambulab_cloud_refresh_token = current.bambulab_cloud_refresh_token
            self._validate_fn(settings)

    def _env_runtime(self) -> ExporterRuntime:
        return ExporterRuntime(
            settings_factory=self._settings_factory,
            validate=self._validate,
            client_factory=self._client_factory,
        )

    def _add(self, config: PrinterConfig) -> ExporterRuntime:
        runtime = ExporterRuntime(
            settings_factory=lambda: printer_settings(config, self._settings_factory),
            validate=self._validate,
            client_factory=self._client_factory,
            discover=lambda _settings: None,  # name and model are saved with the printer
            sync_env=False,
        )
        self._runtimes[config.printer_id] = runtime
        self._configs[config.printer_id] = config
        return runtime

    def _snapshot(self) -> list[ExporterRuntime]:
        with self._lock:
            return list(self._runtimes.values())

    def _registries(self) -> list[CollectorRegistry]:
        return [runtime.metrics.registry for runtime in self._snapshot()]

    # -- runtime surface --------------------------------------------------

    @property
    def scrape_registry(self) -> CollectorRegistry:
        return self._registry

    @property
    def settings(self) -> Settings:
        runtimes = self._snapshot()
        return runtimes[0].settings if runtimes else Settings.model_construct()

    @property
    def metrics(self) -> ExporterMetrics:
        runtimes = self._snapshot()
        return runtimes[0].metrics if runtimes else self._idle_metrics

    @property
    def ready(self) -> bool:
        return any([runtime.ready for runtime in self._snapshot()])

    @property
    def saved(self) -> bool:
        return self._store.load() is not None

    def start(self) -> None:
        with self._lock:
            self._started = True
            runtimes = list(self._runtimes.values())
        for runtime in runtimes:
            runtime.start()

    def stop(self) -> None:
        with self._lock:
            self._started = False
            runtimes = list(self._runtimes.values())
            retiring, self._retiring = self._retiring, []
        for thread in retiring:
            thread.join(timeout=12)
        for runtime in runtimes:
            runtime.stop()

    def reconfigure(self) -> None:
        for runtime in self._snapshot():
            runtime.reconfigure()

    def status(self) -> dict[str, str]:
        statuses = [runtime.status() for runtime in self._snapshot()]
        if not statuses:
            return {
                "state": STATE_SETUP_REQUIRED,
                "message": "No printers selected.",
                "transport": "",
            }
        if len(statuses) == 1:
            return statuses[0]
        rank = {state: index for index, state in enumerate(_STATE_ORDER)}
        worst = min(statuses, key=lambda s: rank.get(s["state"], 0))
        transports = {s["transport"] for s in statuses}
        return {
            "state": worst["state"],
            "message": worst["message"],
            "transport": transports.pop() if len(transports) == 1 else "mixed",
        }

    # -- printer list -----------------------------------------------------

    def configs(self) -> list[PrinterConfig]:
        """The current list. In env mode, the env printer when one is configured."""
        with self._lock:
            if ENV_RUNTIME_ID not in self._runtimes:
                return list(self._configs.values())
            settings = self._runtimes[ENV_RUNTIME_ID].settings
        if not settings.bambulab_serial:
            return []
        return [
            PrinterConfig(
                serial=settings.bambulab_serial,
                transport=settings.bambulab_transport,
                host=settings.bambulab_host,
                port=settings.bambulab_port,
                access_code=settings.bambulab_access_code,
                name=settings.bambulab_printer_name,
                model=settings.bambulab_printer_model,
                env_printer=True,
            )
        ]

    def printers_status(self) -> list[dict[str, str]]:
        with self._lock:
            items = list(self._runtimes.items())
            configs = dict(self._configs)
        out: list[dict[str, str]] = []
        for printer_id, runtime in items:
            status = runtime.status()
            config = configs.get(printer_id)
            settings = runtime.settings
            if config is None and not settings.bambulab_serial:
                continue
            serial = config.serial if config else str(settings.bambulab_serial)
            out.append({
                "id": printer_id,
                "name": config.label if config else (
                    settings.printer_name_label
                    or settings.bambulab_printer_name
                    or mask_serial(serial)
                ),
                "serial": mask_serial(serial),
                "transport": config.transport if config else str(settings.bambulab_transport),
                "state": status["state"],
                "message": status["message"],
            })
        return out

    def _retire(self, runtime: ExporterRuntime) -> None:
        """Stop in the background: a stop can take seconds and this runs during a request."""
        thread = threading.Thread(target=runtime.stop, name="runtime-retire", daemon=True)
        self._retiring = [t for t in self._retiring if t.is_alive()] + [thread]
        thread.start()

    def update(self, configs: list[PrinterConfig]) -> bool:
        """Save the list and apply it. Unchanged printers stay connected. True when saved."""
        persisted = self._store.save(configs)
        wanted = {config.printer_id: config for config in configs}
        started: list[ExporterRuntime] = []
        with self._lock:
            for printer_id in list(self._runtimes):
                if self._configs.get(printer_id) != wanted.get(printer_id):
                    self._retire(self._runtimes.pop(printer_id))
                    self._configs.pop(printer_id, None)
            for printer_id, config in wanted.items():
                if printer_id not in self._runtimes:
                    started.append(self._add(config))
            running = self._started
        if running:
            for runtime in started:
                runtime.start()
        return persisted

    def reset_to_env(self) -> None:
        self._store.clear()
        with self._lock:
            for runtime in self._runtimes.values():
                self._retire(runtime)
            self._runtimes.clear()
            self._configs.clear()
            runtime = self._env_runtime()
            self._runtimes[ENV_RUNTIME_ID] = runtime
            running = self._started
        if running:
            runtime.start()
