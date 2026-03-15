from __future__ import annotations

import math

from prometheus_client import CollectorRegistry, Gauge

from bambulab_metrics_exporter.models import PrinterSnapshot


class ExporterMetrics:
    def __init__(self, printer_name: str, serial: str) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self._base_labels = {
            "printer_name": printer_name,
            "serial": serial,
        }

        label_names = list(self._base_labels.keys())
        self.printer_up = Gauge("bambulab_printer_up", "1 if latest poll had a valid payload", label_names, registry=self.registry)
        self.printer_connected = Gauge("bambulab_printer_connected", "1 if MQTT connection is up", label_names, registry=self.registry)
        self.print_progress_percent = Gauge("bambulab_print_progress_percent", "Print progress percent", label_names, registry=self.registry)
        self.print_remaining_seconds = Gauge("bambulab_print_remaining_seconds", "Estimated seconds remaining", label_names, registry=self.registry)
        self.print_layer_current = Gauge("bambulab_print_layer_current", "Current print layer", label_names, registry=self.registry)
        self.print_layer_total = Gauge("bambulab_print_layer_total", "Total print layers", label_names, registry=self.registry)
        self.print_layer_progress_percent = Gauge("bambulab_print_layer_progress_percent", "Layer-based progress percent", label_names, registry=self.registry)
        self.nozzle_temp = Gauge("bambulab_nozzle_temperature_celsius", "Nozzle temperature", label_names, registry=self.registry)
        self.nozzle_target_temp = Gauge("bambulab_nozzle_target_temperature_celsius", "Nozzle target temperature", label_names, registry=self.registry)
        self.nozzle_diameter = Gauge("bambulab_nozzle_diameter", "Nozzle diameter from MQTT", label_names, registry=self.registry)
        self.bed_temp = Gauge("bambulab_bed_temperature_celsius", "Bed temperature", label_names, registry=self.registry)
        self.bed_target_temp = Gauge("bambulab_bed_target_temperature_celsius", "Bed target temperature", label_names, registry=self.registry)
        self.chamber_temp = Gauge("bambulab_chamber_temperature_celsius", "Chamber temperature", label_names, registry=self.registry)
        self.fan_speed = Gauge("bambulab_fan_speed_percent", "Fan speed percent", label_names, registry=self.registry)
        self.fan_gear = Gauge("bambulab_fan_gear", "Raw fan_gear value from MQTT", label_names, registry=self.registry)
        self.fan_big_1_speed = Gauge("bambulab_fan_big_1_speed_percent", "Big fan 1 speed percent", label_names, registry=self.registry)
        self.fan_big_2_speed = Gauge("bambulab_fan_big_2_speed_percent", "Big fan 2 speed percent", label_names, registry=self.registry)
        self.fan_cooling_speed = Gauge("bambulab_fan_cooling_speed_percent", "Cooling fan speed percent", label_names, registry=self.registry)
        self.fan_heatbreak_speed = Gauge("bambulab_fan_heatbreak_speed_percent", "Heatbreak fan speed percent", label_names, registry=self.registry)
        self.printer_error = Gauge("bambulab_printer_error", "1 when printer reported an error code", label_names, registry=self.registry)
        self.print_error_code_legacy = Gauge("bambulab_print_error_code", "Raw print_error value", label_names, registry=self.registry)
        self.print_error_explicit = Gauge("bambulab_print_error", "Raw print_error value from MQTT", label_names, registry=self.registry)
        self.ap_err_code = Gauge("bambulab_ap_error_code", "Raw ap_err value", label_names, registry=self.registry)
        self.mc_stage = Gauge("bambulab_mc_stage", "Machine stage numeric code", label_names, registry=self.registry)
        self.mc_print_sub_stage = Gauge("bambulab_mc_print_sub_stage", "Machine print sub-stage numeric code", label_names, registry=self.registry)
        self.print_real_action = Gauge("bambulab_print_real_action", "Print real action numeric code", label_names, registry=self.registry)
        self.print_gcode_action = Gauge("bambulab_print_gcode_action", "Print gcode action numeric code", label_names, registry=self.registry)
        self.wifi_signal = Gauge("bambulab_wifi_signal", "WiFi signal value from printer telemetry", label_names, registry=self.registry)
        self.online_ahb = Gauge("bambulab_online_ahb", "AHB online flag", label_names, registry=self.registry)
        self.online_ext = Gauge("bambulab_online_ext", "External online flag", label_names, registry=self.registry)
        self.ams_status = Gauge("bambulab_ams_status", "AMS status numeric code", label_names, registry=self.registry)
        self.ams_rfid_status = Gauge("bambulab_ams_rfid_status", "AMS RFID status numeric code", label_names, registry=self.registry)
        self.queue_total = Gauge("bambulab_queue_total", "Total queued jobs", label_names, registry=self.registry)
        self.queue_est = Gauge("bambulab_queue_estimated_seconds", "Estimated queue time seconds", label_names, registry=self.registry)
        self.queue_number = Gauge("bambulab_queue_number", "Queue number", label_names, registry=self.registry)
        self.queue_status = Gauge("bambulab_queue_status", "Queue status numeric code", label_names, registry=self.registry)
        self.queue_position = Gauge("bambulab_queue_position", "Current queue position", label_names, registry=self.registry)
        self.spd_lvl = Gauge("bambulab_spd_lvl", "Printer speed level (1=Silent,2=Standard,3=Sport,4=Ludicrous)", label_names, registry=self.registry)
        self.spd_mag = Gauge("bambulab_spd_mag", "Printer speed percentage relative to standard", label_names, registry=self.registry)
        self.printer_error_code = Gauge("bambulab_printer_error_code", "Raw printer error code", label_names, registry=self.registry)
        self.chamber_light_on = Gauge("bambulab_chamber_light_on", "Chamber light on/off", label_names, registry=self.registry)
        self.work_light_on = Gauge("bambulab_work_light_on", "Work light on/off", label_names, registry=self.registry)
        self.xcam_feature_enabled = Gauge("bambulab_xcam_feature_enabled", "XCam feature enabled flags", [*label_names, "feature"], registry=self.registry)
        self.gcode_state = Gauge("bambulab_printer_gcode_state", "Current gcode state encoded as one-hot labels", [*label_names, "state"], registry=self.registry)
        self.mc_print_stage_state = Gauge("bambulab_mc_print_stage_state", "Current machine print stage as one-hot labels", [*label_names, "stage"], registry=self.registry)
        self.spd_lvl_state = Gauge("bambulab_spd_lvl_state", "Current speed level as one-hot labels", [*label_names, "mode"], registry=self.registry)
        self.subtask_name_info = Gauge(
            "bambulab_subtask_name_info",
            "Current print subtask name as labeled info metric",
            [*label_names, "subtask_name"],
            registry=self.registry,
        )
        self.fail_reason_info = Gauge(
            "bambulab_fail_reason_info",
            "Current print fail reason as labeled info metric",
            [*label_names, "fail_reason"],
            registry=self.registry,
        )
        self.printer_model_info = Gauge(
            "bambulab_printer_model_info",
            "Printer model type as labeled info metric",
            [*label_names, "model"],
            registry=self.registry,
        )

        self.ams_slot_active = Gauge(
            "bambulab_ams_slot_active",
            "AMS slot active flag",
            [*label_names, "ams_id", "slot_id"],
            registry=self.registry,
        )
        self.ams_slot_remaining_percent = Gauge(
            "bambulab_ams_slot_remaining_percent",
            "AMS slot remaining filament percent",
            [*label_names, "ams_id", "slot_id"],
            registry=self.registry,
        )
        self.ams_slot_tray_type = Gauge(
            "bambulab_ams_slot_tray_type_info",
            "AMS slot filament type as labeled one-hot info metric",
            [*label_names, "ams_id", "slot_id", "tray_type"],
            registry=self.registry,
        )
        self.ams_slot_tray_color = Gauge(
            "bambulab_ams_slot_tray_color_info",
            "AMS slot filament color as labeled one-hot info metric",
            [*label_names, "ams_id", "slot_id", "tray_color"],
            registry=self.registry,
        )
        self.ams_unit_humidity = Gauge(
            "bambulab_ams_unit_humidity",
            "AMS unit humidity",
            [*label_names, "ams_id"],
            registry=self.registry,
        )
        self.ams_unit_humidity_index = Gauge(
            "bambulab_ams_unit_humidity_index",
            "AMS unit humidity index",
            [*label_names, "ams_id"],
            registry=self.registry,
        )
        self.ams_unit_temperature_celsius = Gauge(
            "bambulab_ams_unit_temperature_celsius",
            "AMS unit temperature",
            [*label_names, "ams_id"],
            registry=self.registry,
        )

        # Phase 1: New metrics
        self.usage_hours = Gauge("bambulab_usage_hours_total", "Total printer usage hours", label_names, registry=self.registry)
        self.sdcard_status_info = Gauge(
            "bambulab_sdcard_status_info",
            "SD card status as labeled info metric",
            [*label_names, "status"],
            registry=self.registry,
        )
        self.home_flag_state = Gauge(
            "bambulab_home_flag_state",
            "Decoded home_flag bit states (1=true,0=false)",
            [*label_names, "flag"],
            registry=self.registry,
        )
        self.stat_flag_state = Gauge(
            "bambulab_stat_flag_state",
            "Decoded stat bit states (1=true,0=false)",
            [*label_names, "flag"],
            registry=self.registry,
        )
        self.door_open = Gauge("bambulab_door_open", "1 if printer door is open", label_names, registry=self.registry)
        self.wired_network = Gauge("bambulab_wired_network", "1 if wired network flag is set", label_names, registry=self.registry)
        self.camera_recording = Gauge("bambulab_camera_recording", "1 if camera recording flag is set", label_names, registry=self.registry)
        self.ams_auto_switch = Gauge("bambulab_ams_auto_switch", "1 if AMS auto switch flag is set", label_names, registry=self.registry)
        self.filament_tangle_detected = Gauge("bambulab_filament_tangle_detected", "1 if filament tangle detected flag is set", label_names, registry=self.registry)
        self.filament_tangle_detect_supported = Gauge("bambulab_filament_tangle_detect_supported", "1 if filament tangle detect supported flag is set", label_names, registry=self.registry)
        self.filament_loaded = Gauge("bambulab_filament_loaded", "1 if filament is loaded in extruder", label_names, registry=self.registry)
        self.timelapse_enabled = Gauge("bambulab_timelapse_enabled", "1 if timelapse recording is enabled", label_names, registry=self.registry)

        # Phase 3: Stage info
        self.stg_cur = Gauge("bambulab_stg_cur", "Current print stage numeric ID", label_names, registry=self.registry)
        self.print_stage_info = Gauge(
            "bambulab_print_stage_info",
            "Current print stage as labeled info metric",
            [*label_names, "stage"],
            registry=self.registry,
        )

        self.scrape_duration_seconds = Gauge(
            "bambulab_exporter_scrape_duration_seconds",
            "Duration of last polling cycle",
            label_names,
            registry=self.registry,
        )
        self.scrape_success = Gauge(
            "bambulab_exporter_scrape_success",
            "1 when last polling cycle succeeded",
            label_names,
            registry=self.registry,
        )
        self.last_success_unixtime = Gauge(
            "bambulab_exporter_last_success_unixtime",
            "Unix timestamp of last successful cycle",
            label_names,
            registry=self.registry,
        )

    def _labels(self) -> dict[str, str]:
        return self._base_labels

    def update_from_snapshot(self, snapshot: PrinterSnapshot) -> None:
        labels = self._labels()
        has_payload = 1.0 if snapshot.raw else 0.0
        self.printer_up.labels(**labels).set(has_payload)
        self.printer_connected.labels(**labels).set(1.0 if snapshot.connected else 0.0)

        self._set_optional(self.print_progress_percent, snapshot.progress_percent)
        self._set_optional(self.print_remaining_seconds, snapshot.remaining_seconds)
        self._set_optional(self.print_layer_current, snapshot.layer_current)
        self._set_optional(self.print_layer_total, snapshot.layer_total)
        self._set_optional(self.print_layer_progress_percent, snapshot.layer_progress_percent)
        self._set_optional(self.nozzle_temp, snapshot.nozzle_temp)
        self._set_optional(self.nozzle_target_temp, snapshot.nozzle_target_temp)
        self._set_optional(self.nozzle_diameter, snapshot.nozzle_diameter)
        self._set_optional(self.bed_temp, snapshot.bed_temp)
        self._set_optional(self.bed_target_temp, snapshot.bed_target_temp)
        self._set_optional(self.chamber_temp, snapshot.chamber_temp)
        self._set_optional(self.fan_speed, snapshot.fan_gear)
        self._set_optional(self.fan_gear, snapshot.fan_gear_raw)
        self._set_optional(self.fan_big_1_speed, snapshot.fan_big_1_percent)
        self._set_optional(self.fan_big_2_speed, snapshot.fan_big_2_percent)
        self._set_optional(self.fan_cooling_speed, snapshot.fan_cooling_percent)
        self._set_optional(self.fan_heatbreak_speed, snapshot.fan_heatbreak_percent)
        self._set_optional(self.mc_stage, snapshot.mc_stage)
        self._set_optional(self.mc_print_sub_stage, snapshot.mc_print_sub_stage)
        self._set_optional(self.print_real_action, snapshot.print_real_action)
        self._set_optional(self.print_gcode_action, snapshot.print_gcode_action)
        self._set_optional(self.wifi_signal, snapshot.wifi_signal)
        self._set_optional(self.online_ahb, snapshot.online_ahb)
        self._set_optional(self.online_ext, snapshot.online_ext)
        self._set_optional(self.ams_status, snapshot.ams_status)
        self._set_optional(self.ams_rfid_status, snapshot.ams_rfid_status)
        self._set_optional(self.queue_total, snapshot.queue_total)
        self._set_optional(self.queue_est, snapshot.queue_est)
        self._set_optional(self.queue_number, snapshot.queue_number)
        self._set_optional(self.queue_status, snapshot.queue_status)
        self._set_optional(self.queue_position, snapshot.queue_position)
        self._set_optional(self.spd_lvl, snapshot.spd_lvl)
        self._set_optional(self.spd_mag, snapshot.spd_mag)
        self._set_optional(self.print_error_code_legacy, snapshot.print_error)
        self._set_optional(self.print_error_explicit, snapshot.print_error)
        self._set_optional(self.ap_err_code, snapshot.ap_err)

        chamber_light = None
        work_light = None
        for light in snapshot.lights_report:
            node = str(light.get("node", "")).lower()
            mode = str(light.get("mode", "")).lower()
            light_state = 1.0 if mode in {"on", "flashing", "blink", "blinking"} else 0.0 if mode in {"off", "auto"} else float("nan")
            if node == "chamber_light":
                chamber_light = light_state
            if node == "work_light":
                work_light = light_state
        self._set_optional(self.chamber_light_on, chamber_light)
        self._set_optional(self.work_light_on, work_light)

        self.xcam_feature_enabled.clear()
        for feature, enabled in snapshot.xcam_flags.items():
            self.xcam_feature_enabled.labels(**labels, feature=feature).set(enabled)

        error_code = snapshot.print_error_code
        self.printer_error.labels(**labels).set(1.0 if error_code and error_code != 0 else 0.0)
        self.printer_error_code.labels(**labels).set(float(error_code or 0))

        known_states = {
            "IDLE", "INIT", "RUNNING", "PAUSE", "FINISH", "FAILED", "PREPARE", "SLICING", "OFFLINE", "UNKNOWN"
        }
        current = snapshot.gcode_state if snapshot.gcode_state in known_states else "UNKNOWN"
        for state in known_states:
            self.gcode_state.labels(**labels, state=state).set(1.0 if state == current else 0.0)

        known_print_stages = {
            "AUTO_BED_LEVELING", "HEATBED_PREHEATING", "CHANGING_FILAMENT", "M400_PAUSE", "PAUSED_DUE_TO_FILAMENT_RUNOUT", "HEATING_HOTEND", "CALIBRATING_EXTRUSION", "SCANNING_BED_SURFACE", "INSPECTING_FIRST_LAYER", "IDENTIFYING_BUILD_PLATE_TYPE", "HOMING_TOOLHEAD", "CLEANING_NOZZLE_TIP", "CHECKING_EXTRUDER_TEMPERATURE", "PRINTING", "MOTOR_NOISE_CALIBRATION", "UNKNOWN"
        }
        stage_current = snapshot.mc_print_stage_name or "UNKNOWN"
        if stage_current not in known_print_stages:
            stage_current = "UNKNOWN"
        for stage in known_print_stages:
            self.mc_print_stage_state.labels(**labels, stage=stage).set(1.0 if stage == stage_current else 0.0)

        speed_modes = {1.0: "SILENT", 2.0: "STANDARD", 3.0: "SPORT", 4.0: "LUDICROUS"}
        current_speed_mode = "UNKNOWN"
        if snapshot.spd_lvl is not None:
            current_speed_mode = speed_modes.get(snapshot.spd_lvl, "UNKNOWN")

        for mode in {"SILENT", "STANDARD", "SPORT", "LUDICROUS", "UNKNOWN"}:
            self.spd_lvl_state.labels(**labels, mode=mode).set(1.0 if mode == current_speed_mode else 0.0)

        self.subtask_name_info.clear()
        if snapshot.subtask_name:
            self.subtask_name_info.labels(**labels, subtask_name=snapshot.subtask_name).set(1.0)

        self.fail_reason_info.clear()
        if snapshot.fail_reason:
            self.fail_reason_info.labels(**labels, fail_reason=snapshot.fail_reason).set(1.0)

        self.printer_model_info.clear()
        if snapshot.model_name:
            self.printer_model_info.labels(**labels, model=snapshot.model_name).set(1.0)

        # Phase 1 metrics
        self._set_optional(self.usage_hours, snapshot.usage_hours)
        self._set_optional(self.door_open, snapshot.door_open)
        self._set_optional(self.wired_network, self._flag_to_float(snapshot.home_flags.get("wired_network")))
        self._set_optional(self.camera_recording, self._flag_to_float(snapshot.home_flags.get("camera_recording")))
        self._set_optional(self.ams_auto_switch, self._flag_to_float(snapshot.home_flags.get("ams_auto_switch")))
        self._set_optional(self.filament_tangle_detected, self._flag_to_float(snapshot.home_flags.get("filament_tangle_detected")))
        self._set_optional(self.filament_tangle_detect_supported, self._flag_to_float(snapshot.home_flags.get("filament_tangle_detect_supported")))
        self._set_optional(self.filament_loaded, snapshot.filament_loaded)
        self._set_optional(self.timelapse_enabled, snapshot.timelapse_enabled)

        self.sdcard_status_info.clear()
        if snapshot.sdcard_status:
            self.sdcard_status_info.labels(**labels, status=snapshot.sdcard_status).set(1.0)

        self.home_flag_state.clear()
        for flag, flag_state in snapshot.home_flags.items():
            if flag_state is not None:
                self.home_flag_state.labels(**labels, flag=flag).set(1.0 if flag_state else 0.0)

        self.stat_flag_state.clear()
        for flag, flag_state in snapshot.stat_flags.items():
            if flag_state is not None:
                self.stat_flag_state.labels(**labels, flag=flag).set(1.0 if flag_state else 0.0)

        # Phase 3: Stage info
        self._set_optional(self.stg_cur, float(snapshot.stg_cur) if snapshot.stg_cur is not None else None)
        self.print_stage_info.clear()
        if snapshot.stg_cur_name:
            self.print_stage_info.labels(**labels, stage=snapshot.stg_cur_name).set(1.0)

        self._clear_ams(labels)
        for ams in snapshot.ams_units:
            ams_id = str(ams.get("id", "0"))

            # Strict MQTT mapping:
            # - humidity_index metric follows MQTT "humidity" (index 1..5)
            # - humidity metric follows MQTT "humidity_raw" (raw % 1..100)
            humidity_raw = ams.get("humidity_raw")
            if isinstance(humidity_raw, (int, float, str)):
                try:
                    humidity_raw_value = float(humidity_raw)
                    if 1.0 <= humidity_raw_value <= 100.0:
                        self.ams_unit_humidity.labels(**labels, ams_id=ams_id).set(humidity_raw_value)
                except (TypeError, ValueError):
                    pass

            humidity_index = self._extract_ams_humidity_index(ams)
            if humidity_index is not None and 1.0 <= humidity_index <= 5.0:
                self.ams_unit_humidity_index.labels(**labels, ams_id=ams_id).set(humidity_index)

            temp = ams.get("temp")
            if isinstance(temp, (int, float, str)):
                try:
                    self.ams_unit_temperature_celsius.labels(**labels, ams_id=ams_id).set(float(temp))
                except (TypeError, ValueError):
                    pass
            raw_trays = ams.get("tray")
            trays = [t for t in raw_trays if isinstance(t, dict)] if isinstance(raw_trays, list) else []
            active_id = str(ams.get("tray_now", "-1"))
            for tray in trays:
                tray_id = str(tray.get("id", "-1"))
                self.ams_slot_active.labels(**labels, ams_id=ams_id, slot_id=tray_id).set(
                    1.0 if tray_id == active_id else 0.0
                )
                remain = tray.get("remain")
                if isinstance(remain, (int, float, str)):
                    try:
                        self.ams_slot_remaining_percent.labels(
                            **labels, ams_id=ams_id, slot_id=tray_id
                        ).set(float(remain))
                    except (TypeError, ValueError):
                        pass

                tray_type_raw = tray.get("tray_type", tray.get("ctype", ""))
                tray_type = str(tray_type_raw).strip() or "unknown"
                self.ams_slot_tray_type.labels(
                    **labels, ams_id=ams_id, slot_id=tray_id, tray_type=tray_type
                ).set(1.0)

                tray_color = str(tray.get("tray_color", "")).strip().upper() or "unknown"
                self.ams_slot_tray_color.labels(
                    **labels, ams_id=ams_id, slot_id=tray_id, tray_color=tray_color
                ).set(1.0)


    @staticmethod
    def _flag_to_float(value: bool | None) -> float | None:
        if value is None:
            return None
        return 1.0 if value else 0.0

    def _set_optional(self, gauge: Gauge, value: float | None) -> None:
        labels = self._labels()
        if value is None:
            gauge.labels(**labels).set(float("nan"))
            return
        gauge.labels(**labels).set(value)

    @staticmethod
    def _extract_ams_humidity_index(ams: dict[str, object]) -> float | None:
        raw_value = ams.get("humidity")
        if not isinstance(raw_value, (int, float, str)):
            return None
        try:
            parsed = float(raw_value)
        except (TypeError, ValueError):
            return None
        if math.isfinite(parsed):
            return parsed
        return None

    def _clear_ams(self, labels: dict[str, str]) -> None:
        self.ams_slot_active.clear()
        self.ams_slot_remaining_percent.clear()
        self.ams_slot_tray_type.clear()
        self.ams_slot_tray_color.clear()
        self.ams_unit_humidity.clear()
        self.ams_unit_humidity_index.clear()
        self.ams_unit_temperature_celsius.clear()

    def mark_scrape(self, duration_seconds: float, success: bool, now_ts: float | None = None) -> None:
        labels = self._labels()
        self.scrape_duration_seconds.labels(**labels).set(duration_seconds)
        self.scrape_success.labels(**labels).set(1.0 if success else 0.0)
        if success and now_ts is not None:
            self.last_success_unixtime.labels(**labels).set(now_ts)
