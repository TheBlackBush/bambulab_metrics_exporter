# Metrics Reference

All metrics include stable labels: `printer_name` and `serial`.

---

## Supported models

Detection is not hardware validation: only the X1C is validated on real hardware (an H2D was checked while idle and while printing). Metrics
for hardware a model does not have report NaN.

| Model | Serial prefix | Chamber temp | Chamber heater | Door sensor | Lid | Aux / chamber fan | Extruders | Hotend rack | Laser / cutter |
|-------|---------------|--------------|----------------|-------------|-----|-------------------|-----------|-------------|----------------|
| X1 / X1 Carbon | `00W` / `00M` | yes | no | home_flag | no | yes | 1 | no | no |
| X1E | `03W` | yes | yes | home_flag | no | yes | 1 | no | no |
| X2D | `20P` | yes | yes | stat | no | yes | 2 | no | no |
| P1P / P1S | `01S` / `01P` | no | no | no | no | yes | 1 | no | no |
| P2S | `22E` | yes | no | stat | no | yes | 1 | no | no |
| A1 / A1 mini | `039` / `030` | no | no | no | no | no | 1 | no | no |
| A2L | `26A` | no | no | no | no | no | 1 | no | no |
| H2D / H2D Pro | `094` / `239` | yes | yes | stat | yes | yes | 2 | no | yes |
| H2S | `093` | yes | yes | stat | yes | yes | 1 | no | yes |
| H2C | `31B` (early units `094`) | yes | yes | stat | yes | yes | 2 | yes | yes |
| R1 (laser) | `35F` | no | no | auto | no | no | none | no | yes |

Unknown models export whatever the payload carries.

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
| `bambulab_print_stage_info{stage}` | Info Gauge | Current stage name (stages 0-84 and 88; unlisted codes are `unknown_<n>`). Reports `idle` after a cancelled (`FAILED`) print |
| `bambulab_job_state_info{state}` | Info Gauge | Job phase from `job.job_state`, finer than the gcode state: `idle`, `slicing`, `prepare`, `starting`, `running`, `pause`, `pausing`, `resuming`, `finish`, `failed`, `finishing`, `stopping`, else `unknown`. Recent firmware only (seen on H2D 01.04.20 and X2D) |
| `bambulab_print_stage_countdown_seconds` | Gauge | Seconds left in the current stage (`stg_cd`), for example thermal preconditioning; 0 when no countdown runs. Recent firmware only (seen on H2D, X2D, P2S); `NaN` when not sent or negative |
| `bambulab_print_prepare_percent` | Gauge | Download progress of the job file before a print starts (`gcode_file_prepare_percent`, 0-100) |
| `bambulab_print_type_info{type}` | Info Gauge | Job source (`print_type`): `cloud`, `local`, `idle`, `system`, `unknown` |
| `bambulab_print_skipped_objects` | Gauge | Number of objects skipped in the current print (length of `s_obj`; object IDs are never labels) |
| `bambulab_mc_stage` | Gauge | Raw `mc_stage` code |
| `bambulab_mc_print_sub_stage` | Gauge | Raw `mc_print_sub_stage` code |
| `bambulab_print_real_action` | Gauge | Raw `print_real_action` code |
| `bambulab_print_gcode_action` | Gauge | Raw `print_gcode_action` code |
| `bambulab_firmware_update_available` | Gauge | 1 when the printer offers a firmware update (`upgrade_state.new_version_state` 1), 0 when up to date (2), NaN when unknown (0 or absent) |
| `bambulab_firmware_upgrade_status_info{status}` | Info Gauge | Firmware upgrade state (`upgrade_state.status`): `idle`, `upgrade_request`, `downloading`, `download_fail`, `flash_fail`, `upgrade_fail`, `upgrade_success`, or `unknown` for any other value. Omitted when absent |
| `bambulab_module_firmware_info{module,version}` | Info Gauge | Firmware version of each module from `get_version` (`module="ota"` is the printer firmware; also `mc`, `th`, AMS units such as `n3f/0`). Absent when `BAMBULAB_REQUEST_PUSHALL=false` |
| `bambulab_printer_model_info{model}` | Info Gauge | Detected printer model |

---

