# bambulab-metrics-exporter

Production-oriented Prometheus exporter for Bambu Lab printers (homelab/self-hosted friendly).

## What this does

- Connects to Bambu printer over **LAN MQTT** or **Cloud MQTT**
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

For exporter scope, local MQTT is preferred by default, but cloud MQTT is now supported as an alternative transport.

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
| `BAMBULAB_CLOUD_MQTT_HOST` | cloud | `us.mqtt.bambulab.com` | Cloud MQTT broker host |
| `BAMBULAB_CLOUD_MQTT_PORT` | cloud | `8883` | Cloud MQTT broker port |
| `BAMBULAB_CLOUD_USER_ID` | cloud | - | Bambu cloud uid (used as username `u_<uid>`) |
| `BAMBULAB_CLOUD_ACCESS_TOKEN` | cloud | - | Bambu cloud access token |
| `BAMBULAB_CLOUD_REFRESH_TOKEN` | no | empty | Optional stored refresh token (future use) |
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

- `bambulab_fan_big_1_speed_percent`
- `bambulab_fan_big_2_speed_percent`
- `bambulab_fan_cooling_speed_percent`
- `bambulab_fan_heatbreak_speed_percent`
- `bambulab_mc_stage`
- `bambulab_mc_print_sub_stage`
- `bambulab_print_real_action`
- `bambulab_print_gcode_action`
- `bambulab_mc_print_stage_state{stage="..."}`
- `bambulab_wifi_signal`
- `bambulab_online_ahb`
- `bambulab_online_ext`
- `bambulab_ams_status`
- `bambulab_ams_rfid_status`
- `bambulab_ams_unit_humidity{ams_id}`
- `bambulab_ams_unit_temperature_celsius{ams_id}`
- `bambulab_queue_total`
- `bambulab_queue_estimated_seconds`
- `bambulab_queue_number`
- `bambulab_queue_status`
- `bambulab_queue_position`

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
pip install -r requirements-dev.txt
# or: pip install -e .[dev]
pytest -q
```

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
