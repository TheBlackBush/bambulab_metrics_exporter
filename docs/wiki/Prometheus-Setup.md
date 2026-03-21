# Prometheus Setup

Configure Prometheus to scrape the exporter and optionally load alert and recording rules.

---

## Prerequisites

- Prometheus 2.x running and accessible
- bambulab_metrics_exporter running and reachable on port `9109`

---

## Scrape Configuration

Add the following job to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: bambulab
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["bambulab-metrics-exporter:9109"]
        labels:
          instance: my-printer   # optional, for multi-printer setups
```

A ready-to-use snippet is available at `examples/prometheus/prometheus.scrape.yml`.

---

## Validation

After reloading Prometheus:

1. Open Prometheus UI → **Status → Targets**
2. Find the `bambulab` job — state should be **UP**
3. Query `bambulab_printer_connected` — expect value `1`

---

## Alert Rules

> **Canonical thresholds:** The production-ready alert definitions with tuned thresholds are in `examples/prometheus/prometheus.alerts.yml`. If the inline examples below differ, prefer the file in the repository.

Import `examples/prometheus/prometheus.alerts.yml` or add inline:

```yaml
groups:
  - name: bambulab
    rules:
      - alert: BambuPrinterDisconnected
        expr: bambulab_printer_connected == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Printer {{ $labels.printer_name }} is disconnected"

      - alert: BambuExporterStale
        expr: time() - bambulab_exporter_last_success_unixtime > 300
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Exporter has not scraped successfully in 5 minutes"

      - alert: BambuDoorOpenWhilePrinting
        expr: |
          bambulab_door_open == 1
          and on(printer_name, serial)
          bambulab_printer_gcode_state{state="RUNNING"} == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Printer door open during active print"

      - alert: BambuSdCardAbnormal
        expr: bambulab_sdcard_status_info{status="abnormal"} == 1
        labels:
          severity: warning
        annotations:
          summary: "SD card issue detected on {{ $labels.printer_name }}"
```

---

## Recording Rules

Pre-computed aggregations are available in `examples/prometheus/prometheus.recording.yml`. Load them to speed up Grafana dashboards.

---

## Multiple Printers

Run one exporter instance per printer, each on a distinct port. Use the `PRINTER_NAME_LABEL` env var to set a stable label, and add each target to your scrape config:

```yaml
static_configs:
  - targets:
      - "bambulab-exporter-x1c:9109"
      - "bambulab-exporter-p1p:9110"
```

All metrics include `printer_name` and `serial` labels for per-printer filtering.
