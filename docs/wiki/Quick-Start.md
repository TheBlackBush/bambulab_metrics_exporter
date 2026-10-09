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

The exporter connects right away. Details: [the `/auth` page](#connecting-from-the-browser-the-auth-page-recommended).

### Step 4: Verify

```bash
curl http://localhost:9109/health
curl http://localhost:9109/metrics | grep bambulab_printer_connected
```

You should see `bambulab_printer_connected 1`.

---

## Alternative: environment variables

Everything below is optional. Use env vars when you prefer a fully scripted setup; settings
saved on the `/auth` page take precedence over them.

### Mode selection

| Mode | `BAMBULAB_TRANSPORT` value | When to use |
|------|---------------------------|-------------|
| **Local** (default) | `local_mqtt` | Printer is on your LAN and LAN Mode is enabled |
| **Cloud** | `cloud_mqtt` | Printer is not directly reachable (remote location, CGNAT, etc.) |

Omitting `BAMBULAB_TRANSPORT` is equivalent to setting it to `local_mqtt`.

---

## Local Mode with env vars

### Step 1: Create your `.env` file

```dotenv
BAMBULAB_TRANSPORT=local_mqtt   # optional: this is the default
BAMBULAB_HOST=192.168.1.100     # your printer's IP
BAMBULAB_SERIAL=01P00A000000000 # your printer serial
BAMBULAB_ACCESS_CODE=12345678   # LAN access code
```

**All three of `BAMBULAB_HOST`, `BAMBULAB_SERIAL`, and `BAMBULAB_ACCESS_CODE` are needed** for Local mode with env vars. If one is missing, the exporter keeps running and waits (the status page shows **Printer not configured**) until it is set or the printer is connected on the `/auth` page.

### Step 2: Run the container

```bash
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  --env-file .env \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

### Step 3: Verify it's working

```bash
curl http://localhost:9109/health
curl http://localhost:9109/metrics | grep bambulab_printer_connected
```

You should see `bambulab_printer_connected 1` in the metrics output.

---

## Cloud Mode with env vars

Use this mode when the printer is not directly reachable over LAN. The `/auth` page is the
easiest way to log in; the variables below are for env-variable setups.

### Env vars for Cloud mode

| Variable | Required | Description |
|----------|----------|-------------|
| `BAMBULAB_TRANSPORT` | ✅ | Must be `cloud_mqtt` |
| `BAMBULAB_SERIAL` | ✅ | Printer serial number |
| `BAMBULAB_SECRET_KEY` | ✅ | Encrypts stored credentials; keep stable |
| `BAMBULAB_CLOUD_EMAIL` | ✅ (for OTP flow) | Your Bambu account email |
| `BAMBULAB_CLOUD_USER_ID` + `BAMBULAB_CLOUD_ACCESS_TOKEN` | Alternative | Use if you already have tokens |

### Generate a secret key

`BAMBULAB_SECRET_KEY` encrypts your cloud credentials on the config volume. Generate one before proceeding:

```bash
openssl rand -hex 32
```

Add it to your `.env` (and keep it out of version control):

```dotenv
BAMBULAB_SECRET_KEY=<output from above>
```

> **Keep this key stable.** Changing it invalidates stored credentials and requires re-authentication.

### First-time authentication (OTP flow)

Cloud authentication uses a one-time verification code sent to your Bambu account email.

**Step 1: Send the verification code:**

```bash
docker run --rm -it \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --send-code
```

**Step 2: Exchange the code and save credentials:**

```bash
docker run --rm -it \
  -v /your/config/path:/config \
  -e BAMBULAB_SECRET_KEY="your-strong-secret-key" \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --code 123456 \
    --serial <serial> --save --secret-key "$BAMBULAB_SECRET_KEY"
```

Mount `/your/config/path` to the same path the running exporter uses for its config volume so the saved credentials are picked up automatically.

**Step 3: Start the exporter:**

```dotenv
BAMBULAB_TRANSPORT=cloud_mqtt
BAMBULAB_SERIAL=01P00A000000000
BAMBULAB_SECRET_KEY=<your-secret-key>
BAMBULAB_CLOUD_EMAIL=you@example.com
```

```bash
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  -v /your/config/path:/config \
  --env-file .env \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

### Connecting from the browser: the `/auth` page (recommended)

Open `http://<docker-host>:9109/auth` (also linked from the landing page). Choose:

- **Local (LAN):** enter the printer IP, serial number and LAN access code.
- **Bambu Cloud:** enter your account email, click **Send code**, then enter the emailed code in the same form and click **Log in**.
  The serial is optional when the account has a single printer.

The exporter reconnects immediately; no restart needed. When the cloud login fails later
(expired session, changed password, new config volume) the exporter does **not** exit: it logs
a `BAMBU CLOUD RE-AUTHENTICATION REQUIRED` banner and waits until you log in again on the page.

Settings saved on the page are stored encrypted in the config volume and **override** the
container's env vars (including Unraid template values) after restarts. **Reset to env vars**
on the page removes them. Persisting requires `BAMBULAB_SECRET_KEY`; without it, page settings
apply until the next restart.

> **Security:** the page has no login. Anyone who can reach port 9109 can change which printer
> or account the exporter uses. Do not expose the port outside a trusted network. Saved
> secrets are never shown on the page.

Shell alternative (same result, no browser):

```bash
docker exec -it <container> bambulab-reauth
```

Replace `<container>` with your container name (`bambulab-exporter` in the `docker run`
examples, `bambulab-metrics-exporter` with the Compose file). On Unraid, open the container's
**Console** and run `bambulab-reauth`.

### BAMBULAB_CLOUD_CODE lifecycle

The container handles cloud authentication natively on startup; no manual `bambulab-cloud-auth` runs required if you use this flow.

**Initial authentication (container-native OTP flow):**

1. Set `BAMBULAB_CLOUD_EMAIL` in your `.env`. **Do not set `BAMBULAB_CLOUD_CODE`.**
2. Start the container. Because no valid credentials exist yet, it sends one verification code to your Bambu account email, then waits.
3. Check your email for the code.
4. Add `BAMBULAB_CLOUD_CODE=<code from email>` to your `.env` and recreate the container (or use the `/auth` page instead).
5. The container authenticates, persists encrypted credentials to the config volume, and continues running normally.
6. **Remove `BAMBULAB_CLOUD_CODE` from `.env`**: codes are single-use. It is not needed for steady-state operation.

After step 6, the exporter loads stored credentials automatically on every restart.

**When BAMBULAB_CLOUD_CODE is needed again:**

Repeat the flow above if any of the following occur:

- Stored credentials are missing or cleared (fresh config volume, accidental deletion).
- The Bambu Cloud session has expired or the account password was changed.
- `BAMBULAB_SECRET_KEY` was changed: the encrypted credential file can no longer be decrypted.

In all these cases, the simplest fix is the `/auth` page (above). The env-variable flow still works: start the container without `BAMBULAB_CLOUD_CODE` to trigger a new code delivery, then follow steps 3–6.

---

## Next Steps

| What | Where |
|------|-------|
| Add to Prometheus | [Prometheus Setup](Prometheus-Setup) |
| Tune all env vars | [Configuration](Configuration) |
| Import Grafana dashboard | [Grafana Dashboard](Grafana-Dashboard) |
| Something not working | [Troubleshooting](Troubleshooting) |
