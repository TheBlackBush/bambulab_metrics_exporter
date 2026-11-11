# BambuLab 3D Printer: Grafana Dashboard

Real-time monitoring for BambuLab 3D printers: printer status, print progress, temperatures, fans, extruders and nozzles, AMS filament inventory and drying, HMS errors, firmware, airduct, lights and accessories. Use the **Job** and **Printer** dropdowns at the top to switch between printers; AMS units, extruders and fans are picked up automatically.

Panels for hardware your printer does not have show a placeholder ("No heater", "No dryer", "N/A") instead of an error. The nozzle and bed gauges scale to the printer model's temperature limits.

---

## Requirements

| Component | Version |
|---|---|
| Grafana | Built with 12.4, tested on 13.3 |
| Prometheus | 2.40+ |
| [bambulab_metrics_exporter](https://github.com/TheBlackBush/bambulab_metrics_exporter) | 0.4.0+ (older versions leave the newer panels empty) |
| Business Text plugin (`marcusolsson-dynamictext-panel`) | 6.x |

### Business Text plugin (AMS inventory panel)

The AMS filament inventory panel uses the **Business Text** panel by Volkov Labs to draw one spool card per slot with the real filament color, type, remaining % bar and an active-slot indicator. Native panels cannot loop over slots or bind colors from label values, so this one panel needs the plugin. Every other panel is a built-in Grafana panel.

#### 1. Install the plugin

Grafana CLI:

```bash
grafana-cli plugins install marcusolsson-dynamictext-panel
```

Docker:

```yaml
environment:
  - GF_INSTALL_PLUGINS=marcusolsson-dynamictext-panel
```

Grafana UI: **Administration → Plugins → search "Business Text" → Install**.

Restart Grafana after installing.

#### 2. Allow HTML in panels

Grafana sanitizes panel HTML by default, which strips the spool card styling. Turn sanitization off:

`grafana.ini`:

```ini
[panels]
disable_sanitize_html = true
```

or the environment variable (recommended for Docker):

```bash
GF_PANELS_DISABLE_SANITIZE_HTML=true
```

Docker Compose example:

```yaml
services:
  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_PANELS_DISABLE_SANITIZE_HTML=true
      - GF_INSTALL_PLUGINS=marcusolsson-dynamictext-panel
```

Restart Grafana. Without this the AMS panel shows plain text instead of spool cards.

---

## Data collection

The [bambulab_metrics_exporter](https://github.com/TheBlackBush/bambulab_metrics_exporter) connects to the printer over MQTT, either on your LAN (IP, serial, access code) or through Bambu Cloud, and exposes the telemetry as Prometheus metrics on port **9109**. It only reads; it never sends control commands. One exporter can monitor up to 32 printers (cloud and LAN mixed), or you can run one container per printer. Connect printers on the built-in setup page at `http://exporter-host:9109/auth`.

```
BambuLab printers (LAN MQTT or Bambu Cloud)
        │
        ▼
bambulab_metrics_exporter  (:9109/metrics)
        │
        ▼
Prometheus  ──►  Grafana
```

Model detection covers the A1, A1 mini, A2L, P1P, P1S, P2S, X1, X1C, X1E, X2D, H2D, H2D Pro, H2S, H2C and H3C. Real-world validation so far is on an X1C and an H2D.

### Prometheus scrape config

```yaml
scrape_configs:
  - job_name: bambulab
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets:
          - exporter-host:9109   # one target per exporter
```

The dashboard's **Job** dropdown lists jobs whose name contains `bambulab`, so keep that in the job name (or edit the variable's regex). The **Printer** dropdown lists printer names, so give each printer a distinct name.

Check that metrics are flowing at `http://exporter-host:9109/metrics`: you should see metrics prefixed with `bambulab_`.

---

## Dashboard rows

### Printer Status
Printer connection, model, gcode state (IDLE, RUNNING, FINISH, ...), job state, error flag, SD card or USB drive, door, top lid (H2 series), chamber light, the XCam AI features (first layer inspection, build plate detector, AI print monitor and its sensitivity), camera recording, timelapse, wired or Wi-Fi network, mounted tool head (laser, cutter, cooling fan) and installed accessories (filament buffer, external exhaust fan, fire extinguisher, ...).

### Print Progress
Print stage, time remaining, progress gauge, current/total layers, stage countdown, skipped objects, job name, file download progress, job source (cloud or local), speed percentage and profile, and the fail reason when a print fails.

### Temperatures
Nozzle, bed and chamber gauges, chamber target and heater state (X1E, X2D, H2 series), fan gauges (aux, chamber, part cooling, heatbreak), and trends for temperatures, each extruder's current and target temperature, and fan speeds.

### Extruders & Nozzles
An Extruder Status table with one row per extruder: filament change step, feed direction, filament sensor, loaded AMS slot, nozzle type and diameter, nozzle fitted, filament in the buffer. Plus the active nozzle (left or right) on dual-nozzle printers, its type and diameter, nozzle print time and wear.

### AMS
AMS model, AMS status, auto refill, tangle detection setting, spools per unit, dryer state, the **AMS filament inventory** (Business Text spool cards for every AMS unit plus the external spool), AMS temperature and humidity, drying status for AMS 2 Pro and AMS HT units (time left, target, phase, set duration and why drying cannot start), and an AMS Zones table with humidity, temperature and drying per zone for the AMS 3H on the H3C.

### Airduct, Lights & Storage
Airduct mode and per-fan speeds (P2S, X2D, H2 series), light states, and timelapse storage.

### Health & Firmware
Active HMS errors by severity and by module, firmware update available, firmware upgrade progress, printer firmware version and a firmware table for every module (mainboard, toolhead, AMS units, ...).

### Trending Metrics
Printer connection history, WiFi signal, remaining time, HMS errors over time, machine stage, print errors and airduct fans.

### Exporter Health
Last poll result, time since the last successful poll, and poll duration.

---

## Key metrics

| Metric | Description |
|---|---|
| `bambulab_printer_up` | 1 when the last poll returned data |
| `bambulab_printer_connected` | 1 while the MQTT connection is up |
| `bambulab_printer_gcode_state{state}` | Current gcode state (one-hot) |
| `bambulab_print_progress_percent` | Print progress 0-100 |
| `bambulab_print_remaining_seconds` | Estimated time remaining |
| `bambulab_active_nozzle_temperature_celsius` | Temperature of the nozzle in use (dual-nozzle printers) |
| `bambulab_nozzle_temperature_celsius` / `bambulab_bed_temperature_celsius` | Current temperatures (plus `_target_` variants) |
| `bambulab_chamber_temperature_celsius` | Chamber temperature (models with a chamber sensor) |
| `bambulab_hms_active_errors{severity}` | Active HMS errors: fatal, serious, common, info |
| `bambulab_ams_slot_tray_info` / `bambulab_ams_slot_remaining_percent` | Filament per AMS slot |
| `bambulab_ams_unit_humidity` / `bambulab_ams_unit_temperature_celsius` | AMS environment per unit |
| `bambulab_ams_drying_remaining_seconds{ams_id}` | Drying time left (AMS 2 Pro, AMS HT) |
| `bambulab_firmware_update_available` | 1 when a firmware update is offered |
| `bambulab_light_mode_info{light,mode}` | Light states |

Full reference: [Metrics Reference](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Metrics-Reference).

---

## Alerting suggestions

| Alert | Condition |
|---|---|
| Exporter not polling | `bambulab_printer_up == 0` for 2 minutes |
| Printer disconnected | `bambulab_printer_connected == 0` for 1 minute |
| Serious HMS error | `sum by (printer_name) (bambulab_hms_active_errors{severity=~"fatal\|serious"}) > 0` |
| Printer error | `bambulab_printer_error == 1` |
| AMS humid | `bambulab_ams_unit_humidity_index >= 4` |
| Low filament | `15 >= bambulab_ams_slot_remaining_percent` (15% or less left) |
| Firmware update | `bambulab_firmware_update_available == 1` |

Ready-to-use rules: [prometheus.alerts.yml](https://github.com/TheBlackBush/bambulab_metrics_exporter/blob/main/examples/prometheus/prometheus.alerts.yml).

---

## License

MIT, free to use, modify and share.
