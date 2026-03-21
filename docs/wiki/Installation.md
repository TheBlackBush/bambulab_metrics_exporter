# Installation

## Prerequisites

- Docker + Docker Compose
- Bambu Lab printer accessible via LAN or cloud MQTT
- Printer serial number and LAN access code (or cloud credentials)

---

## Option 1: Pre-built Container (GHCR) — Recommended

```bash
docker pull ghcr.io/theblackbush/bambulab_metrics_exporter:latest
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  --env-file .env \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

Or with Docker Compose:

```bash
docker compose up -d
```

---

## Option 2: Build Locally

```bash
docker build -t bambulab-metrics-exporter:latest .
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  --env-file .env \
  bambulab-metrics-exporter:latest
```

Or with Docker Compose:

```bash
docker compose up -d --build
```

The included `docker-compose.yml` is cloud-first and minimal. Required cloud fields are active; optional fields are commented.

---

## Option 3: Unraid

A ready-to-import Unraid template is included: `unraid-bambulab-metrics-exporter.xml`

1. Go to **Docker → Add Container → Template**
2. Paste the XML content or use Template URL
3. Fill in `BAMBULAB_SECRET_KEY` and required transport fields
4. Start the container and verify `/metrics`

---

## Choosing a Mode

The exporter supports two transport modes. **`local_mqtt` is the default** — it is used when `BAMBULAB_TRANSPORT` is not set or is set to `local_mqtt`.

| Mode | When to use |
|------|-------------|
| **Local** (`local_mqtt`) | Printer is on your LAN with LAN Mode enabled |
| **Cloud** (`cloud_mqtt`) | Printer is remote or not directly reachable |

If `BAMBULAB_TRANSPORT=cloud_mqtt` is not explicitly set, the exporter always falls back to Local mode.

---

### Local Mode — minimum required env vars

```dotenv
BAMBULAB_TRANSPORT=local_mqtt   # optional — this is the default
BAMBULAB_HOST=192.168.1.100     # printer IP/hostname
BAMBULAB_SERIAL=01P00A000000000 # printer serial number
BAMBULAB_ACCESS_CODE=12345678   # LAN access code
```

The container will refuse to start if any of these three values are missing while in Local mode.

---

### Cloud Mode — minimum required env vars

```dotenv
BAMBULAB_TRANSPORT=cloud_mqtt
BAMBULAB_SERIAL=01P00A000000000   # printer serial number
BAMBULAB_SECRET_KEY=<32-byte hex> # generated with: openssl rand -hex 32
BAMBULAB_CLOUD_EMAIL=you@example.com
```

After the first successful authentication, credentials are stored encrypted in the config volume. On subsequent starts the stored credentials are loaded automatically — no OTP needed unless re-authentication is required (see below).

> **Important:** keep `BAMBULAB_SECRET_KEY` stable. Changing it invalidates the stored credential file and forces a full re-authentication.

---

## Cloud Mode: Getting Credentials (OTP Flow)

Cloud authentication uses the `bambulab-cloud-auth` tool included in the container image. No local Python installation is required.

**Step 1 — Send a verification code to your Bambu account email:**

```bash
docker run --rm -it \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --send-code
```

**Step 2 — Exchange the code and save encrypted credentials:**

```bash
docker run --rm -it \
  -v /path/to/config:/config \
  -e BAMBULAB_SECRET_KEY="your-strong-secret-key" \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --code 123456 \
    --serial <printer_serial> --save --secret-key "$BAMBULAB_SECRET_KEY"
```

Mount `/path/to/config` to the same location used by the running exporter so the saved credentials are accessible.

### BAMBULAB_CLOUD_CODE lifecycle

`BAMBULAB_CLOUD_CODE` is a **one-time bootstrap variable**. It is only needed during initial authentication and must be removed from steady-state config afterward.

**First-time setup (container-native OTP flow):**

1. Set `BAMBULAB_CLOUD_EMAIL` in your `.env`. **Do not set `BAMBULAB_CLOUD_CODE`.**
2. Start the container. It detects no valid credentials, sends a verification code to your Bambu account email, and exits.
3. Check your email for the code.
4. Add `BAMBULAB_CLOUD_CODE=<code from email>` to your `.env` and restart the container.
5. The container authenticates, persists encrypted credentials to the config volume, and continues running normally.
6. **Remove `BAMBULAB_CLOUD_CODE` from `.env`** — it is not needed again for normal operation.

After this, the exporter reuses stored credentials automatically on every restart.

**When BAMBULAB_CLOUD_CODE is needed again:**

Repeat the flow above if any of the following occur:

- Stored credentials are missing or cleared (fresh config volume, accidental deletion).
- The Bambu Cloud session has expired or the account password was changed.
- `BAMBULAB_SECRET_KEY` was changed — the encrypted credential file can no longer be decrypted.

In all cases: start the container without `BAMBULAB_CLOUD_CODE` to trigger a new code delivery, then follow steps 3–6 above.

---

## Next Steps

Once the exporter is running, configure Prometheus to scrape it — see [Prometheus Setup](Prometheus-Setup).
For a full env var reference see [Configuration](Configuration).
