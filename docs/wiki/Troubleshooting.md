# Troubleshooting

---

## Connection Problems

The exporter never exits on connection problems: the web server stays up and the status page
(`/`) and `/auth/status` show what is wrong.

**Status page shows "Printer not configured"** (`/auth/status`: `setup_required`)
- No printer is configured yet, or a required value is missing or invalid. Connect the printer
  on the `/auth` page, or set the env vars (LAN: `BAMBULAB_HOST`, `BAMBULAB_SERIAL`,
  `BAMBULAB_ACCESS_CODE`; see [Installation](Installation#environment-variable-setup-optional)).

**Printer settings are lost after a restart**
- Set `BAMBULAB_SECRET_KEY` and mount the config volume
  (`/config/bambulab-metrics-exporter`). Without the key, `/auth` page settings and cloud logins
  last only until the next restart.

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

**The exporter ignores my changed env vars**
- Settings saved on the `/auth` page override env vars. Use **Reset to env vars** on the page.

**LAN connection preflight fails**
- The exporter keeps running and retries every 60 seconds; `/auth/status` shows `error`
- Verify printer IP and LAN access code (Settings → Network on printer), or fix them on `/auth`
- Check port 8883: `nc -zv <printer_ip> 8883`
- TLS cert verification is intentionally disabled

**`/auth` returns 403 `host_not_allowed`**
- The page only accepts IP addresses and local-network host names (DNS-rebinding protection)
- Add the name you use (for example a reverse-proxy host) to `AUTH_ALLOWED_HOSTS`

**`bambulab-reauth` saved credentials but the exporter cannot read them**
- `docker exec` runs as root. The command hands the files to `PUID`/`PGID`, or to the owner of
  the config folder when those are not set in the container. If both are unknown, run it as
  the exporter user: `docker exec -it -u 99:100 <container> bambulab-reauth`

---

## No Metrics / Empty /metrics

- Check `/ready`: "Warming Up" means still connecting
- Check `bambulab_exporter_scrape_success`; if 0, look at logs
- Set `LOG_LEVEL=DEBUG` for verbose output
- Verify `BAMBULAB_REQUEST_PUSHALL=true` (default)

---

## Stale Metrics

- Check `bambulab_printer_connected`; if 0, the MQTT session dropped
- Cloud: an expired or revoked token is detected automatically; the exporter refreshes it, or
  shows **Login required** on the `/auth` page if you need to log in again
- Values can stay at their last reading while disconnected; check `bambulab_printer_connected`
  before trusting them
- Check `bambulab_exporter_last_success_unixtime` for staleness

---

## Wrong Printer Model

`bambulab_printer_model_info` is missing or shows the wrong model:
- Model is resolved from `product_name` → serial prefix (payload, then `BAMBULAB_SERIAL`) → `BAMBULAB_PRINTER_MODEL` → known `hw_ver`+`project_name` pairs
- When nothing matches, the series is omitted (no guessed model)
- Workaround: set `BAMBULAB_PRINTER_MODEL` to your model (for example `P2S` or `X1 Carbon`)
- Open a GitHub issue with your model and serial prefix (first 3 characters only)

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

## Grafana AMS Panel Shows Plain Text

- Install the **Business Text** plugin (`marcusolsson-dynamictext-panel`) and set
  `GF_PANELS_DISABLE_SANITIZE_HTML=true` (or `disable_sanitize_html = true` under `[panels]` in
  `grafana.ini`), then restart Grafana. See [Grafana Dashboard](Grafana-Dashboard).

---

## Fan Metrics Look Wrong

Fan values use step-aware normalization (raw 0–15 → nearest-10 %); this is intentional.

---

## Debugging

Set `LOG_LEVEL=DEBUG` on the container (Unraid: **Log Level** in the template), restart it,
then read the logs:

```bash
docker logs -f bambulab-exporter

# Quick checks
curl http://localhost:9109/auth/status
curl http://localhost:9109/metrics | grep bambulab_printer
curl http://localhost:9109/ready
```

---

## Getting Help

Open an issue: https://github.com/TheBlackBush/bambulab_metrics_exporter/issues

Include: printer model + firmware, transport mode (local or cloud), and logs with `LOG_LEVEL=DEBUG`. Remove your serial number, IP addresses, access code, email and tokens first.
