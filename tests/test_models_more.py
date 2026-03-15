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
                "nozzle_diameter": "0.4",
                "wifi_signal": "-62",
                "online": {"ahb": True, "ext": False},
                "ams_status": "1",
                "ams_rfid_status": 2,
                "queue_total": "3",
                "queue_est": "120",
                "queue_number": 4,
                "queue_sts": "5",
                "queue": "6",
                "spd_lvl": 3,
                "spd_mag": 124,
                "sn": "SN123456",
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
    assert snap.fan_gear_raw == 10.0
    assert snap.fan_big_1_percent == 40.0
    assert snap.fan_big_2_percent == 55.0
    assert snap.fan_cooling_percent == 60.0
    assert snap.fan_heatbreak_percent == 70.0
    assert snap.mc_stage == 2.0
    assert snap.mc_print_sub_stage == 3.0
    assert snap.print_real_action == 4.0
    assert snap.print_gcode_action == 5.0
    assert snap.mc_print_stage_name == "PRINTING"
    assert snap.nozzle_diameter == 0.4
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
    assert snap.spd_lvl == 3.0
    assert snap.spd_mag == 124.0
    assert snap.sn == "SN123456"
    assert len(snap.lights_report) == 1
    assert snap.xcam_flags["allow_skip_parts"] == 1.0


def test_model_chamber_temp_fallback_and_defaults() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"device": {"ctc": {"info": {"temp": 31}}}}},
    )
    assert snap.chamber_temp == 31.0
    assert snap.subtask_name is None


def test_model_wifi_signal_dbm_string() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"wifi_signal": "-42dBm"}},
    )
    assert snap.wifi_signal == -42.0


def test_model_fail_reason_string() -> None:
    snap = PrinterSnapshot(
        connected=True,
        raw={"print": {"fail_reason": "filament runout"}},
    )
    assert snap.fail_reason == "filament runout"


def test_model_name_discovery_paths() -> None:
    # Mapping from legacy device.type
    snap_p1s = PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 3}}})
    assert snap_p1s.model_name == "P1S"

    # Fallback to model_id
    snap_fallback = PrinterSnapshot(connected=True, raw={"print": {"model_id": "X1C"}})
    assert snap_fallback.model_name == "X1C"

    # Unknown type
    snap_unknown = PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 99}}})
    assert snap_unknown.model_name is None


def test_printer_type_detection_from_module_metadata() -> None:
    by_product = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "ota", "product_name": "Bambu Lab H2D"}]},
    )
    assert by_product.printer_type == "H2D"

    by_hw_project = PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "esp32", "hw_ver": "AP04", "project_name": "C12"}]},
    )
    assert by_hw_project.printer_type == "P1S"


def test_model_edge_cases_from_legacy_coverage_file() -> None:
    snap_no_nozzle = PrinterSnapshot(connected=True, raw={"print": {"vt_tray": None}})
    assert snap_no_nozzle.nozzle_temp is None

    snap_fan_high = PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 50}})
    assert snap_fan_high.fan_gear == 50.0

    snap_ams_tray = PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "1"}}})
    assert snap_ams_tray.ams_tray_now == "1"

    snap_ams_name = PrinterSnapshot(connected=True, raw={"print": {"ams": {"ams": [{"id": "0", "name": "AMS1"}]}}})
    assert snap_ams_name.ams_units[0]["name"] == "AMS1"

    snap_no_sub = PrinterSnapshot(connected=True, raw={"print": {"subtask_name": 123}})
    assert snap_no_sub.subtask_name is None