## Temperatures

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_nozzle_temperature_celsius` | Gauge | Current nozzle temperature. On dual-nozzle printers this is extruder 0, which can be idle during a print; use bambulab_active_nozzle_temperature_celsius. |
| `bambulab_nozzle_target_temperature_celsius` | Gauge | Target nozzle temperature |
| `bambulab_active_nozzle_temperature_celsius` | Gauge | Temperature of the nozzle in use (the active extruder); same as the nozzle temperature on single-nozzle printers |
| `bambulab_nozzle_diameter` | Gauge | Nozzle diameter from telemetry |
| `bambulab_bed_temperature_celsius` | Gauge | Current bed temperature |
| `bambulab_bed_target_temperature_celsius` | Gauge | Target bed temperature |
| `bambulab_chamber_temperature_celsius` | Gauge | Chamber temperature (`device.ctc` on new firmware, unpacked; `chamber_temper` on older firmware). NaN on models without a chamber sensor (A1, A1 mini, A2L, P1P, P1S) |
| `bambulab_chamber_target_temperature_celsius` | Gauge | Chamber heater target (0 while the heater is off). Only on models with a chamber heater (X1E, X2D, H2D, H2D Pro, H2S, H2C); NaN otherwise |
| `bambulab_chamber_heater_state` | Gauge | Chamber heater state: 0 idle, 1 heating, 2 holding, 3 cooling. NaN on models without a chamber heater |

---

## Fans

Fan values: raw levels 0–15 → nearest-10 percent normalization.

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_fan_big_1_speed_percent` | Gauge | Big fan 1 (aux) speed percent. NaN on models without an aux fan (A1, A1 mini, A2L) |
| `bambulab_fan_big_2_speed_percent` | Gauge | Big fan 2 (chamber) speed percent. NaN on models without a chamber fan (A1, A1 mini, A2L) |
| `bambulab_fan_cooling_speed_percent` | Gauge | Cooling fan speed percent |
| `bambulab_fan_heatbreak_speed_percent` | Gauge | Heatbreak fan speed percent |
| `bambulab_fan_secondary_aux_speed_percent` | Gauge | Secondary auxiliary fan speed percent (airduct fan 10, part id 160; X2D). NaN when the printer has no such fan |
| `bambulab_airduct_mode_info{mode}` | Info Gauge | Airduct mode (`device.airduct.modeCur`): `cooling`, `heating`, `exhaust`, `full_cooling`, `init`, `unknown`. P2S, X2D and the H2 family; omitted on printers without an airduct mode |
| `bambulab_airduct_fan_speed_percent{fan}` | Gauge | Airduct fan speed by fan (part id >> 4): `heatbreak`, `part_cooling`, `aux`, `chamber`, `heatbreak_2`, `mc_board`, `inner_loop`, `aux_2`. Left/right placement of `aux` and `aux_2` differs per model |

---

## Errors

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_printer_error` | Gauge | 1 when printer error code is non-zero |
| `bambulab_printer_error_code` | Gauge | Raw printer error code |
| `bambulab_print_error` | Gauge | Raw print_error value from MQTT |
| `bambulab_print_error_code` | Gauge | Legacy alias of `bambulab_print_error` (same value), kept for existing dashboards |
| `bambulab_ap_error_code` | Gauge | Raw ap_err value from MQTT |
| `bambulab_hms_active_errors{severity}` | Gauge | Active HMS (health management) errors by severity: `fatal`, `serious`, `common`, `info`, `unknown`. All values present (0 when none); omitted when the printer sends no `hms` list |
| `bambulab_hms_active_errors_by_module{module}` | Gauge | Active HMS errors by module: `mc`, `mainboard`, `ams`, `toolhead`, `xcam`, `other`. `module` is the part of the printer that raised the error, not its topic (an MQTT error raised by the mainboard counts as `mainboard`) |

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
| `bambulab_ams_unit_humidity{ams_id}` | Gauge | AMS humidity raw value. Not exported for AMS Lite (no sensor) |
| `bambulab_ams_unit_humidity_index{ams_id}` | Gauge | AMS humidity index (1–5). Not exported for AMS Lite |
| `bambulab_ams_unit_temperature_celsius{ams_id}` | Gauge | AMS temperature. Not exported for AMS Lite |

### Slots

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_ams_slot_active{ams_id,slot_id}` | Gauge | 1 for the slot loaded in the active extruder (per-extruder `snow` on new firmware, `tray_now` on older firmware; AMS HT units use ids 128+) |
| `bambulab_ams_slot_present{ams_id,slot_id}` | Gauge | 1 when a spool sits in the slot, with or without an RFID tag; 0 when the slot is empty (`ams.tray_exist_bits`). AMS, AMS lite and AMS 2 Pro (ids 0-3) and AMS HT (ids 128-135) only; units with other ids, such as the A2L's, are left out |
| `bambulab_ams_slot_remaining_percent{ams_id,slot_id}` | Gauge | Remaining filament %. NaN when unknown (the printer reports -1 for spools without an estimate) |
| `bambulab_ams_slot_tray_info{ams_id,slot_id,tray_type,tray_color}` | Info Gauge | Filament type and color |

