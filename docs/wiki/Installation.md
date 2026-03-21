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

## Cloud Mode: Getting Credentials

Cloud authentication uses the `bambulab-cloud-auth` tool included in the container image. No local Python installation is required.

```bash
# Step 1: Send verification code to your email
docker run --rm -it \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --send-code

# Step 2: Exchange the code for an access token and save encrypted credentials
docker run --rm -it \
  -v /path/to/config:/config \
  -e BAMBULAB_SECRET_KEY="your-strong-secret-key" \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --code 123456 \
    --serial <printer_serial> --save --secret-key "$BAMBULAB_SECRET_KEY"
```

Mount `/path/to/config` to the same location used by the running exporter so the saved credentials are accessible.

---

## Next Steps

Once the exporter is running, configure Prometheus to scrape it — see [Prometheus Setup](Prometheus-Setup).
