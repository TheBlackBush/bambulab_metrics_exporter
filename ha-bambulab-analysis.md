# ha-bambulab Analysis - Features We Could Add

## Executive Summary
The `ha-bambulab` Home Assistant integration exposes **significantly more** sensors and features than our current Prometheus exporter. Below is a detailed breakdown of what they have that we don't, organized by priority and implementation complexity.

---

## 🔴 High Priority - Missing Core Metrics

### 1. **Print Job Details**
They expose rich print job metadata that we're currently missing:

- ✅ **Already have:** `gcode_file`, `subtask_name`, `print_progress`, `remaining_time`, `current_layer`, `total_layers`
- ❌ **Missing:**
  - `print_type` (enum: "cloud", "local", "slicer")
  - `print_bed_type` (string: bed type used)
  - `printable_objects` (count + list of object names)
  - `skipped_objects` (count + list of skipped objects)
  - `gcode_file_downloaded` (separate from `gcode_file`)
  - `model_download_percentage` (for cloud prints)

**Value:** These are useful for understanding print job origins and multi-part prints.

---

### 2. **AMS (Automatic Material System) Sensors**
They have comprehensive AMS tracking per unit:

- ✅ **Already have:** None (we don't track AMS at all!)
- ❌ **Missing:**
  - `humidity_index` (1-5 scale, inverted from printer)
  - `humidity` (percentage, for newer AMS units)
  - `temperature` (AMS internal temp)
  - `remaining_drying_time` (for AMS 2 Pro / AMS HT)
  - `tray_1`, `tray_2`, `tray_3`, `tray_4` (per-tray filament info with rich attributes)
  - `active_ams` (binary sensor: is this AMS unit active?)
  - `drying` (binary sensor: is this AMS drying filament?)

**Each tray exposes:**
- `color`, `cols` (multi-color support)
- `ctype` (filament type)
- `bed_temp`, `nozzle_temp_min`, `nozzle_temp_max`
- `dry_temp`, `dry_time`
- `remain` (remaining filament %)
- `tag_uid`, `tray_uuid`
- `k_value` (pressure advance)

**Value:** **Critical** for users with AMS units. This is a major gap in our exporter.

---

### 3. **External Spool (Virtual Tray) Support**
They track external spools (non-AMS filament) separately:

- ✅ **Already have:** None
- ❌ **Missing:**
  - `external_spool` sensor (with same rich attributes as AMS trays)
  - Support for dual nozzles (left/right external spools)

**Value:** Important for users without AMS or using external filament.

---

### 4. **Active Tray Info**
They expose a single `active_tray` sensor with all current filament details as attributes:

- ✅ **Already have:** None
- ❌ **Missing:**
  - `active_tray` (name of currently active filament)
  - Attributes: `ams_index`, `bed_temp`, `color`, `ctype`, `k_value`, `nozzle_temp_min/max`, `remain`, `type`, etc.

**Value:** **Very useful** for dashboards - single metric to see what's currently loaded.

---

### 5. **Hotend Rack System (X1 Plus)**
For printers with automatic nozzle changers:

- ✅ **Already have:** None
- ❌ **Missing:**
  - `hotend_rack_holder_position` (enum: a_top, b_top, centre)
  - `hotend_rack_holder_state` (enum: idle, pick_hotend, place_hotend, etc.)
  - `hotend_1` through `hotend_6` (per-hotend status: mounted, docked, empty)
  - Per-hotend attributes: `nozzle_type`, `nozzle_diameter`, `serial`, `max_temp`, `wear`, `status`, `color`, `filament_id`

**Value:** **Critical** for X1 Plus users. Currently unsupported.

---

### 6. **Dual Nozzle Support**
They have full support for dual-nozzle printers:

- ✅ **Already have:** None
- ❌ **Missing:**
  - `left_nozzle_temp`, `left_target_nozzle_temp`
  - `right_nozzle_temp`, `right_target_nozzle_temp`
  - `left_nozzle_diameter`, `left_nozzle_type`
  - `right_nozzle_diameter`, `right_nozzle_type`
  - `active_nozzle_temperature`, `active_nozzle_target_temperature` (unified active nozzle tracking)

**Value:** **Required** for dual-nozzle printer support (e.g., X1 Plus with IDEX).

---

### 7. **Binary Sensors (State Indicators)**
They expose many binary sensors we don't track:

- ✅ **Already have:** `print_error` (as gauge)
- ❌ **Missing:**
  - `timelapse` (is timelapse recording enabled?)
  - `extruder_filament_state` (is filament loaded?)
  - `hms_errors` (HMS error present?) + error details as attributes
  - `online` (is printer online?)
  - `firmware_update` (is firmware update available?)
  - `door_open` (is door open? - for printers with door sensor)
  - `airduct_mode` (is air duct open/closed?)
  - `developer_lan_mode` (is LAN mode enabled without encryption?)
  - `mqtt_encryption` (is MQTT encryption enabled?)
  - `hybrid_mode_blocks_control` (is hybrid mode blocking control?)

**Value:** Binary sensors are **excellent** for Prometheus alerting.

---

### 8. **Diagnostic Sensors**
Useful for troubleshooting:

- ✅ **Already have:** `wifi_signal`, `serial`
- ❌ **Missing:**
  - `mqtt_mode` (enum: "bambu_cloud" or "local")
  - `tool_module` (enum: "none", "laser10", "laser40", "cutter")
  - `sdcard_status` (enum: status of SD card)
  - `ip_address` (printer IP)
  - `total_usage_hours` (lifetime printer usage)

**Value:** Nice-to-have for diagnostics and monitoring.

---

## 🟡 Medium Priority - Enhanced Features

### 9. **Fan Speed Tracking**
They expose all fan speeds as percentages:

- ✅ **Already have:** `bambulab_fan_gear` (cooling fan speed as 0-15 scale)
- ❌ **Missing (converted to %):**
  - `aux_fan_speed` (auxiliary fan)
  - `chamber_fan_speed` (chamber fan)
  - `cooling_fan_speed` (part cooling fan)
  - `heatbreak_fan_speed` (heatbreak fan)

**Value:** We have the raw data, but they convert to %. Consider adding `_percent` metrics.

---

### 10. **Advanced Print Job Metrics**
They expose detailed print metrics:

- ✅ **Already have:** None
- ❌ **Missing:**
  - `print_length` (meters of filament used, with per-filament breakdown as attributes)
  - `print_weight` (grams of filament used, with per-filament breakdown as attributes)

**Value:** Great for material usage tracking and cost estimation.

---

### 11. **Nozzle Info**
They track both active and per-side nozzles:

- ✅ **Already have:** `bambulab_nozzle_diameter`
- ❌ **Missing:**
  - `nozzle_type` (hardened, standard, etc.)
  - `active_nozzle_diameter` (for dual-nozzle: which is active)
  - `active_nozzle_type`

**Value:** Useful for tracking nozzle wear and configuration.

---

### 12. **Chamber Heater Support**
They have chamber heater metrics:

- ✅ **Already have:** `bambulab_chamber_temp`
- ❌ **Missing:**
  - `target_chamber_temp` (only for printers with active chamber heater)

**Value:** Only relevant for X1 Plus with chamber heater.

---

## 🟢 Low Priority - Nice-to-Have

### 13. **Start/End Time with Restore Logic**
They have sophisticated start/end time handling:

- ✅ **Already have:** None
- ❌ **Missing:**
  - `start_time` (with LAN-mode restore from previous state)
  - `end_time` (calculated end time)

**Implementation:** They use Home Assistant's `RestoreEntity` to persist `start_time` across restarts (important for LAN mode where start time isn't in MQTT).