### Gen2 Drying (only when `ams_info` present)

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_ams_heater_state_info{...,state}` | Info Gauge | AMS dryer state: `off`, `self_check`, `drying`, `cooling`, `stopped`, `error`, `thermal_runaway`, `test_mode` (`unknown_<n>` otherwise); only for units with a dryer (AMS 2 Pro, AMS HT) |
| `bambulab_ams_dry_fan_status{...,fan_id}` | Gauge | Gen2 AMS drying fan status |
| `bambulab_ams_dry_sub_status_info{...,state}` | Info Gauge | AMS drying sub-status: `none`, `heating`, `dehumidifying` |
| `bambulab_ams_drying_remaining_seconds{ams_id}` | Gauge | Remaining drying time (`dry_time`, minutes in the payload), 0 when not drying. AMS 2 Pro and AMS HT only |
| `bambulab_ams_drying_target_temperature_celsius{ams_id}` | Gauge | Configured drying temperature (`dry_setting.dry_temperature`). Omitted when unset or on older firmware |
| `bambulab_ams_drying_duration_seconds{ams_id}` | Gauge | Configured drying duration (`dry_setting.dry_duration`, hours in the payload). Omitted when unset |
| `bambulab_ams_drying_blocked_reason_info{ams_id,reason}` | Info Gauge | Why this AMS cannot start drying now (`dry_sf_reason`, a list of codes), one series per reason with value 1. `reason` is one of `task_occupied`, `insufficient_power`, `ams_busy`, `consumable_at_ams_outlet`, `initiating_ams_drying`, `not_supported_in_2d_mode`, `drying_in_progress`, `upgrading`, `insufficient_power_need_plugin_power`, `closing_ams_drying`, `filament_at_ams_outlet_manual_unload`, `unknown`. `drying_in_progress` only means a drying run is active. Omitted when no reason is reported |

---

## External Spool

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_external_spool_active` | Gauge | 1 when the external spool feeds the active extruder |
| `bambulab_external_spool_info{...}` | Info Gauge | External spool metadata; empty virtual slots are omitted |

---

## Extruders (H2D, H2D Pro, H2C, X2D, and new firmware on other models)

