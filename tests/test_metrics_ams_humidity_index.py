from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_ams_humidity_index_mixed_payload_variants() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {"id": "0", "humidity": "20", "humidity_raw": "62", "humidity_index": "6"},
                        {"id": "1", "humidity": 30, "humidity_raw": 58, "humidity_level": 4},
                        {"id": "2", "humidity": "25"},
                    ]
                }
            }
        },
    )

    metrics.update_from_snapshot(snapshot)

    labels = {"printer_name": "p1", "serial": "SN123"}
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get() == 6.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 4.0
    # Falls back to MQTT humidity field when explicit index fields are missing.
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="2")._value.get() == 25.0

    # Raw humidity metric prefers humidity_raw and falls back to humidity.
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="0")._value.get() == 62.0
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="1")._value.get() == 58.0
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="2")._value.get() == 25.0


def test_ams_humidity_index_invalid_values_are_skipped() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {"id": "0", "humidity_index": "oops"},
                        {"id": "1", "humidity_level": None},
                        {"id": "2", "humidityIndex": "nan"},
                    ]
                }
            }
        },
    )

    metrics.update_from_snapshot(snapshot)

    assert len(metrics.ams_unit_humidity_index._metrics) == 0


def test_ams_humidity_index_per_ams_refresh_behavior() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="SN123")
    labels = {"printer_name": "p1", "serial": "SN123"}

    first_snapshot = PrinterSnapshot(
        connected=True,
        raw={"print": {"ams": {"ams": [{"id": "0", "humidity_level": 3}, {"id": "1", "humidity_level": 5}]}}},
    )
    metrics.update_from_snapshot(first_snapshot)

    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get() == 3.0
    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="1")._value.get() == 5.0

    second_snapshot = PrinterSnapshot(
        connected=True,
        raw={"print": {"ams": {"ams": [{"id": "0", "humidity_level": "7"}, {"id": "1", "humidity_level": "bad"}]}}},
    )
    metrics.update_from_snapshot(second_snapshot)

    assert metrics.ams_unit_humidity_index.labels(**labels, ams_id="0")._value.get() == 7.0
    assert (labels["printer_name"], labels["serial"], "1") not in metrics.ams_unit_humidity_index._metrics
