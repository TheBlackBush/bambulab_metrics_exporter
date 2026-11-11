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

**Too many codes requested**
- The `/auth` page limits verification emails: 5 sends 60 seconds apart, then a 10 minute wait,
  then a 1 hour wait after each later round of 5. Rejected sends count too. The limit survives
  restarts and is reset only by a successful login on the page. The **Send code** button is
  active when the page loads; the time left appears on it after you press it. A press during
  a wait is refused and does not use up a try. Wait for it, or use `bambulab-reauth` in the
  container, which is a separate path that this limit does not apply to.
  To clear the limit by hand, stop the container, delete `send-code-limit.json` from the config
  directory, and start it again. Deleting it while the container runs has no effect.

**The exporter ignores my changed env vars**
- Settings saved on the `/auth` page override env vars. Use **Reset to env vars** on the page.

**LAN connection preflight fails**
- The exporter keeps running and retries every 60 seconds; `/auth/status` shows `error`
- Verify printer IP and LAN access code (Settings → Network on printer), or fix them on `/auth`
- Check port 8883: `nc -zv <printer_ip> 8883`
- TLS cert verification is intentionally disabled

**`/auth` or `/diagnostics` returns 403 `host_not_allowed`**
- The page only accepts IP addresses and local-network host names (DNS-rebinding protection)
- Add the name you use (for example a reverse-proxy host) to `AUTH_ALLOWED_HOSTS`

**`bambulab-reauth` saved credentials but the exporter cannot read them**
- `docker exec` runs as root. The command hands the files to `PUID`/`PGID`, or to the owner of
  the config folder when those are not set in the container. If both are unknown, run it as
  the exporter user: `docker exec -it -u 99:100 <container> bambulab-reauth`

---

## Several Printers in One Exporter

- A printer picked on `/auth` disappears after a restart: set `BAMBULAB_SECRET_KEY`. Without it the
  printer list lives in memory only.
- One printer shows an error on the page while others work: each printer has its own connection and
  retries on its own; the status page and `printers` in `/auth/status` list each state. The top
  level `state` is the worst one.
- All cloud printers show **Login required**: they share one Bambu account, so one login on `/auth`
  restores all of them. LAN printers are not affected.
- Saving a selection is refused when the account device list is empty or the latest refresh failed
  (the picker then says the list is the last known one). Try again in a minute. A cloud printer that
  left the account can still be removed.
- **The saved printer list could not be read** on `/auth`: the exporter runs the env-var printer (or
  nothing) because `printers.enc.json` did not decrypt or is damaged. Usually `BAMBULAB_SECRET_KEY`
  changed or is missing: restore it and restart. The log names the error type. If you save a new list
  or reset instead, the old file is kept as `printers.enc.json.bad`.
- A serial is either cloud or LAN, never both: remove the printer first to change how it connects.
- Two printers can have the same `printer_name`; filter on `serial` to separate them.
- Several printers per exporter have not been validated on real hardware. If one misbehaves, run it
  in its own container.

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

# Diagnostic report as a file (sanitized, ready to attach to an issue)
curl -o diagnostics.json "http://localhost:9109/diagnostics/report?download=1"
```

---

## "Unsupported printer" on the Connection Page

The exporter does not recognize the printer's model, from its serial number or from the data it
sends. It still exports the metrics it can read, but model-specific ones (chamber, rack, extra
fans) may be missing or wrong. Click **Run diagnostics** under the label and send the report with
a GitHub issue, so the model can be added.

---

## Getting Help

Open the **Diagnostics** page (button on the status page, or `/diagnostics`), run a
[Diagnostic Report](Diagnostic-Report), check it, and click **Create GitHub issue**, or attach it
to a [new issue](https://github.com/TheBlackBush/bambulab_metrics_exporter/issues/new?template=diagnostic.yml)
yourself.
It holds the printer model, firmware, connection state, recent exporter logs and the printer's
data, with serials, addresses, names and credentials removed.

Without a browser, download the report with
`curl -o diagnostics.json "http://localhost:9109/diagnostics/report?download=1"` and attach the
file to the issue.

If you add more logs (`LOG_LEVEL=DEBUG`), remove your serial number, IP addresses, access code,
email and tokens first.