The `bambulab_filament_change_step_info`, `bambulab_extruder_buffer_filament_present`, `bambulab_extruder_nozzle_present` and `bambulab_extruder_extrusion_direction_info` metrics below come from the per-extruder block, which the A1, P1P and older X1 firmware do not send.

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_active_extruder_index` | Gauge | Active extruder index |
| `bambulab_extruder_temperature_celsius{extruder_id}` | Gauge | Per-extruder current temperature |
| `bambulab_extruder_target_temperature_celsius{extruder_id}` | Gauge | Per-extruder target temperature |
| `bambulab_extruder_nozzle_info{extruder_id,nozzle_type,nozzle_diameter}` | Info Gauge | Per-extruder nozzle metadata |
| `bambulab_active_nozzle_info{nozzle_type,nozzle_diameter}` | Info Gauge | Active nozzle metadata (also from top-level `nozzle_type` on A1, P1 and older X1 firmware) |
| `bambulab_extruder_loaded_slot_info{extruder_id,ams_id,slot_id}` | Info Gauge | Filament loaded in each extruder (`device.extruder.info[].snow`): AMS unit and slot, or `external`. Extruders with nothing loaded are omitted |
| `bambulab_filament_change_step_info{extruder_id,step}` | Info Gauge | Filament change step per extruder (`device.extruder.info[].stat` bits 0-7): `idle`, `pause`, `heat_nozzle`, `cut_filament`, `pull_current_filament`, `push_new_filament`, `grab_new_filament`, `purge_old_filament`, `check_position`, `switch_extruder`, `switch_hotend`, `ams_filament_cooling`, `push_switcher_filament`, `pull_switcher_filament`, `switcher_switch`, `batch_pull_filament`, `nesting_print_tool`, `purge_filament`, else `unknown` |
| `bambulab_extruder_buffer_filament_present{extruder_id}` | Gauge | 1 when filament is in the extruder's buffer (`info` bit 2). Bambu Studio parses this bit but does not use it, so treat it as informational |
| `bambulab_extruder_nozzle_present{extruder_id}` | Gauge | 1 when a nozzle is fitted (`info` bit 3). Some models do not support nozzle detection and may always report 1 |
| `bambulab_extruder_extrusion_direction_info{extruder_id,direction}` | Info Gauge | Filament feed or retract motion as reported by the firmware: `idle`, `extruding` or `retracting` (`info` bits 11-12), else `unknown`. Ordinary printing reads `idle` on the H2D, H2S, P2S and X2D samples |
| `bambulab_nozzle_wear_ratio{extruder_id}` | Gauge | Wear value of the nozzle mounted on each extruder (`device.nozzle.info[].wear`, passed through unscaled; the unit is not confirmed) |
| `bambulab_nozzle_print_time_seconds{extruder_id}` | Gauge | Total print time of the mounted nozzle (`p_t`), for hotends that keep their own usage record. Bambu added this for the H2C hotend rack; Bambu support said it needs H2C firmware V01.02.00.00. H2D and X2D firmware also send the field, but report 0: on an H2D it stayed 0 through about 12 hours of printing. The metric shows whatever the printer reports, so 0 here usually means "not counted", not "unused" |

### Filament change steps

Values of the `step` label on `bambulab_filament_change_step_info`, with what each one means. Loading and unloading filament use the steps from `heat_nozzle` to `check_position`; the order and which steps run depend on the printer and the change. The steps after that cover extruder and hotend switches and the Filament Track Switch.

| `step` | Meaning |
|---|---|
| `idle` | Idle, no filament change running |
| `pause` | Paused |
| `heat_nozzle` | Heating the nozzle |
| `cut_filament` | Cutting the filament |
| `pull_current_filament` | Pulling back the current filament |
| `push_new_filament` | Pushing the new filament into the extruder |
| `grab_new_filament` | Grabbing the new filament |
| `purge_old_filament` | Purging the old filament |
| `check_position` | Checking the filament position |
| `switch_extruder` | Switching extruder |
| `switch_hotend` | Switching hotend |
| `ams_filament_cooling` | Waiting for the AMS to cool the filament |
| `push_switcher_filament` | Feeding the current filament at the Filament Track Switch |
| `pull_switcher_filament` | Pulling back the current filament at the Filament Track Switch |
| `switcher_switch` | Switching track at the Filament Track Switch |
| `batch_pull_filament` | Pulling back several filaments |
| `nesting_print_tool` | Tool change step; no description available |
| `purge_filament` | Purge step; no description available |
| `unknown` | A step code this exporter does not know yet |

---

## Hotend Rack

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_hotend_rack_holder_position_info{position}` | Info Gauge | Holder position |
| `bambulab_hotend_rack_holder_state_info{state}` | Info Gauge | Holder state |
| `bambulab_hotend_rack_slot_state_info{slot_id,state}` | Info Gauge | Slot state |
| `bambulab_hotend_rack_hotend_info{slot_id,nozzle_type,nozzle_diameter}` | Info Gauge | Slot nozzle metadata |
| `bambulab_hotend_rack_hotend_wear_ratio{slot_id}` | Gauge | Nozzle wear ratio |
| `bambulab_hotend_rack_hotend_print_time_seconds{slot_id}` | Gauge | Total print time of the hotend (`p_t`) |
| `bambulab_hotend_rack_hotend_max_temperature_celsius{slot_id}` | Gauge | Maximum temperature of the hotend (`tm`) |
| `bambulab_hotend_rack_hotend_runtime_minutes{slot_id}` | Gauge | **Deprecated**: carries `tm` (maximum temperature), not a runtime; removed in a future release |

---

## Connectivity & Flags

