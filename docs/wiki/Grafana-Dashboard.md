# Grafana Dashboard

A ready-to-import sample dashboard is included in the repository.
The dashboard is also published on the [Grafana.com dashboard listing](https://grafana.com/grafana/dashboards/25033-bambulab-metrics/).

---

## Dashboard Files

| File | Description |
|------|-------------|
| `examples/grafana/dashboard.sample.json` | Grafana dashboard JSON — import directly |
| `examples/grafana/dashboard-sample.jpg` | Screenshot of the sample dashboard |

---

## Import Steps

1. Open Grafana → **Dashboards → Import**
2. Click **Upload JSON file** → select `examples/grafana/dashboard.sample.json`
3. Select your **Prometheus data source**
4. Click **Import**

Set `$printer` variable to your `printer_name` label value.

---

## Dashboard Preview

![Dashboard Sample](https://github.com/TheBlackBush/bambulab_metrics_exporter/blob/main/examples/grafana/dashboard-sample.jpg?raw=true)

---

## Included Panels

- **Print status** — progress %, remaining time, layer, gcode state
- **Temperatures** — nozzle, bed, chamber (current and target)
- **Fans** — big1, big2, cooling, heatbreak, secondary aux
- **AMS** — humidity index per unit, remaining % per slot, filament type/color
- **Print stage** — current stage name
- **Exporter health** — last success, scrape duration, connectivity

---

## Prometheus Assets

| File | Description |
|------|-------------|
| `examples/prometheus/prometheus.scrape.yml` | Scrape config snippet |
| `examples/prometheus/prometheus.alerts.yml` | Alert rules |
| `examples/prometheus/prometheus.recording.yml` | Recording rules |

---

## Suggested Alert Rules

```yaml
- alert: BambuDoorOpenWhilePrinting
  expr: |
    bambulab_door_open == 1
    and on(printer_name, serial)
    bambulab_printer_gcode_state{state="RUNNING"} == 1
  for: 2m
  labels:
    severity: warning

- alert: BambuExporterStale
  expr: time() - bambulab_exporter_last_success_unixtime > 300
  for: 2m
  labels:
    severity: warning

- alert: BambuSdCardAbnormal
  expr: bambulab_sdcard_status_info{status="abnormal"} == 1
  labels:
    severity: warning
```
