"""Existing metrics are a public API: this test fails on a rename, type or label change."""
from __future__ import annotations

import json
from pathlib import Path

from bambulab_metrics_exporter.metrics import ExporterMetrics

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "metrics_contract.json"


def _current() -> dict[str, dict[str, object]]:
    metrics = ExporterMetrics(printer_name="x", serial="y")
    return {
        gauge._name: {"type": gauge._type, "labels": list(gauge._labelnames)}
        for gauge in vars(metrics).values()
        if hasattr(gauge, "_labelnames")
    }


def test_existing_metrics_are_unchanged() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    current = _current()
    changed = {name: spec for name, spec in contract.items() if current.get(name) != spec}
    assert changed == {}, "existing metrics changed; this breaks users' dashboards and alerts"
