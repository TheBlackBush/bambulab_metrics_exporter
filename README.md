# bambulab-metrics-exporter

[![Docker Publish](https://img.shields.io/github/actions/workflow/status/TheBlackBush/bambulab_metrics_exporter/docker-publish.yml?style=for-the-badge&label=Docker%20Publish)](https://github.com/TheBlackBush/bambulab_metrics_exporter/actions/workflows/docker-publish.yml)
[![GitHub Release](https://img.shields.io/github/v/release/TheBlackBush/bambulab_metrics_exporter?style=for-the-badge)](https://github.com/TheBlackBush/bambulab_metrics_exporter/releases)
[![GHCR Package](https://img.shields.io/badge/image-bambulab__metrics__exporter-blue?style=for-the-badge&logo=github)](https://github.com/TheBlackBush/bambulab_metrics_exporter/pkgs/container/bambulab_metrics_exporter)
[![Last Commit](https://img.shields.io/github/last-commit/TheBlackBush/bambulab_metrics_exporter?style=for-the-badge)](https://github.com/TheBlackBush/bambulab_metrics_exporter/commits/main)
[![Ko-fi](https://img.shields.io/badge/support_me_on_ko--fi-F16061?style=for-the-badge&logo=kofi&logoColor=f5f5f5)](https://ko-fi.com/M4M11W3R7J)

Production-oriented Prometheus exporter for Bambu Lab printers (homelab/self-hosted friendly).

> **Note:** Development and real-world validation of this exporter are currently done only on an **X1C** printer.
> If you want to help improve support for additional printer models, please get in touch with me via GitHub.


## What this does

- Connects to Bambu printer over **LAN MQTT** or **Cloud MQTT**
- Periodically requests a full state snapshot (`pushall`)
- Parses print state/telemetry into stable Prometheus metrics
- Exposes:
  - `GET /metrics`
  - `GET /health`
  - `GET /ready`

## Implementation notes

- Supports both LAN MQTT (`local_mqtt`) and Cloud MQTT (`cloud_mqtt`).
- Uses `device/<serial>/report` and `device/<serial>/request` topics.
- Requests full snapshots with `pushall` and maps stable telemetry fields to Prometheus metrics.
- Printer model detection uses a table-driven resolver pipeline (`product_name` → `hw_ver+project_name` → `SN prefix` → legacy fallbacks), including newer SN prefixes such as `22E` (P2S), `093` (H2S), and `094` (H2D).

For exporter scope, local MQTT is preferred by default, but cloud MQTT is also supported.

## Quick start (local)

```bash
cp .env.example .env
# edit .env values
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# or: pip install -e .
bambulab-exporter
```

Then open:

- <http://localhost:9109/metrics>
- <http://localhost:9109/health>
- <http://localhost:9109/ready>

## Cloud connection (email + 2FA code)

Use the included helper CLI to get cloud credentials:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Step 1: send verification code to email
bambulab-cloud-auth --email you@example.com --send-code

# Step 2: exchange code for access token + user id
bambulab-cloud-auth --email you@example.com --code 123456
```

Then put the output values in `.env`:

```dotenv
BAMBULAB_TRANSPORT=cloud_mqtt
BAMBULAB_SERIAL=<printer_serial>
BAMBULAB_CLOUD_USER_ID=<uid>
BAMBULAB_CLOUD_ACCESS_TOKEN=<access_token>
BAMBULAB_CLOUD_MQTT_HOST=us.mqtt.bambulab.com
BAMBULAB_CLOUD_MQTT_PORT=8883
```

And run as usual:

```bash
bambulab-exporter
```

## Environment variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `BAMBULAB_TRANSPORT` | no | `local_mqtt` | Transport backend (`local_mqtt` or `cloud_mqtt`) |
| `BAMBULAB_HOST` | yes | - | Printer IP/hostname |
| `BAMBULAB_PORT` | no | `8883` | Printer MQTT TLS port |
| `BAMBULAB_SERIAL` | yes | - | Printer serial/device id |
| `BAMBULAB_ACCESS_CODE` | yes | - | Printer LAN access code |
| `BAMBULAB_USERNAME` | no | `bblp` | MQTT username |
| `BAMBULAB_REQUEST_PUSHALL` | no | `true` | Request full snapshot every poll |
| `PRINTER_NAME_LABEL` | no | empty | Custom printer name label (falls back to `BAMBULAB_PRINTER_NAME`) |
| `BAMBULAB_PRINTER_NAME` | no | auto | Real printer name discovered from machine (auto-persisted) |
| `POLLING_INTERVAL_SECONDS` | no | `10` | Polling interval |
| `REQUEST_TIMEOUT_SECONDS` | no | `8` | Per-cycle snapshot timeout |
| `LISTEN_HOST` | no | `0.0.0.0` | HTTP bind host |
| `LISTEN_PORT` | no | `9109` | HTTP port |
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

### Docker Compose (recommended)

`docker-compose.yml` is cloud-first and minimal by default.

- Required cloud fields are active by default.
- Optional fields stay commented with short inline hints.
- Works for regular Linux hosts and Unraid (`PUID/PGID/UMASK` optional).

### CI/CD behavior (current)

- Pull Requests to `main`: run essential tests only.
- Push/Merge to `main`: run full test suite.
- Published Release: run full tests, then Docker multi-arch build/push to GHCR.

Minimal required values before first run (cloud mode):

- `BAMBULAB_TRANSPORT=cloud_mqtt`
- `BAMBULAB_SERIAL=<printer_serial>`
- `BAMBULAB_SECRET_KEY=<strong_random_key>`
- `BAMBULAB_CLOUD_EMAIL=<your_email>`

If `BAMBULAB_CLOUD_USER_ID`/`BAMBULAB_CLOUD_ACCESS_TOKEN` are missing, startup re-auth flow can trigger automatically.

## Prometheus integration

Use `examples/prometheus/prometheus.scrape.yml` snippet, or equivalent:

```yaml
scrape_configs:
  - job_name: bambulab
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["bambulab-metrics-exporter:9109"]
```

## Operator PromQL examples

### AMS metrics

- Average humidity index per AMS unit over 15 minutes:

```promql
avg_over_time(bambulab_ams_unit_humidity_index{printer_name="$printer"}[15m])
```

- Lowest remaining filament percentage per printer (all AMS slots):

```promql
min by (printer_name) (bambulab_ams_slot_remaining_percent)
```

- Slots below 15% remaining filament:

```promql
bambulab_ams_slot_remaining_percent{printer_name="$printer"} < 15
```

### Alert tuning examples

- Door open while printing, less sensitive (require 2 minutes open):

```promql
bambulab_door_open{printer_name="$printer"} == 1
and on(printer_name, serial)
bambulab_printer_gcode_state{printer_name="$printer", state="RUNNING"} == 1
```

Suggested alert rule tuning:

```yaml
for: 2m
labels:
  severity: warning
```

- Stale exporter threshold tuned for slower polling environments:

```promql
time() - bambulab_exporter_last_success_unixtime{printer_name="$printer"} > 300
```

Suggested alert rule tuning:

```yaml
for: 2m
labels:
  severity: warning
```

- SD card abnormal status:

```promql
bambulab_sdcard_status_info{printer_name="$printer", status="abnormal"} == 1
```


## Exported metrics (core)

| Metric | Type | Description |
|---|---|---|
| `bambulab_printer_up` | Gauge | 1 if latest poll returned a valid payload. |
| `bambulab_printer_connected` | Gauge | 1 if MQTT connection is up. |
| `bambulab_print_progress_percent` | Gauge | Print progress percent. |
| `bambulab_print_remaining_seconds` | Gauge | Estimated seconds remaining. |
| `bambulab_print_layer_current` | Gauge | Current print layer. |
| `bambulab_print_layer_total` | Gauge | Total print layers. |
| `bambulab_print_layer_progress_percent` | Gauge | Layer-based progress percent. |
| `bambulab_nozzle_temperature_celsius` | Gauge | Current nozzle temperature. |
| `bambulab_nozzle_target_temperature_celsius` | Gauge | Target nozzle temperature. |
| `bambulab_nozzle_diameter` | Gauge | Nozzle diameter from telemetry. |
| `bambulab_bed_temperature_celsius` | Gauge | Current bed temperature. |
| `bambulab_bed_target_temperature_celsius` | Gauge | Target bed temperature. |
| `bambulab_chamber_temperature_celsius` | Gauge | Chamber temperature. |
| `bambulab_fan_big_1_speed_percent` | Gauge | Big fan 1 speed percent. |
| `bambulab_fan_big_2_speed_percent` | Gauge | Big fan 2 speed percent. |
| `bambulab_fan_cooling_speed_percent` | Gauge | Cooling fan speed percent. |
| `bambulab_fan_heatbreak_speed_percent` | Gauge | Heatbreak fan speed percent. |
| `bambulab_printer_error` | Gauge | 1 when printer error code is non-zero. |
| `bambulab_printer_error_code` | Gauge | Raw printer error code. |
| `bambulab_print_error` | Gauge | Raw `print_error` value from MQTT. |
| `bambulab_ap_error_code` | Gauge | Raw `ap_err` value from MQTT. |
| `bambulab_printer_gcode_state{state}` | One-hot Gauge | Current gcode state as one-hot labels. |
| `bambulab_mc_print_stage_state{stage}` | One-hot Gauge | Current print stage as one-hot labels. |
| `bambulab_subtask_name_info{subtask_name}` | Info Gauge | Current subtask name. |
| `bambulab_fail_reason_info{fail_reason}` | Info Gauge | Current fail reason. |
| `bambulab_printer_model_info{model}` | Info Gauge | Detected printer model. |
| `bambulab_wifi_signal` | Gauge | Wi-Fi signal value (dBm when available). |
| `bambulab_online_ahb` | Gauge | Online AHB flag. |
| `bambulab_online_ext` | Gauge | Online external flag. |
| `bambulab_chamber_light_on` | Gauge | Chamber light status (1/0). |
| `bambulab_work_light_on` | Gauge | Work light status (1/0). |
| `bambulab_xcam_feature_enabled{feature}` | Gauge | XCam feature enable flags. |
| `bambulab_ams_status_id` | Gauge | AMS status numeric code. |
| `bambulab_ams_status_name{status}` | Info Gauge | AMS status name label. |
| `bambulab_ams_rfid_status_id` | Gauge | AMS RFID status numeric code. |
| `bambulab_ams_rfid_status_name{status}` | Info Gauge | AMS RFID status name label. |
| `bambulab_ams_unit_info{ams_id,ams_model,ams_series}` | Info Gauge | AMS unit identity labels. |
| `bambulab_ams_unit_humidity{ams_id}` | Gauge | AMS humidity raw value. |
| `bambulab_ams_unit_humidity_index{ams_id}` | Gauge | AMS humidity index (1-5). |
| `bambulab_ams_unit_temperature_celsius{ams_id}` | Gauge | AMS temperature. |
| `bambulab_ams_slot_active{ams_id,slot_id}` | Gauge | AMS slot active flag. |
| `bambulab_ams_slot_remaining_percent{ams_id,slot_id}` | Gauge | AMS slot remaining filament %. |
| `bambulab_ams_slot_tray_type_info{ams_id,slot_id,tray_type}` | Info Gauge | AMS slot filament type. |
| `bambulab_ams_slot_tray_color_info{ams_id,slot_id,tray_color}` | Info Gauge | AMS slot filament color. |
| `bambulab_ams_heater_state_info{ams_id,ams_model,ams_series,state}` | Info Gauge | Gen2 AMS heater/dry state. |
| `bambulab_ams_dry_fan_status{ams_id,ams_model,ams_series,fan_id}` | Gauge | Gen2 AMS drying fan status. |
| `bambulab_ams_dry_sub_status_info{ams_id,ams_model,ams_series,state}` | Info Gauge | Gen2 AMS drying sub-status. |
| `bambulab_external_spool_active` | Gauge | 1 when external spool is active. |
| `bambulab_external_spool_info{external_id,tray_type,tray_info_idx,tray_color}` | Info Gauge | External spool metadata. |
| `bambulab_active_extruder_index` | Gauge | Active extruder index (dual-extruder models). |
| `bambulab_extruder_temperature_celsius{extruder_id}` | Gauge | Per-extruder current temperature. |
| `bambulab_extruder_target_temperature_celsius{extruder_id}` | Gauge | Per-extruder target temperature. |
| `bambulab_extruder_nozzle_info{extruder_id,nozzle_type,nozzle_diameter}` | Info Gauge | Per-extruder nozzle metadata. |
| `bambulab_active_nozzle_info{nozzle_type,nozzle_diameter}` | Info Gauge | Active nozzle metadata. |
| `bambulab_hotend_rack_holder_position_info{position}` | Info Gauge | Hotend rack holder position. |
| `bambulab_hotend_rack_holder_state_info{state}` | Info Gauge | Hotend rack holder state. |
| `bambulab_hotend_rack_slot_state_info{slot_id,state}` | Info Gauge | Hotend rack slot state (`mounted/docked/empty`). |
| `bambulab_hotend_rack_hotend_info{slot_id,nozzle_type,nozzle_diameter}` | Info Gauge | Hotend rack slot nozzle metadata. |
| `bambulab_hotend_rack_hotend_wear_ratio{slot_id}` | Gauge | Hotend rack nozzle wear ratio. |
| `bambulab_hotend_rack_hotend_runtime_minutes{slot_id}` | Gauge | Hotend rack nozzle runtime minutes. |
| `bambulab_sdcard_status_info{status}` | Info Gauge | SD-card status (`present/abnormal/absent`). |
| `bambulab_door_open` | Gauge | Door open flag. |
| `bambulab_wired_network` | Gauge | Wired network detected flag. |
| `bambulab_camera_recording` | Gauge | Camera recording flag. |
| `bambulab_ams_auto_switch` | Gauge | AMS auto-switch flag. |
| `bambulab_filament_tangle_detected` | Gauge | Filament tangle detected flag. |
| `bambulab_filament_tangle_detect_supported` | Gauge | Filament tangle detection support flag. |
| `bambulab_queue_total` | Gauge | Total queued jobs. |
| `bambulab_queue_estimated_seconds` | Gauge | Estimated queue seconds. |
| `bambulab_queue_number` | Gauge | Queue number. |
| `bambulab_queue_status` | Gauge | Queue status numeric code. |
| `bambulab_queue_position` | Gauge | Queue position. |
| `bambulab_spd_lvl` | Gauge | Speed level numeric value. |
| `bambulab_spd_mag` | Gauge | Speed multiplier/percentage. |
| `bambulab_spd_lvl_state{mode}` | One-hot Gauge | Speed mode one-hot labels. |
| `bambulab_stg_cur` | Gauge | Current stage numeric id. |
| `bambulab_print_stage_info{stage}` | Info Gauge | Current stage name label. |
| `bambulab_exporter_scrape_duration_seconds` | Gauge | Duration of last scrape cycle. |
| `bambulab_exporter_scrape_success` | Gauge | 1 when last scrape succeeded. |
| `bambulab_exporter_last_success_unixtime` | Gauge | Unix timestamp of last successful scrape. |

All metrics include stable labels:

- `printer_name` (from `PRINTER_NAME_LABEL` or `BAMBULAB_PRINTER_NAME`)
- `serial` (from `BAMBULAB_SERIAL`)

## Testing

```bash
pip install -r requirements-dev.txt
# or: pip install -e .[dev]
pytest --cov=src --cov-report=term-missing
```

Currently maintaining **>95% test coverage** for core modules.

### Sample payload and expected metrics

- MQTT sample payload: `examples/sample_mqtt_message.json`
- Sample metrics excerpt: `examples/sample_metrics.prom`

These are useful for quick regression checks and dashboard/query validation.

## Known limitations

1. Cloud mode currently expects a valid access token (helper tool included for obtaining it).
2. TLS cert verification is disabled in both LAN/cloud MQTT paths for compatibility with current broker behavior.
3. Some firmware fields can be missing or model-specific; exporter degrades gracefully (`NaN` for missing scalar values).

## Future enhancements

- Automatic access-token refresh using refresh token
- Optional job-name metric via controlled allow-listing (avoid cardinality issues)
- Better fan mapping per model/firmware
- Integration tests with recorded MQTT fixtures


## Secure local credential storage (Option 1)

The project now supports encrypted local credential storage for cloud auth:

- Encrypted file: `${BAMBULAB_CONFIG_DIR}/${BAMBULAB_CREDENTIALS_FILE}`
- Shared with host via Docker volume
- Encrypted using `BAMBULAB_SECRET_KEY`

### Docker example

```yaml
services:
  bambulab-metrics-exporter:
    image: bambulab-metrics-exporter:latest
    env_file:
      - .env
    environment:
      - BAMBULAB_SECRET_KEY=${BAMBULAB_SECRET_KEY}
    volumes:
      - ./config:/config/bambulab-metrics-exporter
```

### Cloud auth + save

```bash
bambulab-cloud-auth --email you@example.com --code 123456 \
  --serial <printer_serial> \
  --save \
  --secret-key "$BAMBULAB_SECRET_KEY"
```

This command will:
1. Fetch cloud token/user id
2. Save encrypted credentials to config volume
3. Update `.env` automatically

At exporter startup:
- If `BAMBULAB_TRANSPORT=cloud_mqtt` and env tokens are missing, exporter auto-loads credentials from encrypted file.
- Runtime-provided env vars are synced back into `.env` (whitelisted keys).


## Startup behavior (connection preflight)

On container startup, exporter performs a connection preflight:

- **local_mqtt**
  - If required env vars are missing: startup fails with clear error.
  - If connection test fails: startup fails with troubleshooting message.

- **cloud_mqtt**
  - If credentials are missing/invalid: exporter tries automatic re-auth.
  - Re-auth requires `BAMBULAB_CLOUD_EMAIL`.
  - If `BAMBULAB_CLOUD_CODE` is missing, exporter sends a new code email and exits with instruction to restart with the code.
  - On success, new credentials are saved encrypted to config dir and synced to `.env`, so next startup won't require re-entry.


Prometheus scrape config sample: `examples/prometheus/prometheus.scrape.yml`

Alert rules sample: `examples/prometheus/prometheus.alerts.yml`

Recording rules sample: `examples/prometheus/prometheus.recording.yml`

Grafana sample dashboard: `examples/grafana/dashboard.sample.json`


## Unraid Docker template

A ready-to-import Unraid template is included:

- `unraid-bambulab-metrics-exporter.xml`

In Unraid:
1. Docker -> Add Container -> Template: use XML file content (or host it and use Template URL).
2. Fill `BAMBULAB_SECRET_KEY` and required transport fields.
3. Start container and verify `/metrics`.

> Note: Replace repository/template/icon URLs in XML with your actual GitHub/registry paths before publishing.


### Unraid clean setup (PUID/PGID)

Unraid support is integrated into the main runtime files:

- `Dockerfile`
- `entrypoint.sh`
- `docker-compose.yml`
- `unraid-bambulab-metrics-exporter.xml`

The container starts with bootstrap privileges to align UID/GID, then drops to `PUID:PGID` using `gosu`.

Default values are:
- `PUID=99`
- `PGID=100`
- `UMASK=002`

Build/run example:

```bash
cd /path/to/bambulab-metrics-exporter
export BAMBULAB_SECRET_KEY='your-strong-key'
docker compose up --build -d
```
