# Grafana Dashboard

A ready-made dashboard is published on
[Grafana.com (ID 25033)](https://grafana.com/grafana/dashboards/25033-bambulab-metrics/) and
included in the repository as `examples/grafana/dashboard.sample.json`.

![Dashboard Sample](https://github.com/TheBlackBush/bambulab_metrics_exporter/blob/main/examples/grafana/dashboard-sample.jpg?raw=true)

---

## Requirements

- Prometheus scraping the exporter ([Prometheus Setup](Prometheus-Setup)). The **Job** dropdown
  lists Prometheus jobs whose name contains `bambulab`, so keep that in the job name.
- Exporter 0.2.0 or newer (older versions leave the newer panels empty).
- For the **AMS filament inventory** panel only: the free **Business Text** plugin and HTML
  rendering enabled:
  1. Install the plugin: `grafana-cli plugins install marcusolsson-dynamictext-panel`, or in
     Docker `GF_INSTALL_PLUGINS=marcusolsson-dynamictext-panel`, or **Administration > Plugins**.
  2. Allow HTML in panels: `GF_PANELS_DISABLE_SANITIZE_HTML=true`, or in `grafana.ini`:
     ```ini
     [panels]
     disable_sanitize_html = true
     ```
  3. Restart Grafana. Without step 2 the AMS panel shows plain text instead of spool cards.

All other panels use built-in Grafana panel types.

---

## Import

1. In Grafana open **Dashboards > New > Import**.
2. Enter **25033** and click **Load** (or upload `examples/grafana/dashboard.sample.json`).
3. Select your **Prometheus** data source and click **Import**.
4. Pick the **Job** and **Printer** at the top of the dashboard.

---

## Rows

- **Printer Status**: online state, model, gcode state, error flag, SD / USB storage, chamber light, door,
  nozzle diameter, XCam AI features, live printer connection, and exporter health (last poll
  result, time since the last successful poll, poll duration). Other panels keep the last values
  received while the connection reads Disconnected
- **Print Progress**: stage, time remaining, progress, layers, speed profile, job name
- **Temperatures**: nozzle, bed and chamber gauges, fan gauges (aux, chamber, part cooling,
  heatbreak), temperature and fan trends, and on dual-nozzle printers the active nozzle (right or
  left), its type, and current and target temperature per extruder (extruder 0 is the right
  nozzle)
- **AMS Status**: AMS model and status, auto refill, tangle detection setting, filament
  inventory (Business Text spool cards), AMS temperature and humidity per unit
- **Health & Firmware**: active HMS errors by severity and module, firmware update available,
  printer and module firmware versions
- **Chamber, Airduct & Accessories**: chamber heater state and target, airduct mode and fan
  speeds, mounted tool head, installed accessories, light states, timelapse storage
- **Extruders & Nozzles**: filament sensor and loaded AMS slot per extruder, nozzle print time
  and wear
- **Job & Filament Change**: job state, stage countdown, a per-extruder table with the filament
  change step (in plain words), feed direction, nozzle and buffer, and spools per AMS unit.
  These panels need recent firmware and show "Not reported" or no rows on printers that do not
  send the fields
- **AMS Drying**: drying time left, target temperature and dryer state per unit
- **Trending Metrics**: online history, Wi-Fi signal, remaining time, HMS errors, nozzle
  temperature, machine stage, print errors, airduct fans

Panels for hardware a printer does not have show a placeholder such as "No heater" or "N/A"
instead of an error. All queries filter on both `$job` and `$printer`, so one job can scrape
several exporters without mixing printers. The **Printer** dropdown lists `printer_name` values,
so printers with the same name appear as one entry: give each printer a distinct name.

---

## Alerts

Alert and recording rules are in [Prometheus Setup](Prometheus-Setup) and
`examples/prometheus/`.
