# Quick Start

Get the exporter running in under 5 minutes.

---

## Prerequisites

- Docker installed (or Unraid: install the **bambulab-metrics-exporter** template)
- For a LAN connection: the printer's IP, **serial number** and **LAN access code**
  - Find these on the printer at **Settings > Network**, or in Bambu Studio **Device > LAN Mode**
- For a Bambu Cloud connection: your Bambu account email (a verification code is emailed to it)

---

## Recommended: set up in the browser

The exporter only needs a secret key and a config volume to start. You then connect the
printer on the `/auth` page; no printer settings in env vars.

### Step 1: Generate a secret key (once)

```bash
openssl rand -hex 32
```

It encrypts the settings and cloud login saved by the page, so they survive restarts. Keep it;
changing it later means connecting again.

### Step 2: Start the container

```bash
docker run -d \
  --name bambulab-exporter \
  --restart unless-stopped \
  -p 9109:9109 \
  -v /path/to/config:/config/bambulab-metrics-exporter \
  -e BAMBULAB_SECRET_KEY=<your-generated-key> \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

The status page at `http://<docker-host>:9109/` shows **Printer not configured** until a
printer is connected.

### Step 3: Connect the printer

Open `http://<docker-host>:9109/auth` (also linked from the status page) and choose:

- **Local (LAN):** printer IP, serial number and LAN access code.
- **Bambu Cloud:** account email, **Send code**, then the emailed code and **Log in**. The
  serial is optional when the account has a single printer.

The exporter connects right away. Details: [The `/auth` page](#the-auth-page).

### Step 4: Verify

```bash
curl http://localhost:9109/health
curl http://localhost:9109/metrics | grep bambulab_printer_connected
```

You should see `bambulab_printer_connected 1`.

---

## The `/auth` page

Open `http://<docker-host>:9109/auth` (also linked as **Printer Connection** on the status page).

- **Local (LAN):** enter the printer IP, serial number and LAN access code.
- **Bambu Cloud:** enter your account email, click **Send code**, then enter the emailed code in
  the same form and click **Log in**. The serial is only needed when the account has more than
  one printer.

Good to know:

- **No restart needed.** The exporter reconnects as soon as you save.
- **Settings are remembered.** They are stored encrypted in the config volume and survive
  restarts and updates. This needs `BAMBULAB_SECRET_KEY`; without it, page settings apply until
  the next restart.
- **The page wins over env vars.** Page settings override the container's env vars (including
  Unraid template values). **Reset to env vars** on the page removes them.
- **Expired cloud login.** If the login stops working (expired session, changed password, new
  config volume), the exporter keeps running, logs a `BAMBU CLOUD RE-AUTHENTICATION REQUIRED`
  banner, shows **Login required** on the page and waits until you log in again. This is also
  detected while it is running.
- **Security.** The page has no login of its own. Anyone who can reach port 9109 can change which
  printer or account the exporter uses, so keep the port on a trusted network. Saved secrets are
  never shown on the page.
- **Without a browser.** `docker exec -it <container> bambulab-reauth` does the same cloud login
  in a terminal (on Unraid: open the container's **Console** and run `bambulab-reauth`).

---

## Prefer environment variables?

You can also configure the printer with env vars instead of the page, for example in scripted
setups. See [Installation: environment-variable setup](Installation#environment-variable-setup-optional)
and the full [Configuration](Configuration) reference.

---

## Next Steps

| What | Where |
|------|-------|
| Add to Prometheus | [Prometheus Setup](Prometheus-Setup) |
| Tune all env vars | [Configuration](Configuration) |
| Import Grafana dashboard | [Grafana Dashboard](Grafana-Dashboard) |
| Something not working | [Troubleshooting](Troubleshooting) |
