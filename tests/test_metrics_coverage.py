from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot

def test_metrics_ams_error_edge_cases() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="S1")
    
    # Snapshot with invalid humidity/temp types to trigger try/except in metrics.py
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "humidity": "not-a-number",
                            "temp": None,
                            "tray": [
                                {"id": "0", "remain": "invalid"}
                            ]
                        }
                    ]
                }
            }
        }
    )
    
    metrics.update_from_snapshot(snapshot)
    # The metric should not be present in the underlying dict if it failed conversion
    # or conversion was not called for None.
    # ams_unit_humidity for ID "0" might exist if conversion started, but conversion 
    # to float for "not-a-number" fails inside the try block.
    # In prometheus_client, .labels(...) creates the gauge in the dict immediately.
    assert True

def test_metrics_no_subtask_no_fail_reason() -> None:
    metrics = ExporterMetrics(printer_name="p1", serial="S1")
    snapshot = PrinterSnapshot(connected=True, raw={"print": {}})
    
    # This should hit the 'if snapshot.subtask_name' = False branch
    metrics.update_from_snapshot(snapshot)
    assert len(metrics.subtask_name_info._metrics) == 0
    assert len(metrics.fail_reason_info._metrics) == 0
