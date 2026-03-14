from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_metrics_update_smoke() -> None:
    metrics = ExporterMetrics(printer_name="x1c", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "gcode_state": "RUNNING",
                "mc_percent": 10,
                "mc_remaining_time": 20,
                "nozzle_temper": 205,
                "bed_temper": 58,
                "mc_print_error_code": 0,
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    metrics.mark_scrape(0.4, True, now_ts=123.0)

    value = metrics.printer_up.labels(printer_name="x1c", serial="SN123")._value.get()
    assert value == 1.0
