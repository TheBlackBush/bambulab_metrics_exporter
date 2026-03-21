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

### OTP lifecycle — when re-authentication is required

Once credentials are saved, the exporter reuses them on every restart without prompting for a new code. Re-authentication is required only when:

- Stored credentials are missing (e.g., fresh config volume, no prior `--save` run).
- Stored credentials are expired or invalidated (e.g., Bambu Cloud session ended, password changed).
- `BAMBULAB_SECRET_KEY` was changed — the encrypted credential file can no longer be decrypted.

In these cases, the container can trigger re-auth automatically on startup:

1. Set `BAMBULAB_CLOUD_EMAIL` in your `.env`.
2. Start the container — if credentials are absent/invalid, it sends a code to your email and exits with instructions.
3. Add `BAMBULAB_CLOUD_CODE=<code from email>` to `.env` and restart.
4. The container logs in, persists credentials, and continues running normally.
5. **Remove `BAMBULAB_CLOUD_CODE`** after a successful start — codes are single-use.

---

## Next Steps

Once the exporter is running, configure Prometheus to scrape it — see [Prometheus Setup](Prometheus-Setup).
For a full env var reference see [Configuration](Configuration).
