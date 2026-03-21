# Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in required values.

---

## Core Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_TRANSPORT` | no | `local_mqtt` | Transport: `local_mqtt` or `cloud_mqtt` |
| `BAMBULAB_HOST` | yes (LAN) | — | Printer IP or hostname |
| `BAMBULAB_PORT` | no | `8883` | Printer MQTT TLS port |
| `BAMBULAB_SERIAL` | yes | — | Printer serial / device ID |
| `BAMBULAB_ACCESS_CODE` | yes (LAN) | — | Printer LAN access code |
| `BAMBULAB_USERNAME` | no | `bblp` | MQTT username |

---

## Cloud MQTT Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_CLOUD_USER_ID` | yes (cloud) | — | Cloud user ID |
| `BAMBULAB_CLOUD_ACCESS_TOKEN` | yes (cloud) | — | Cloud access token |
| `BAMBULAB_CLOUD_MQTT_HOST` | no | `us.mqtt.bambulab.com` | Cloud MQTT broker |
| `BAMBULAB_CLOUD_MQTT_PORT` | no | `8883` | Cloud MQTT TLS port |
| `BAMBULAB_CLOUD_EMAIL` | conditional | — | Required only when cloud credentials are missing or expired (triggers re-auth flow) |
| `BAMBULAB_CLOUD_CODE` | no | — | Verification code for re-auth |

---

## Credential Storage

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_SECRET_KEY` | yes (cloud) | — | Encryption key for local credentials |
| `BAMBULAB_CONFIG_DIR` | no | `/config/bambulab-metrics-exporter` | Config directory |

---

## Polling & HTTP

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_REQUEST_PUSHALL` | no | `true` | Request full snapshot each poll |
| `POLLING_INTERVAL_SECONDS` | no | `10` | Polling interval (seconds) |
| `REQUEST_TIMEOUT_SECONDS` | no | `8` | Per-cycle timeout (seconds) |
| `LISTEN_HOST` | no | `0.0.0.0` | HTTP bind host |
| `LISTEN_PORT` | no | `9109` | HTTP port |

---

## Printer Name & Labels

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PRINTER_NAME_LABEL` | no | empty | **Canonical** custom printer name label; takes priority over all other sources |
| `BAMBULAB_PRINTER_NAME` | no | `auto` | Discovered printer name (auto-persisted) |

> **Note:** `PRINTER_NAME_LABEL` is the current canonical variable for setting a stable printer label. Older examples or documentation may reference `PRINTER_NAME` — that name is no longer used. Use `PRINTER_NAME_LABEL` in all new configurations.

> **Deprecated — no effect:** `SITE` and `LOCATION` variables appeared in older configurations but are **inactive** and have no effect. Do not set them; they are ignored by the exporter.

All metrics include `printer_name` and `serial` labels.

---

## Logging & Unraid

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `PUID` | `99` | User ID for container runtime |
| `PGID` | `100` | Group ID for container runtime |
| `UMASK` | `002` | File creation mask |

---

## Minimal LAN `.env`

```dotenv
BAMBULAB_TRANSPORT=local_mqtt
BAMBULAB_HOST=192.168.1.100
BAMBULAB_SERIAL=01P00A000000000
BAMBULAB_ACCESS_CODE=12345678
```

## Minimal Cloud `.env`

```dotenv
BAMBULAB_TRANSPORT=cloud_mqtt
BAMBULAB_SERIAL=01P00A000000000
BAMBULAB_SECRET_KEY=your-strong-key
BAMBULAB_CLOUD_EMAIL=you@example.com
BAMBULAB_CLOUD_USER_ID=<uid>
BAMBULAB_CLOUD_ACCESS_TOKEN=<access_token>
BAMBULAB_CLOUD_MQTT_HOST=us.mqtt.bambulab.com
```

---

## Startup Preflight

**LAN mode:** Missing vars → clear error. Connection failure → troubleshooting message.

**Cloud mode:** Missing/invalid credentials → automatic re-auth triggered.
- Requires `BAMBULAB_CLOUD_EMAIL`
- If `BAMBULAB_CLOUD_CODE` missing → exporter sends code email and exits with restart instructions
- On success → credentials saved encrypted, synced to `.env`