**Value:** Nice for accurate print duration tracking, but complex to implement in Prometheus.

---

### 14. **Print File Type Icons**
They dynamically set icons based on file type:

- **Implementation:** `icon_fn=lambda self: self.coordinator.get_model().print_job.file_type_icon`
- **Value:** UI-only, not relevant for Prometheus.

---

## 🔧 Implementation Recommendations

### Phase 1: AMS Support (High ROI)
**Effort:** Medium | **Value:** Very High

1. Add AMS unit discovery (support multiple AMS units)
2. Expose per-AMS metrics:
   - `bambulab_ams_humidity_index{ams_serial, ams_index}`
   - `bambulab_ams_humidity{ams_serial, ams_index}`
   - `bambulab_ams_temperature{ams_serial, ams_index}`
   - `bambulab_ams_drying_time_remaining{ams_serial, ams_index}`
3. Expose per-tray metrics:
   - `bambulab_ams_tray_info{ams_serial, tray_index, name, type, color}`
   - `bambulab_ams_tray_remain_pct{ams_serial, tray_index}`
   - `bambulab_ams_tray_active{ams_serial, tray_index}` (binary)

---

### Phase 2: Binary Sensors (High ROI, Low Effort)
**Effort:** Low | **Value:** High

Add binary metrics (0/1 gauges):
- `bambulab_timelapse_enabled`
- `bambulab_filament_loaded`
- `bambulab_hms_error`
- `bambulab_door_open`
- `bambulab_firmware_update_available`
- `bambulab_mqtt_encryption_enabled`

