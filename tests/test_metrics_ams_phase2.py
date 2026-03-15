from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_ams_k_value_and_string_remain() -> None:
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
                                {"id": "1", "remain": "77.5", "tray_color": "ffffff", "ctype": "PLA", "k": "0.019"}
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
    assert metrics.ams_slot_k_value.labels(**labels, ams_id="0", slot_id="1")._value.get() == 0.019


def test_ams_k_value_fallback_field_names() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "tray": [
                                {"id": "1", "k_value": "0.031", "tray_type": "PETG", "tray_color": "161616ff"},
                                {"id": "2", "K": 0.027, "tray_type": "PLA", "tray_color": "ffffff"},
                            ],
                        }
                    ]
                }
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    labels = {"printer_name": "p1", "serial": "SN123"}
    assert metrics.ams_slot_k_value.labels(**labels, ams_id="0", slot_id="1")._value.get() == 0.031
    assert metrics.ams_slot_k_value.labels(**labels, ams_id="0", slot_id="2")._value.get() == 0.027


def test_ams_invalid_k_value_is_ignored() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "tray": [{"id": "1", "k": "bad-value", "tray_type": "PETG", "tray_color": "161616ff"}],
                        }
                    ]
                }
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    labels = {"printer_name": "p1", "serial": "SN123", "ams_id": "0", "slot_id": "1"}
    assert metrics.ams_slot_k_value.labels(**labels)._value.get() == 0.0