| Metric | Type | Description |
|--------|------|-------------|
| `bambulab_wifi_signal` | Gauge | Wi-Fi signal (dBm) |
| `bambulab_wired_network` | Gauge | Wired network detected |
| `bambulab_network_rtt{interface}` | Gauge | Raw `rtt` value the printer reports per network interface (`wlan`, `wired`). The unit and exact meaning are not confirmed, so the name carries no unit. On a real H2D it stayed near 215 while a connection to the cloud broker took about 210 ms, so it likely tracks the cloud connection in milliseconds. |
| `bambulab_network_retransmissions{interface}` | Gauge | `retrans` value the printer reports per network interface (`wlan`, `wired`). Reported by the printer; the meaning (counter or per interval) is not confirmed. On a real H2D it held steady during a print and was higher than a day earlier, so it likely is a running total. |
| `bambulab_door_open` | Gauge | Door open flag. NaN on models without a door sensor (A1, A1 mini, A2L, P1P, P1S) |
| `bambulab_lid_open` | Gauge | Top lid open flag (`stat` bit 24). H2 family only; NaN on other models |
| `bambulab_mqtt_signature_required` | Gauge | 1 when the printer only accepts signed MQTT commands (Developer Mode off; `fun` bit 0x20000000). Unsigned control commands from other tools are then rejected with HMS `0500_0500_0001_0007` |
| `bambulab_axis_homed{axis}` | Gauge | 1 when the axis (`x`, `y`, `z`) is homed (`home_flag` bits 0-2) |
| `bambulab_online_ahb` | Gauge | AMS hub online flag (`online.ahb`) |
| `bambulab_online_ext` | Gauge | Extension board online flag (`online.ext`) |
| `bambulab_sdcard_status_info{status}` | Info Gauge | SD card status. An H2D has no SD slot and reports its USB drive here: `present` means a USB drive is inserted and `absent` means none |
| `bambulab_chamber_light_on` | Gauge | Chamber light (1/0) |
| `bambulab_work_light_on` | Gauge | Work light (1/0). NaN when the printer reports `flashing`: printers send that constantly, also while the light is off |
| `bambulab_light_mode_info{light,mode}` | Info Gauge | Mode per light: `light` is `chamber_light`, `chamber_light2` (H2 family), `work_light` (omitted while reported `flashing`, see above) or `heatbed_light`; `mode` is `on`, `off`, `flashing` or `unknown` |
| `bambulab_tool_head_info{tool}` | Info Gauge | Mounted tool head (`device.ext_tool`): `none`, `laser_10w`, `laser_40w`, `cutter`, `cooling_fan`, `other`. |
| `bambulab_accessory_present{accessory}` | Gauge | 1/0 per accessory: `filament_buffer`, `external_exhaust_fan`, `fire_extinguisher`, `rotary_attachment`, `filament_switch`, `air_pump`. Detected from `get_version` product names, plus `fire_ext`/`fourth_axis` `connect_flag` and `aux` bit 29 (filament switch). Omitted when no source is available |
| `bambulab_toolhead_filament_present{extruder_id}` | Gauge | 1 when the extruder's filament sensor detects filament (`device.extruder.info[].info` bit 1; `hw_switch_state` on older firmware) |
| `bambulab_timelapse_storage_free_bytes{storage}` | Gauge | Free timelapse storage (`internal` or `external`, from `tl_*_free_kb`, KiB). Seen on X2D, and on H2D as `external` while a USB drive is inserted; omitted when unknown or not present |
| `bambulab_timelapse_storage_total_bytes{storage}` | Gauge | Total timelapse storage |
| `bambulab_camera_recording` | Gauge | Camera recording flag (camera setting `ipcam.ipcam_record`; home_flag bit 5 as fallback) |
| `bambulab_timelapse_enabled` | Gauge | Timelapse recording enabled (`ipcam.timelapse`) |
| `bambulab_xcam_feature_enabled{feature}` | Gauge | XCam feature flags |
| `bambulab_xcam_halt_print_sensitivity_info{level}` | Info Gauge | XCam halt-print sensitivity level (`low`/`medium`/`high`) |
| `bambulab_ams_auto_switch` | Gauge | AMS auto-switch flag |
| `bambulab_filament_tangle_detection_enabled` | Gauge | Tangle detection setting (home_flag bit 20); NaN unless the printer reports support (bit 19) |
| `bambulab_filament_tangle_detected` | Gauge | **Deprecated** alias of `bambulab_filament_tangle_detection_enabled`; it is the setting, not a detected tangle |
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
# Active serious or fatal HMS errors
sum by (printer_name) (bambulab_hms_active_errors{severity=~"fatal|serious"}) > 0

# Chamber still heating up
bambulab_chamber_target_temperature_celsius > 0
  and bambulab_chamber_temperature_celsius < bambulab_chamber_target_temperature_celsius - 2

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