---

### Phase 3: Print Job Enhancement (Medium ROI)
**Effort:** Low | **Value:** Medium

Add:
- `bambulab_print_type{type}` (info metric)
- `bambulab_print_bed_type_info{bed_type}`
- `bambulab_printable_objects_count`
- `bambulab_print_length_meters`
- `bambulab_print_weight_grams`

---

### Phase 4: Dual Nozzle & Hotend Rack (High ROI for X1 Plus users)
**Effort:** High | **Value:** High (for specific users)

Add:
- Dual nozzle temp tracking
- Hotend rack status (6 slots)
- Per-hotend wear tracking

---

### Phase 5: External Spool (Medium ROI)
**Effort:** Low | **Value:** Medium

Add:
- `bambulab_external_spool_info{spool_index, name, type, color}`
- `bambulab_external_spool_remain_pct{spool_index}`

---

## 📊 Data Sources in ha-bambulab

They use a `pybambu` library that parses MQTT messages into structured models:

### Key Model Classes:
- `PrintJob` - all print job data
- `AMS` - AMS units and trays
- `Temperature` - all temperatures
- `Fans` - fan speeds (with `FansEnum`)
- `Speed` - speed profile
- `Stage` - current stage
- `HotendRack` - hotend rack system
- `HMS` - error codes
- `HomeFlag` - SD card status, etc.

### MQTT Message Parsing:
- They subscribe to `device/{serial}/report` and parse JSON payloads
- Data is normalized and exposed through the coordinator pattern

---

## 🎯 Conclusion

**Top 3 Priorities for Our Exporter:**

1. **AMS Support** - Massive gap, high user value
2. **Binary Sensors** - Easy wins for alerting
3. **Print Job Enhancement** - Better material tracking

**Estimated Effort:**
- Phase 1 (AMS): ~2-3 days
- Phase 2 (Binary): ~4-6 hours
- Phase 3 (Print Job): ~4-6 hours

**Total New Metrics Estimate:** ~50-70 new metrics across all phases.

---

## 📝 Notes

- They handle **feature flags** extensively (`Features.DUAL_NOZZLES`, `Features.AMS_DRYING`, etc.) to support different printer models
- They have **robust error handling** with HMS error code mapping
- They support both **cloud** and **local** MQTT modes with different data availability
- They use **RestoreEntity** pattern in Home Assistant to persist state across restarts (not directly applicable to Prometheus)

**Source Repository:** https://github.com/greghesp/ha-bambulab
**Last Analyzed:** 2026-03-15
