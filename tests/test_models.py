from bambulab_metrics_exporter.models import PrinterSnapshot


def test_snapshot_extracts_core_fields() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "gcode_state": "RUNNING",
                "mc_percent": 42,
                "mc_remaining_time": 11,
                "layer_num": 196,
                "total_layer_num": 240,
                "nozzle_temper": 215.5,
                "bed_temper": 60,
                "chamber_temper": 36,
                "mc_print_error_code": 0,
            }
        },
    )

    assert snap.gcode_state == "RUNNING"
    assert snap.progress_percent == 42.0
    assert snap.remaining_seconds == 660.0
    assert snap.layer_current == 196.0
    assert snap.layer_total == 240.0
    assert round(snap.layer_progress_percent or 0.0, 2) == 81.67
    assert snap.nozzle_temp == 215.5
    assert snap.bed_temp == 60.0
    assert snap.chamber_temp == 36.0
    assert snap.print_error_code == 0
