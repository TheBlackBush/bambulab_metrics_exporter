from bambulab_metrics_exporter.models import PrinterSnapshot


def test_model_parsing_extended_fields() -> None:
    snap = PrinterSnapshot(
        connected=False,
        raw={
            "print": {
                "fan_gear": 10,
                "big_fan1_speed": "40",
                "big_fan2_speed": "55",
                "cooling_fan_speed": "60",
                "heatbreak_fan_speed": "70",
                "mc_stage": "2",
                "mc_print_sub_stage": 3,
                "print_real_action": "4",
                "print_gcode_action": "5",
                "mc_print_stage": "PRINTING",
                "wifi_signal": "-62",
                "online": {"ahb": True, "ext": False},
                "ams_status": "1",
                "ams_rfid_status": 2,
                "queue_total": "3",
                "queue_est": "120",
                "queue_number": 4,
                "queue_sts": "5",
                "queue": "6",
                "lights_report": [{"node": "chamber_light", "mode": "on"}],
                "xcam": {
                    "allow_skip_parts": True,
                    "buildplate_marker_detector": False,
                    "first_layer_inspector": True,
                    "print_halt": False,
                    "printing_monitor": True,
                    "spaghetti_detector": False,
                },
            }
        },
    )

    assert snap.fan_gear is not None
    assert snap.fan_big_1_percent == 40.0
    assert snap.fan_big_2_percent == 55.0
    assert snap.fan_cooling_percent == 60.0
    assert snap.fan_heatbreak_percent == 70.0
    assert snap.mc_stage == 2.0
    assert snap.mc_print_sub_stage == 3.0
    assert snap.print_real_action == 4.0
    assert snap.print_gcode_action == 5.0
    assert snap.mc_print_stage_name == "PRINTING"
    assert snap.wifi_signal == -62.0
    assert snap.online_ahb == 1.0
    assert snap.online_ext == 0.0
    assert snap.ams_status == 1.0
    assert snap.ams_rfid_status == 2.0
    assert snap.queue_total == 3.0
    assert snap.queue_est == 120.0
    assert snap.queue_number == 4.0
    assert snap.queue_status == 5.0
    assert snap.queue_position == 6.0
    assert len(snap.lights_report) == 1
    assert snap.xcam_flags["allow_skip_parts"] == 1.0


def test_model_chamber_temp_fallback_and_defaults() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"device": {"ctc": {"info": {"temp": 31}}}}},
    )
    assert snap.chamber_temp == 31.0
    assert snap.subtask_name is None
