# Troubleshooting

---

## Exporter Won't Start

**Missing required env vars**
- LAN: `BAMBULAB_HOST`, `BAMBULAB_SERIAL`, `BAMBULAB_ACCESS_CODE`
- Cloud: `BAMBULAB_SERIAL`, `BAMBULAB_SECRET_KEY`, `BAMBULAB_CLOUD_EMAIL`, plus credentials or encrypted file

**Cloud re-auth loop**
1. Check email for the verification code
2. Add `BAMBULAB_CLOUD_CODE=<code>` to `.env` and restart
3. On success, credentials are saved encrypted — code is no longer needed

**LAN connection preflight fails**
- Verify printer IP and LAN access code (Settings → Network on printer)
- Check port 8883: `nc -zv <printer_ip> 8883`
- TLS cert verification is intentionally disabled

---

## No Metrics / Empty /metrics

- Check `/ready` — "Warming Up" means still connecting
- Check `bambulab_exporter_scrape_success` — if 0, look at logs
- Set `LOG_LEVEL=DEBUG` for verbose output
- Verify `BAMBULAB_REQUEST_PUSHALL=true` (default)

---

## Stale Metrics

- Check `bambulab_printer_connected` — if 0, MQTT session dropped
- Cloud: access token may have expired; restart to trigger re-auth
- Check `bambulab_exporter_last_success_unixtime` for staleness

---

## Wrong Printer Model

`bambulab_printer_model_info` shows `unknown`:
- Model resolved from `product_name → hw_ver+project_name → SN prefix`
- Open a GitHub issue with your model and serial prefix (first 3 chars)

---

## AMS Metrics Missing

- Verify AMS is visible in Bambu Studio
- Enable `LOG_LEVEL=DEBUG` and look for AMS parsing warnings
- Gen2 drying metrics only emit when `ams_info` is present in the MQTT payload

---

## Docker / Unraid Permission Issues

- Set `PUID`/`PGID` to match the host user owning the config directory
- Defaults: `PUID=99`, `PGID=100`

---

## Fan Metrics Look Wrong

Fan values use step-aware normalization (raw 0–15 → nearest-10 %) — this is intentional.

---

## Debugging

```bash
# Verbose logging
LOG_LEVEL=DEBUG bambulab-exporter

# Quick checks
curl http://localhost:9109/metrics | grep bambulab_printer
curl http://localhost:9109/health
curl http://localhost:9109/ready
```

---

## Getting Help

Open an issue: https://github.com/TheBlackBush/bambulab_metrics_exporter/issues

Include: printer model + firmware, transport mode, logs with `LOG_LEVEL=DEBUG`, sanitized `.env`.
