# Troubleshooting

---

## Exporter Won't Start

**Missing required env vars**
- LAN: `BAMBULAB_HOST`, `BAMBULAB_SERIAL`, `BAMBULAB_ACCESS_CODE`
- Cloud: `BAMBULAB_SERIAL`, `BAMBULAB_SECRET_KEY`, `BAMBULAB_CLOUD_EMAIL`, plus credentials or encrypted file

**`BAMBU CLOUD RE-AUTHENTICATION REQUIRED` in the logs**
1. Open `http://<docker-host>:9109/auth`, choose **Bambu Cloud**, click **Send code**, enter the code and log in
   (shell alternative: `docker exec -it <container> bambulab-reauth`)
2. The exporter resumes within a few seconds; no restart needed
3. `GET /auth/status` shows the current state (`auth_required` until you log in)
4. If newer credentials were saved but the container template still sets old
   `BAMBULAB_CLOUD_ACCESS_TOKEN` / `BAMBULAB_CLOUD_REFRESH_TOKEN` values, the exporter now
   falls back to the stored ones. Leave those template fields empty after the first login.

**`Cloud token refresh failed due to a network or API outage`**
- The credentials were not rejected; the cloud API was unreachable. The exporter retries every
  60 seconds without sending verification emails. Check DNS and outbound HTTPS.

**`Missing settings` / status `setup_required`**
- Required settings are missing. Fill them in on the `/auth` page or set the env vars.

**The exporter ignores my changed env vars**
- Settings saved on the `/auth` page override env vars. Use **Reset to env vars** on the page.

**LAN connection preflight fails**
- Verify printer IP and LAN access code (Settings → Network on printer)
- Check port 8883: `nc -zv <printer_ip> 8883`
- TLS cert verification is intentionally disabled

---

## No Metrics / Empty /metrics

- Check `/ready`: "Warming Up" means still connecting
- Check `bambulab_exporter_scrape_success`; if 0, look at logs
- Set `LOG_LEVEL=DEBUG` for verbose output
- Verify `BAMBULAB_REQUEST_PUSHALL=true` (default)

---

## Stale Metrics

- Check `bambulab_printer_connected`; if 0, MQTT session dropped
- Cloud: access token may have expired; restart, and if the log shows the re-authentication banner log in on the `/auth` page
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

Fan values use step-aware normalization (raw 0–15 → nearest-10 %); this is intentional.

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
