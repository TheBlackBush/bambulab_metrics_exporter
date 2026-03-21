# Quick Start

Get the exporter running in under 5 minutes.

---

## Prerequisites

- Docker installed
- Bambu Lab printer on your LAN (or cloud credentials)
- Printer **serial number** and **LAN access code**
  - Find these in: Bambu Studio → Device → LAN Mode, or on the printer at **Settings → Network**

---

## Step 1: Create your `.env` file

```dotenv
BAMBULAB_TRANSPORT=local_mqtt
BAMBULAB_HOST=192.168.1.100     # your printer's IP
BAMBULAB_SERIAL=01P00A000000000 # your printer serial
BAMBULAB_ACCESS_CODE=12345678   # LAN access code
```

## Step 2: Run the container

```bash
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  --env-file .env \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

## Step 3: Verify it's working

```bash
curl http://localhost:9109/health
curl http://localhost:9109/metrics | grep bambulab_printer_connected
```

You should see `bambulab_printer_connected 1` in the metrics output.

---

## Cloud Mode

If your printer is only accessible via the Bambu Cloud, use the `bambulab-cloud-auth` tool bundled in the container image to obtain credentials — no local Python installation required.

```bash
# 1. Send a verification code to your email
docker run --rm -it \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --send-code

# 2. Exchange the code for credentials (saves to mounted /config volume)
docker run --rm -it \
  -v /your/config/path:/config \
  -e BAMBULAB_SECRET_KEY="your-strong-secret-key" \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --code 123456 \
    --serial <serial> --save --secret-key "$BAMBULAB_SECRET_KEY"
```

See [Configuration](Configuration) for the full cloud variable reference.

---

## Next Steps

| What | Where |
|------|-------|
| Add to Prometheus | [Prometheus Setup](Prometheus-Setup) |
| Tune all env vars | [Configuration](Configuration) |
| Import Grafana dashboard | [Grafana Dashboard](Grafana-Dashboard) |
| Something not working | [Troubleshooting](Troubleshooting) |
