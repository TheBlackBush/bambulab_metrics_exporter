# Metrics Reference

All metrics include stable labels: `printer_name` and `serial`.

---

## Exporter Health

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_printer_up` | Gauge | 1 if latest poll returned a valid payload |
| `bambulab_printer_connected` | Gauge | 1 if MQTT connection is up |
| `bambulab_exporter_scrape_duration_seconds` | Gauge | Duration of last scrape cycle |
| `bambulab_exporter_scrape_success` | Gauge | 1 when last scrape succeeded |
| `bambulab_exporter_last_success_unixtime` | Gauge | Unix timestamp of last successful scrape |

---

## Print Progress

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_print_progress_percent` | Gauge | Print progress percent |
| `bambulab_print_remaining_seconds` | Gauge | Estimated seconds remaining |
| `bambulab_print_layer_current` | Gauge | Current print layer |
| `bambulab_print_layer_total` | Gauge | Total print layers |
| `bambulab_print_layer_progress_percent` | Gauge | Layer-based progress percent |

---

## Print State

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_printer_gcode_state{state}` | One-hot Gauge | Current gcode state |
| `bambulab_subtask_name_info{subtask_name}` | Info Gauge | Current subtask name |
| `bambulab_fail_reason_info{fail_reason}` | Info Gauge | Current fail reason |
| `bambulab_stg_cur` | Gauge | Current stage numeric ID |
| `bambulab_print_stage_info{stage}` | Info Gauge | Current stage name |
| `bambulab_printer_model_info{model}` | Info Gauge | Detected printer model |

---

## Temperatures

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_nozzle_temperature_celsius` | Gauge | Current nozzle temperature |
| `bambulab_nozzle_target_temperature_celsius` | Gauge | Target nozzle temperature |
| `bambulab_nozzle_diameter` | Gauge | Nozzle diameter from telemetry |
| `bambulab_bed_temperature_celsius` | Gauge | Current bed temperature |
| `bambulab_bed_target_temperature_celsius` | Gauge | Target bed temperature |
| `bambulab_chamber_temperature_celsius` | Gauge | Chamber temperature |

---

## Fans

Fan values: raw levels 0–15 → nearest-10 percent normalization.

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_fan_big_1_speed_percent` | Gauge | Big fan 1 speed percent |
| `bambulab_fan_big_2_speed_percent` | Gauge | Big fan 2 speed percent |
| `bambulab_fan_cooling_speed_percent` | Gauge | Cooling fan speed percent |
| `bambulab_fan_heatbreak_speed_percent` | Gauge | Heatbreak fan speed percent |
| `bambulab_fan_secondary_aux_speed_percent` | Gauge | Secondary auxiliary fan speed percent |

---

## Errors

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_printer_error` | Gauge | 1 when printer error code is non-zero |
| `bambulab_printer_error_code` | Gauge | Raw printer error code |
| `bambulab_print_error` | Gauge | Raw print_error value from MQTT |
| `bambulab_ap_error_code` | Gauge | Raw ap_err value from MQTT |

---

## AMS

### Status

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_ams_status_id` | Gauge | AMS status numeric code |
| `bambulab_ams_status_name{status}` | Info Gauge | AMS status name |
| `bambulab_ams_rfid_status_id` | Gauge | AMS RFID status numeric code |
| `bambulab_ams_rfid_status_name{status}` | Info Gauge | AMS RFID status name |

### Unit

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_ams_unit_info{ams_id,ams_model,ams_series}` | Info Gauge | AMS unit identity |
| `bambulab_ams_unit_humidity{ams_id}` | Gauge | AMS humidity raw value |
| `bambulab_ams_unit_humidity_index{ams_id}` | Gauge | AMS humidity index (1–5) |
| `bambulab_ams_unit_temperature_celsius{ams_id}` | Gauge | AMS temperature |

### Slots

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_ams_slot_active{ams_id,slot_id}` | Gauge | AMS slot active flag |
| `bambulab_ams_slot_remaining_percent{ams_id,slot_id}` | Gauge | Remaining filament % |
| `bambulab_ams_slot_tray_info{ams_id,slot_id,tray_type,tray_color}` | Info Gauge | Filament type and color |

### Gen2 Drying (only when `ams_info` present)

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_ams_heater_state_info{...,state}` | Info Gauge | Gen2 AMS heater/dry state |
| `bambulab_ams_dry_fan_status{...,fan_id}` | Gauge | Gen2 AMS drying fan status |
| `bambulab_ams_dry_sub_status_info{...,state}` | Info Gauge | Gen2 AMS drying sub-status |

---

