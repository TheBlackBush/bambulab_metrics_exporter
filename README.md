# bambulab-metrics-exporter

Production-oriented Prometheus exporter for Bambu Lab printers (homelab/self-hosted friendly).

## What this does

- Connects to Bambu printer over **LAN MQTT** (`mqtts://<printer>:8883`)
- Periodically requests a full state snapshot (`pushall`)
- Parses print state/telemetry into stable Prometheus metrics
- Exposes:
  - `GET /metrics`
  - `GET /health`
  - `GET /ready`

## Engineering notes from reference (`WeeJeWel/com.bambulab`)

The Homey app was used as architecture reference (not copied):

- Authentication modes in that project:
  - Cloud account flow (`email + 2FA`) for device discovery
  - Local printer LAN mode using `bblp` + `accessCode`
- Transport/state model:
  - MQTT report topic: `device/<serial>/report`
  - MQTT request topic: `device/<serial>/request`
  - `pushall` command requests full state
- Important telemetry fields observed:
  - `gcode_state`, `mc_percent`, `mc_remaining_time`
  - `nozzle_temper`, `bed_temper`, `chamber_temper`
  - AMS blocks, error codes

For exporter scope, local MQTT is preferred: lower latency, simpler, no cloud dependency.

## Quick start (local)

```bash
cp .env.example .env
# edit .env values
python -m venv .venv
source .venv/bin/activate
pip install -e .
bambulab-exporter
```

Then open:

- <http://localhost:9109/metrics>
- <http://localhost:9109/health>
- <http://localhost:9109/ready>

## Environment variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `BAMBULAB_TRANSPORT` | no | `local_mqtt` | Transport backend (currently local_mqtt) |
| `BAMBULAB_HOST` | yes | - | Printer IP/hostname |
| `BAMBULAB_PORT` | no | `8883` | Printer MQTT TLS port |
| `BAMBULAB_SERIAL` | yes | - | Printer serial/device id |
| `BAMBULAB_ACCESS_CODE` | yes | - | Printer LAN access code |
| `BAMBULAB_USERNAME` | no | `bblp` | MQTT username |
| `BAMBULAB_REQUEST_PUSHALL` | no | `true` | Request full snapshot every poll |
| `POLLING_INTERVAL_SECONDS` | no | `10` | Polling interval |
| `REQUEST_TIMEOUT_SECONDS` | no | `8` | Per-cycle snapshot timeout |
| `LISTEN_HOST` | no | `0.0.0.0` | HTTP bind host |
| `LISTEN_PORT` | no | `9109` | HTTP port |
| `PRINTER_NAME` | no | `bambulab` | Stable metric label |
| `SITE` | no | empty | Optional metric label |
| `LOCATION` | no | empty | Optional metric label |
| `LOG_LEVEL` | no | `INFO` | Python log level |

## Docker

```bash
docker build -t bambulab-metrics-exporter:latest .
docker run --rm -p 9109:9109 --env-file .env bambulab-metrics-exporter:latest
```

or:

```bash
docker compose up -d --build
```

## Prometheus integration

Use `deploy/prometheus.scrape.yml` snippet, or equivalent:

```yaml
scrape_configs:
  - job_name: bambulab
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["bambulab-metrics-exporter:9109"]
```

## Exported metrics (core)

- `bambulab_printer_up`
- `bambulab_printer_connected`
- `bambulab_print_progress_percent`
- `bambulab_print_remaining_seconds`
- `bambulab_nozzle_temperature_celsius`
- `bambulab_bed_temperature_celsius`
- `bambulab_chamber_temperature_celsius`
- `bambulab_fan_speed_percent`
- `bambulab_printer_error`
- `bambulab_printer_error_code`
- `bambulab_printer_gcode_state{state="..."}` (one-hot)
- `bambulab_ams_slot_active{ams_id,slot_id}`
- `bambulab_ams_slot_remaining_percent{ams_id,slot_id}`

Exporter self-metrics:

- `bambulab_exporter_scrape_duration_seconds`
- `bambulab_exporter_scrape_success`
- `bambulab_exporter_last_success_unixtime`

All metrics include stable labels:

- `printer_name`
- `site`
- `location`

## Testing

```bash
pip install -e .[dev]
pytest -q
```

## Known limitations

1. Current implementation is LAN MQTT only (by design).
2. TLS cert verification is disabled for printer-local TLS (common in Bambu LAN mode).
3. Some firmware fields can be missing or model-specific; exporter degrades gracefully (`NaN` for missing scalar values).

## Future enhancements

- Cloud transport plugin (`BambuCloudClient`) behind same client interface
- Optional job-name metric via controlled allow-listing (avoid cardinality issues)
- Better fan mapping per model/firmware
- Integration tests with recorded MQTT fixtures
