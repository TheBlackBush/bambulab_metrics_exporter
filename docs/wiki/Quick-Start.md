# Quick Start

Get the exporter running in under 5 minutes.

---

## Prerequisites

- Docker installed
- Bambu Lab printer on your LAN (or cloud credentials)
- Printer **serial number** and **LAN access code**
  - Find these in: Bambu Studio → Device → LAN Mode, or on the printer at **Settings → Network**

---

## Mode Selection

The exporter supports two transport modes. **`local_mqtt` is the default** — no extra configuration needed if your printer is on the same LAN.

| Mode | `BAMBULAB_TRANSPORT` value | When to use |
|------|---------------------------|-------------|
| **Local** (default) | `local_mqtt` | Printer is on your LAN and LAN Mode is enabled |
| **Cloud** | `cloud_mqtt` | Printer is not directly reachable (remote location, CGNAT, etc.) |

Omitting `BAMBULAB_TRANSPORT` is equivalent to setting it to `local_mqtt`.

---

## Local Mode (default)

### Step 1: Create your `.env` file

```dotenv
BAMBULAB_TRANSPORT=local_mqtt   # optional — this is the default
BAMBULAB_HOST=192.168.1.100     # your printer's IP
BAMBULAB_SERIAL=01P00A000000000 # your printer serial
BAMBULAB_ACCESS_CODE=12345678   # LAN access code
```

**All three of `BAMBULAB_HOST`, `BAMBULAB_SERIAL`, and `BAMBULAB_ACCESS_CODE` are required** for Local mode. The container will refuse to start if any are missing.

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

## Cloud Mode

Use this mode when the printer is not directly reachable over LAN.

### Required env vars for Cloud mode

| Variable | Required | Description |
|----------|----------|-------------|
| `BAMBULAB_TRANSPORT` | ✅ | Must be `cloud_mqtt` |
| `BAMBULAB_SERIAL` | ✅ | Printer serial number |
| `BAMBULAB_SECRET_KEY` | ✅ | Encrypts stored credentials — keep stable |
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

**Step 1 — Send the verification code:**

```bash
docker run --rm -it \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --send-code
```

**Step 2 — Exchange the code and save credentials:**

```bash
docker run --rm -it \
  -v /your/config/path:/config \
  -e BAMBULAB_SECRET_KEY="your-strong-secret-key" \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --code 123456 \
    --serial <serial> --save --secret-key "$BAMBULAB_SECRET_KEY"
```

Mount `/your/config/path` to the same path the running exporter uses for its config volume so the saved credentials are picked up automatically.

**Step 3 — Start the exporter:**

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

### BAMBULAB_CLOUD_CODE lifecycle

The container handles cloud authentication natively on startup — no manual `bambulab-cloud-auth` runs required if you use this flow.

**Initial authentication (container-native OTP flow):**

1. Set `BAMBULAB_CLOUD_EMAIL` in your `.env`. **Do not set `BAMBULAB_CLOUD_CODE`.**
2. Start the container. Because no valid credentials exist yet, it sends a verification code to your Bambu account email, then exits.
3. Check your email for the code.
4. Add `BAMBULAB_CLOUD_CODE=<code from email>` to your `.env` and restart the container.
5. The container authenticates, persists encrypted credentials to the config volume, and continues running normally.
6. **Remove `BAMBULAB_CLOUD_CODE` from `.env`** — codes are single-use. It is not needed for steady-state operation.

After step 6, the exporter loads stored credentials automatically on every restart.

**When BAMBULAB_CLOUD_CODE is needed again:**

Repeat the flow above if any of the following occur:

- Stored credentials are missing or cleared (fresh config volume, accidental deletion).
- The Bambu Cloud session has expired or the account password was changed.
- `BAMBULAB_SECRET_KEY` was changed — the encrypted credential file can no longer be decrypted.

In all these cases, start the container without `BAMBULAB_CLOUD_CODE` to trigger a new code delivery, then follow steps 3–6 above.

---

## Next Steps

| What | Where |
|------|-------|
| Add to Prometheus | [Prometheus Setup](Prometheus-Setup) |
| Tune all env vars | [Configuration](Configuration) |
| Import Grafana dashboard | [Grafana Dashboard](Grafana-Dashboard) |
| Something not working | [Troubleshooting](Troubleshooting) |
