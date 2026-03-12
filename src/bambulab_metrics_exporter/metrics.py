from __future__ import annotations

from prometheus_client import CollectorRegistry, Gauge

from bambulab_metrics_exporter.models import PrinterSnapshot


class ExporterMetrics:
    def __init__(self, printer_name: str, site: str, location: str) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self._base_labels = {
            "printer_name": printer_name,
            "site": site,
            "location": location,
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
        self.bed_temp = Gauge("bambulab_bed_temperature_celsius", "Bed temperature", label_names, registry=self.registry)
        self.bed_target_temp = Gauge("bambulab_bed_target_temperature_celsius", "Bed target temperature", label_names, registry=self.registry)
        self.chamber_temp = Gauge("bambulab_chamber_temperature_celsius", "Chamber temperature", label_names, registry=self.registry)
        self.fan_speed = Gauge("bambulab_fan_speed_percent", "Fan speed percent", label_names, registry=self.registry)
        self.fan_big_1_speed = Gauge("bambulab_fan_big_1_speed_percent", "Big fan 1 speed percent", label_names, registry=self.registry)
        self.fan_big_2_speed = Gauge("bambulab_fan_big_2_speed_percent", "Big fan 2 speed percent", label_names, registry=self.registry)
        self.fan_cooling_speed = Gauge("bambulab_fan_cooling_speed_percent", "Cooling fan speed percent", label_names, registry=self.registry)
        self.fan_heatbreak_speed = Gauge("bambulab_fan_heatbreak_speed_percent", "Heatbreak fan speed percent", label_names, registry=self.registry)
        self.printer_error = Gauge("bambulab_printer_error", "1 when printer reported an error code", label_names, registry=self.registry)
        self.print_error_code_legacy = Gauge("bambulab_print_error_code", "Raw print_error value", label_names, registry=self.registry)
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
        self.printer_error_code = Gauge("bambulab_printer_error_code", "Raw printer error code", label_names, registry=self.registry)
        self.gcode_state = Gauge("bambulab_printer_gcode_state", "Current gcode state encoded as one-hot labels", [*label_names, "state"], registry=self.registry)
        self.mc_print_stage_state = Gauge("bambulab_mc_print_stage_state", "Current machine print stage as one-hot labels", [*label_names, "stage"], registry=self.registry)

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
        self._set_optional(self.bed_temp, snapshot.bed_temp)
        self._set_optional(self.bed_target_temp, snapshot.bed_target_temp)
        self._set_optional(self.chamber_temp, snapshot.chamber_temp)
        self._set_optional(self.fan_speed, snapshot.fan_gear)
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
        self._set_optional(self.print_error_code_legacy, snapshot.print_error)
        self._set_optional(self.ap_err_code, snapshot.ap_err)

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

        self._clear_ams(labels)
        for ams in snapshot.ams_units:
            ams_id = str(ams.get("id", "0"))
            trays = ams.get("tray") if isinstance(ams.get("tray"), list) else []
            active_id = str(ams.get("tray_now", "-1"))
            for tray in trays:
                tray_id = str(tray.get("id", "-1"))
                self.ams_slot_active.labels(**labels, ams_id=ams_id, slot_id=tray_id).set(
                    1.0 if tray_id == active_id else 0.0
                )
                remain = tray.get("remain")
                if isinstance(remain, (int, float)):
                    self.ams_slot_remaining_percent.labels(
                        **labels, ams_id=ams_id, slot_id=tray_id
                    ).set(float(remain))

    def _set_optional(self, gauge: Gauge, value: float | None) -> None:
        labels = self._labels()
        if value is None:
            gauge.labels(**labels).set(float("nan"))
            return
        gauge.labels(**labels).set(value)

    def _clear_ams(self, labels: dict[str, str]) -> None:
        self.ams_slot_active.clear()
        self.ams_slot_remaining_percent.clear()

    def mark_scrape(self, duration_seconds: float, success: bool, now_ts: float | None = None) -> None:
        labels = self._labels()
        self.scrape_duration_seconds.labels(**labels).set(duration_seconds)
        self.scrape_success.labels(**labels).set(1.0 if success else 0.0)
        if success and now_ts is not None:
            self.last_success_unixtime.labels(**labels).set(now_ts)
