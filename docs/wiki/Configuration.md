# Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in required values.

---

## Core Variables

Printer connection and login variables are **optional** when you connect the printer on the
`/auth` page ([Quick Start](Quick-Start)); settings saved there take precedence over env vars.
The "Required" column below applies to env-variable setups.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_TRANSPORT` | no | `local_mqtt` | Transport: `local_mqtt` or `cloud_mqtt` |
| `BAMBULAB_HOST` | env setup, LAN | - | Printer IP or hostname |
| `BAMBULAB_PORT` | no | `8883` | Printer MQTT TLS port |
| `BAMBULAB_SERIAL` | env setup | - | Printer serial / device ID |
| `BAMBULAB_ACCESS_CODE` | env setup, LAN | - | Printer LAN access code |
| `BAMBULAB_USERNAME` | no | `bblp` | MQTT username |

---

## Cloud MQTT Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_CLOUD_USER_ID` | no | - | Cloud user ID (only for manually obtained tokens) |
| `BAMBULAB_CLOUD_ACCESS_TOKEN` | no | - | Cloud access token (only for manually obtained tokens) |
| `BAMBULAB_CLOUD_MQTT_HOST` | no | `us.mqtt.bambulab.com` | Cloud MQTT broker |
| `BAMBULAB_CLOUD_MQTT_PORT` | no | `8883` | Cloud MQTT TLS port |
| `BAMBULAB_CLOUD_EMAIL` | env OTP flow | - | For the env-variable login flow: the container emails a verification code to it. Not needed with the `/auth` page |
| `BAMBULAB_CLOUD_CODE` | no | - | Verification code for re-auth |

---

## Credential Storage

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_SECRET_KEY` | recommended | - | Encrypts `/auth` page settings and cloud credentials so they survive restarts; keep stable |
| `BAMBULAB_CONFIG_DIR` | no | `/config/bambulab-metrics-exporter` | Config directory |

Files in the config directory (all encrypted with `BAMBULAB_SECRET_KEY`, mode `0600`):

| File | Written by | Purpose |
|------|------------|---------|
| `credentials.enc.json` (`BAMBULAB_CREDENTIALS_FILE`) | cloud login, token refresh, `bambulab-reauth` | Cloud user ID and tokens |
| `connection-overrides.enc.json` | `/auth` page | Connection settings that override env vars; removed by **Reset to env vars** |
| `credentials.enc.json.before-auth-page` | `/auth` page | The credentials that existed before the first page login; restored by **Reset to env vars** |

### Generating `BAMBULAB_SECRET_KEY`

`BAMBULAB_SECRET_KEY` encrypts everything the exporter saves in the config volume: settings entered on the `/auth` page and Bambu Cloud credentials (user ID, tokens). Without it, page settings and cloud logins last only until the next restart.

Generate a strong key with:

```bash
openssl rand -hex 32
```

Add the output to your `.env`:

```dotenv
BAMBULAB_SECRET_KEY=a3f1c8e2d4b7901234567890abcdef1234567890abcdef1234567890abcdef12
```

> **Safety notes:**
> - **Never commit or share this key.** Add `.env` to `.gitignore`.
> - **Keep the key stable.** Changing it will invalidate any encrypted credentials on the config volume; you will need to log in again on the `/auth` page (or run `bambulab-reauth`).

---

## Polling & HTTP

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BAMBULAB_REQUEST_PUSHALL` | no | `true` | Request full snapshot each poll, and the module list (`get_version`) on each connect |
| `POLLING_INTERVAL_SECONDS` | no | `10` | Polling interval (seconds) |
| `REQUEST_TIMEOUT_SECONDS` | no | `8` | Per-cycle timeout (seconds) |
| `LISTEN_HOST` | no | `0.0.0.0` | HTTP bind host |
| `LISTEN_PORT` | no | `9109` | HTTP port |
| `AUTH_ALLOWED_HOSTS` | no | empty | Extra host names allowed for the `/auth` page, comma separated (for example a reverse-proxy name). IP addresses, `localhost`, single-word names (`tower`) and local-network names (`.local`, `.lan`, `.home`, `.internal`, `.home.arpa`) are always allowed; other names get `403` to block DNS-rebinding attacks |

---

## Printer Name & Labels

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PRINTER_NAME_LABEL` | no | empty | **Canonical** custom printer name label; takes priority over all other sources |
| `BAMBULAB_PRINTER_NAME` | no | `auto` | Discovered printer name (auto-persisted) |
| `BAMBULAB_PRINTER_MODEL` | no | empty | Model hint used when the serial prefix is not recognized (for example `P2S`, `X1 Carbon`, `BL-P001`). Filled by cloud discovery; unrecognized values are ignored |

> **Note:** `PRINTER_NAME_LABEL` is the current canonical variable for setting a stable printer label. Older examples or documentation may reference `PRINTER_NAME`; that name is no longer used. Use `PRINTER_NAME_LABEL` in all new configurations.

> **Deprecated (no effect):** `SITE` and `LOCATION` variables appeared in older configurations but are **inactive** and have no effect. Do not set them; they are ignored by the exporter.

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

## Minimal setup (`/auth` page)

```dotenv
BAMBULAB_SECRET_KEY=<openssl rand -hex 32>
```

Mount the config volume, start the container and connect the printer at `/auth`.

## Minimal LAN `.env`

```dotenv
BAMBULAB_TRANSPORT=local_mqtt
BAMBULAB_HOST=192.0.2.100
BAMBULAB_SERIAL=01P00A000000000
BAMBULAB_ACCESS_CODE=12345678
```

## Minimal Cloud `.env`

```dotenv
BAMBULAB_TRANSPORT=cloud_mqtt
BAMBULAB_SERIAL=01P00A000000000
BAMBULAB_SECRET_KEY=<openssl rand -hex 32>
BAMBULAB_CLOUD_EMAIL=you@example.com
```

The container emails a verification code on first start; see
[Installation](Installation#cloud-mode-email-code-flow).

---

## Startup Preflight

The web server starts first and stays up; connecting happens in the background. `/auth/status`
reports the state. Settings saved on the `/auth` page override env vars until reset there.

**LAN mode:** Missing settings → `setup_required` (fill in on `/auth`). Connection failure →
error logged, retried every 60 seconds.

**Cloud mode:** credentials are tried in order: env tokens, encrypted credential file (if it
holds different, newer tokens), refresh token, then `BAMBULAB_CLOUD_EMAIL` + `BAMBULAB_CLOUD_CODE`.
- Only a refusal by the Bambu broker counts as rejected credentials. An unreachable broker, a
  network or API outage, or a printer that does not answer (powered off) is retried every
  60 seconds and never sends a code.
- If the broker rejects the credentials while the exporter is running (expired or revoked
  token), it re-validates the same way: refresh token first, then the re-authentication state.
- If the credentials are rejected, the exporter logs a re-authentication banner and **waits**;
  log in on the `/auth` page (or run `docker exec -it <container> bambulab-reauth`) and it
  resumes. While waiting it still re-checks every 5 minutes.
- If only `BAMBULAB_CLOUD_EMAIL` is set, at most one verification code is sent per container
  start, and each `BAMBULAB_CLOUD_CODE` value is tried once.
- On success → credentials saved encrypted, synced to `.env`. Values entered on the `/auth`
  page are never written to `.env`.

**Invalid values** (for example `BAMBULAB_TRANSPORT=lan`) no longer stop the container: the
exporter starts with defaults, logs the error, and `/auth/status` reports `setup_required`.