## External Spool

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_external_spool_active` | Gauge | 1 when external spool is active |
| `bambulab_external_spool_info{...}` | Info Gauge | External spool metadata |

---

## Multi-Extruder (H2D / H2D Pro)

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_active_extruder_index` | Gauge | Active extruder index |
| `bambulab_extruder_temperature_celsius{extruder_id}` | Gauge | Per-extruder current temperature |
| `bambulab_extruder_target_temperature_celsius{extruder_id}` | Gauge | Per-extruder target temperature |
| `bambulab_extruder_nozzle_info{extruder_id,nozzle_type,nozzle_diameter}` | Info Gauge | Per-extruder nozzle metadata |
| `bambulab_active_nozzle_info{nozzle_type,nozzle_diameter}` | Info Gauge | Active nozzle metadata |

---

## Hotend Rack

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_hotend_rack_holder_position_info{position}` | Info Gauge | Holder position |
| `bambulab_hotend_rack_holder_state_info{state}` | Info Gauge | Holder state |
| `bambulab_hotend_rack_slot_state_info{slot_id,state}` | Info Gauge | Slot state |
| `bambulab_hotend_rack_hotend_info{slot_id,nozzle_type,nozzle_diameter}` | Info Gauge | Slot nozzle metadata |
| `bambulab_hotend_rack_hotend_wear_ratio{slot_id}` | Gauge | Nozzle wear ratio |
| `bambulab_hotend_rack_hotend_runtime_minutes{slot_id}` | Gauge | Nozzle runtime minutes |

---

## Connectivity & Flags

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_wifi_signal` | Gauge | Wi-Fi signal (dBm) |
| `bambulab_wired_network` | Gauge | Wired network detected |
| `bambulab_door_open` | Gauge | Door open flag |
| `bambulab_sdcard_status_info{status}` | Info Gauge | SD card status |
| `bambulab_chamber_light_on` | Gauge | Chamber light (1/0) |
| `bambulab_work_light_on` | Gauge | Work light (1/0) |
| `bambulab_camera_recording` | Gauge | Camera recording flag |
| `bambulab_xcam_feature_enabled{feature}` | Gauge | XCam feature flags |
| `bambulab_ams_auto_switch` | Gauge | AMS auto-switch flag |
| `bambulab_filament_tangle_detected` | Gauge | Filament tangle detected |
| `bambulab_filament_tangle_detect_supported` | Gauge | Filament tangle detection supported |

---

## Queue & Speed

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_queue_total` | Gauge | Total queued jobs |
| `bambulab_queue_estimated_seconds` | Gauge | Estimated queue seconds |
| `bambulab_queue_number` | Gauge | Queue number |
| `bambulab_queue_status` | Gauge | Queue status code |
| `bambulab_queue_position` | Gauge | Queue position |
| `bambulab_spd_lvl` | Gauge | Speed level numeric value |
| `bambulab_spd_mag` | Gauge | Speed multiplier/percentage |
| `bambulab_spd_lvl_state{mode}` | One-hot Gauge | Speed mode one-hot |

---

## Internal / Diagnostic Metrics

> **Note:** The exporter may expose additional low-level or diagnostic gauges sourced directly from raw MQTT telemetry (e.g. raw status codes, internal counters). These metrics are not listed above because they reflect internal printer state, may change between firmware versions, and are not intended for production alerting. If you observe unlisted `bambulab_*` metrics in your Prometheus instance, treat them as diagnostic/informational only.

---

## PromQL Examples

```promql
# Average AMS humidity index over 15 minutes
avg_over_time(bambulab_ams_unit_humidity_index{printer_name="$printer"}[15m])

# Lowest remaining filament % per printer
min by (printer_name) (bambulab_ams_slot_remaining_percent)

# Slots below 15% remaining
bambulab_ams_slot_remaining_percent{printer_name="$printer"} < 15

# Door open while printing
bambulab_door_open{printer_name="$printer"} == 1
and on(printer_name, serial)
bambulab_printer_gcode_state{printer_name="$printer", state="RUNNING"} == 1

# Stale exporter
time() - bambulab_exporter_last_success_unixtime{printer_name="$printer"} > 300

# SD card abnormal
bambulab_sdcard_status_info{printer_name="$printer", status="abnormal"} == 1
```

---

## Migration Notes

- `bambulab_mc_print_stage_state{stage}` removed → use `bambulab_print_stage_info{stage}` + `bambulab_stg_cur`
- `bambulab_ams_status` → `bambulab_ams_status_id`
- `bambulab_ams_rfid_status` → `bambulab_ams_rfid_status_id`
- `bambulab_ams_slot_tray_type_info` + `bambulab_ams_slot_tray_color_info` → `bambulab_ams_slot_tray_info`
