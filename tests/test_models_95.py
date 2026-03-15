from bambulab_metrics_exporter import models

def test_models_more_edges_for_95_percent():
    # Line 100: nozzle_temp returning None when structure is missing
    # We need to break the nested structure: vt_tray or nozzle_temper
    # Wait, the code is: nested = self.print_block.get("vt_tray", {})
    # So if we provide an empty dict, it skips the inside.
    snap_no_nozzle = models.PrinterSnapshot(connected=True, raw={"print": {"vt_tray": None}})
    assert snap_no_nozzle.nozzle_temp is None
    
    # Line 127: fan_gear returning raw value when > 15
    snap_fan_high = models.PrinterSnapshot(connected=True, raw={"print": {"fan_gear": 50}})
    assert snap_fan_high.fan_gear == 50.0
    
    # Line 250-252: ams_tray_now with valid string
    snap_ams_tray = models.PrinterSnapshot(connected=True, raw={"print": {"ams": {"tray_now": "1"}}})
    assert snap_ams_tray.ams_tray_now == "1"
    
    # Line 272: ams_units name strip
    # Wait, the models.py code does NOT strip the name, it just returns it if it is a string.
    # Ah, I see: it checks if 'name' in ams, if so returns ams['name'].
    # There is NO .strip() in models.py for ams name! 
    # Let me check models.py again.
    snap_ams_name = models.PrinterSnapshot(connected=True, raw={"print": {"ams": {"ams": [{"id": "0", "name": "AMS1"}]}}})
    assert snap_ams_name.ams_units[0]["name"] == "AMS1"
    
    # Line 287: gcode_file None -> wait, I checked models.py again, it is subtask_name
    # 269: @property
    # 270: def subtask_name(self) -> str | None:
    # 271:     value = self.print_block.get("subtask_name")
    # 272:     if isinstance(value, str):
    # 273:         return value
    # 274:     return None
    snap_no_sub = models.PrinterSnapshot(connected=True, raw={"print": {"subtask_name": 123}})
    assert snap_no_sub.subtask_name is None

def test_model_name_discovery():
    # Test mapping from legacy device.type
    snap_p1s = models.PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 3}}})
    assert snap_p1s.model_name == "P1S"

    # Test fallback to model_id
    snap_fallback = models.PrinterSnapshot(connected=True, raw={"print": {"model_id": "X1C"}})
    assert snap_fallback.model_name == "X1C"

    # Test unknown type
    snap_unknown = models.PrinterSnapshot(connected=True, raw={"print": {"device": {"type": 99}}})
    assert snap_unknown.model_name is None


def test_printer_type_detection_from_product_name_modules():
    snap = models.PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "ota", "product_name": "Bambu Lab H2D"}]},
    )
    assert snap.printer_type == "H2D"


def test_printer_type_detection_from_hw_ver_project_name():
    snap = models.PrinterSnapshot(
        connected=True,
        raw={"module": [{"name": "esp32", "hw_ver": "AP04", "project_name": "C12"}]},
    )
    assert snap.printer_type == "P1S"
