# Prometheus Setup

Configure Prometheus to scrape the exporter and optionally load alert and recording rules.

---

## Prerequisites

- Prometheus 2.x running and accessible
- Keep `bambulab` in the job name: the [Grafana dashboard](Grafana-Dashboard) **Job** dropdown
  lists jobs whose name contains it
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
      - targets: ["bambulab-metrics-exporter:9109"]   # or <docker-host-ip>:9109
        labels:
          instance: my-printer   # optional, for setups with several exporters
```

A ready-to-use snippet is available at `examples/prometheus/prometheus.scrape.yml`.

---

## Validation

After reloading Prometheus:

1. Open Prometheus UI → **Status → Targets**
2. Find the `bambulab` job: state should be **UP**
3. Query `bambulab_printer_connected`: expect value `1`

---

## Alert Rules

Load `examples/prometheus/prometheus.alerts.yml` (add it to `rule_files` in `prometheus.yml`).
It contains:

| Alert | Fires when |
|-------|------------|
| `BambuPrinterOffline` | The exporter is not connected to the printer |
| `BambuExporterScrapeFailing` | Polling the printer fails |
| `BambuExporterStale` | No successful poll for 3 minutes |
| `BambuPrinterErrorActive` | The printer reports an error |
| `BambuHmsSeriousError` | A serious or fatal HMS error is active |
| `BambuNozzleTooHot` | The nozzle is above 320 °C |
| `BambuDoorOpenWhilePrinting` | The door is open during a print (models with a door sensor) |
| `BambuSdCardAbnormal` | The SD card reports a problem (not yet confirmed for USB drives on printers with no SD slot) |

The file is the reference for exact expressions and thresholds; adjust them there.

---

## Recording Rules

Pre-computed aggregations are available in `examples/prometheus/prometheus.recording.yml`. Load them to speed up Grafana dashboards.

---

## Multiple Printers

One exporter can monitor up to 32 printers chosen on the `/auth` page, so a single scrape target
serves all of them. `/metrics` carries every printer's series, told apart by the `printer_name` and
`serial` labels. `/ready` is ready once any printer has data. `PRINTER_NAME_LABEL` applies only to
the printer configured through env vars; other printers use their cloud name, the name typed for a
LAN printer, or a masked serial.

You can still run one exporter container per printer, each on its own host port (and its own config
volume), and add each target to your scrape config:

```yaml
static_configs:
  - targets:
      - "bambulab-exporter-x1c:9109"
      - "bambulab-exporter-p1p:9110"
```

All metrics include `printer_name` and `serial` labels for per-printer filtering.
