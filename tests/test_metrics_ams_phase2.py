from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_ams_string_remain_and_tray_type_fallback() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "tray_now": "1",
                            "tray": [
                                {"id": "1", "remain": "77.5", "tray_color": "ffffff", "ctype": "PLA"}
                            ],
                        }
                    ]
                }
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    labels = {"printer_name": "p1", "serial": "SN123"}

    assert metrics.ams_slot_remaining_percent.labels(**labels, ams_id="0", slot_id="1")._value.get() == 77.5
    assert metrics.ams_slot_tray_type.labels(**labels, ams_id="0", slot_id="1", tray_type="PLA")._value.get() == 1.0


def test_ams_invalid_remain_is_ignored() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "tray": [{"id": "1", "remain": "bad-value", "tray_type": "PETG", "tray_color": "161616ff"}],
                        }
                    ]
                }
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    labels = {"printer_name": "p1", "serial": "SN123", "ams_id": "0", "slot_id": "1"}
    assert metrics.ams_slot_remaining_percent.labels(**labels)._value.get() == 0.0
