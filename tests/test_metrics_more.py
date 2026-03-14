from bambulab_metrics_exporter.metrics import ExporterMetrics
from bambulab_metrics_exporter.models import PrinterSnapshot


def test_metrics_full_update_with_ams_lights_xcam() -> None:
    metrics = ExporterMetrics(printer_name="p1", site="s", location="l")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={
            "print": {
                "gcode_state": "RUNNING",
                "mc_print_stage": "PRINTING",
                "mc_percent": 50,
                "mc_remaining_time": 10,
                "layer_num": 100,
                "total_layer_num": 200,
                "nozzle_temper": 210,
                "nozzle_target_temper": 220,
                "bed_temper": 60,
                "bed_target_temper": 65,
                "chamber_temper": 34,
                "big_fan1_speed": "33",
                "big_fan2_speed": "44",
                "cooling_fan_speed": "55",
                "heatbreak_fan_speed": "66",
                "mc_stage": 1,
                "mc_print_sub_stage": 2,
                "print_real_action": 3,
                "print_gcode_action": 4,
                "wifi_signal": "-60",
                "online": {"ahb": True, "ext": True},
                "ams_status": 1,
                "ams_rfid_status": 2,
                "print_error": 0,
                "ap_err": 0,
                "mc_print_error_code": "0",
                "fail_reason": "filament runout",
                "lights_report": [
                    {"node": "chamber_light", "mode": "on"},
                    {"node": "work_light", "mode": "off"},
                ],
                "xcam": {"printing_monitor": True, "spaghetti_detector": False},
                "ams": {
                    "tray_now": "2",
                    "ams": [
                        {
                            "id": "1",
                            "humidity": "18",
                            "temp": "23",
                            "tray": [
                                {"id": "2", "remain": 87, "tray_type": "PLA", "tray_color": "f98c36ff"},
                                {"id": "3", "remain": 50, "tray_type": "PETG", "tray_color": "161616ff"},
                            ],
                        }
                    ],
                },
            }
        },
    )

    metrics.update_from_snapshot(snapshot)
    metrics.mark_scrape(0.1, True, now_ts=111.0)

    labels = dict(printer_name="p1", site="s", location="l")
    assert metrics.printer_up.labels(**labels)._value.get() == 1.0
    assert metrics.chamber_light_on.labels(**labels)._value.get() == 1.0
    assert metrics.work_light_on.labels(**labels)._value.get() == 0.0
    assert metrics.print_error_raw.labels(**labels)._value.get() == 0.0
    assert (
        metrics.fail_reason_info.labels(**labels, fail_reason="filament runout")._value.get() == 1.0
    )
    assert metrics.ams_unit_humidity.labels(**labels, ams_id="1")._value.get() == 18.0
    assert metrics.ams_slot_tray_type.labels(**labels, ams_id="1", slot_id="2", tray_type="PLA")._value.get() == 1.0
    assert metrics.ams_slot_tray_color.labels(**labels, ams_id="1", slot_id="2", tray_color="F98C36FF")._value.get() == 1.0


def test_metrics_work_light_flashing_treated_as_on() -> None:
    metrics = ExporterMetrics(printer_name="p1", site="s", location="l")
    snapshot = PrinterSnapshot(
        connected=True,
        raw={"print": {"lights_report": [{"node": "work_light", "mode": "flashing"}]}},
    )

    metrics.update_from_snapshot(snapshot)
    labels = dict(printer_name="p1", site="s", location="l")
    assert metrics.work_light_on.labels(**labels)._value.get() == 1.0
