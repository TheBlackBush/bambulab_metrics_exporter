# Quick Start

Get the exporter running in under 5 minutes.

---

## Prerequisites

- Docker installed (recommended) or Python 3.11+
- Bambu Lab printer on your LAN (or cloud credentials)
- Printer **serial number** and **LAN access code**
  - Find these in: Bambu Studio → Device → LAN Mode, or on the printer at **Settings → Network**

---

## Fastest Path: Docker

### 1. Create your `.env` file

```dotenv
BAMBULAB_TRANSPORT=local_mqtt
BAMBULAB_HOST=192.168.1.100     # your printer's IP
BAMBULAB_SERIAL=01P00A000000000 # your printer serial
BAMBULAB_ACCESS_CODE=12345678   # LAN access code
```

### 2. Run the container

```bash
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  --env-file .env \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

### 3. Verify it's working

```bash
curl http://localhost:9109/health
curl http://localhost:9109/metrics | grep bambulab_printer_connected
```

You should see `bambulab_printer_connected 1` in the metrics output.

---

## Cloud Mode

If your printer is only accessible via the Bambu Cloud:

1. Clone the repo and install the package:
   ```bash
   git clone https://github.com/TheBlackBush/bambulab_metrics_exporter.git
   cd bambulab_metrics_exporter
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
2. Obtain cloud credentials:
   ```bash
   bambulab-cloud-auth --email you@example.com --send-code
   bambulab-cloud-auth --email you@example.com --code 123456 \
     --serial <serial> --save --secret-key your-strong-key
   ```
3. See [Configuration](Configuration) for the full cloud variable reference.

---

## Next Steps

| What | Where |
|------|-------|
| Add to Prometheus | [Prometheus Setup](Prometheus-Setup) |
| Tune all env vars | [Configuration](Configuration) |
| Import Grafana dashboard | [Grafana Dashboard](Grafana-Dashboard) |
| Something not working | [Troubleshooting](Troubleshooting) |
