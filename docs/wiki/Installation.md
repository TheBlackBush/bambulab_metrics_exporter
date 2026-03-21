# Installation

## Prerequisites

- Python 3.11+ (for local/virtualenv install)
- Docker + Docker Compose (for container install)
- Bambu Lab printer accessible via LAN or cloud MQTT
- Printer serial number and LAN access code (or cloud credentials)

---

## Option 1: Local (virtualenv)

```bash
# 1. Copy and edit the environment file
cp .env.example .env
# edit .env — set BAMBULAB_HOST, BAMBULAB_SERIAL, BAMBULAB_ACCESS_CODE at minimum

# 2. Create a virtual environment and install
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# or editable install:
# pip install -e .

# 3. Run
bambulab-exporter
```

Open http://localhost:9109/ to verify the exporter is running.

---

## Option 2: Docker

```bash
docker build -t bambulab-metrics-exporter:latest .
docker run --rm -p 9109:9109 --env-file .env bambulab-metrics-exporter:latest
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

## Pre-built Container (GHCR)

```bash
docker pull ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

---

## Cloud Mode: Getting Credentials

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Step 1: send verification code to email
bambulab-cloud-auth --email you@example.com --send-code

# Step 2: exchange code for access token and save encrypted credentials
bambulab-cloud-auth --email you@example.com --code 123456 \
  --serial <printer_serial> --save --secret-key "$BAMBULAB_SECRET_KEY"
```

---

## Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: bambulab
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs:
      - targets: ["bambulab-metrics-exporter:9109"]
```

Sample also available at `examples/prometheus/prometheus.scrape.yml`.
