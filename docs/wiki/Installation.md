# Installation

## Prerequisites

- Docker (Docker Compose optional), or Unraid
- A Bambu Lab printer on your LAN (IP, serial number, LAN access code) or linked to your Bambu
  Cloud account
- A secret key, generated once with `openssl rand -hex 32` (see
  [Configuration](Configuration#generating-bambulab_secret_key))

The easiest setup starts the container with only the secret key and a config volume, then
connects the printer on the `/auth` page: see [Quick Start](Quick-Start).

---

## Option 1 (Recommended): Pre-built image (GHCR)

```bash
docker run -d \
  --name bambulab-exporter \
  --restart unless-stopped \
  -p 9109:9109 \
  -v /path/to/config:/config/bambulab-metrics-exporter \
  -e BAMBULAB_SECRET_KEY=<your-generated-key> \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest
```

Then connect the printer at `http://<docker-host>:9109/auth`.

### Development builds

Every push to the `develop` branch publishes a pre-release image after the full test suite
passes:

| Tag | Meaning |
|-----|---------|
| `latest`, `<version>` | Stable releases (recommended) |
| `develop` | Newest `develop` build; changes with every push |
| `develop-<short-sha>` | A specific `develop` commit; never changes |

```bash
docker pull ghcr.io/theblackbush/bambulab_metrics_exporter:develop
```

Development builds can contain unreleased and breaking changes. Use them for testing, and
pin a `develop-<short-sha>` tag if you need a reproducible deployment.

---

## Option 2: Docker Compose

The included `docker-compose.yml` needs only `BAMBULAB_SECRET_KEY`; every other setting is
optional and commented. Put the key in a `.env` file next to it (see `.env.example`), then:

```bash
docker compose up -d          # or: docker compose up -d --build   (build from source)
```

and connect the printer on the `/auth` page. Compose mounts `./config` as the config volume and
includes a `/health` health check.

---

## Option 3: Build locally

```bash
docker build -t bambulab-metrics-exporter:latest .
docker run -d \
  --name bambulab-exporter \
  -p 9109:9109 \
  -v /path/to/config:/config/bambulab-metrics-exporter \
  -e BAMBULAB_SECRET_KEY=<your-generated-key> \
  bambulab-metrics-exporter:latest
```

---

## Option 4: Unraid

A ready-to-import Unraid template is included: `unraid-bambulab-metrics-exporter.xml`

1. On the **Docker** tab, scroll to **Template repositories**, add
   `https://github.com/TheBlackBush/bambulab_metrics_exporter` on a new line and click **Save**.
2. Click **Add Container** and pick **bambulab-metrics-exporter** from the **Template** list.
3. Fill in **Secret Key** (generate once with `openssl rand -hex 32`) and click **Apply**. All
   other fields are optional.
4. Open the container's **WebUI**, click **Printer Connection** and connect the printer on the
   `/auth` page.

---

## Environment-variable setup (optional)

Instead of the `/auth` page, the printer can be configured with env vars. Settings saved on the
page take precedence; **Reset to env vars** on the page switches back.

| Mode | `BAMBULAB_TRANSPORT` | When to use |
|------|----------------------|-------------|
| **Local** (default) | `local_mqtt` (or omit) | Printer is on your LAN with LAN Mode enabled |
| **Cloud** | `cloud_mqtt` | Printer is remote or not directly reachable |

### Local mode

```dotenv
BAMBULAB_HOST=192.0.2.100       # printer IP/hostname
BAMBULAB_SERIAL=01P00A000000000 # printer serial number
BAMBULAB_ACCESS_CODE=12345678   # LAN access code
```

If one of them is missing, the exporter keeps running and waits (the status page shows
**Printer not configured**) until it is set or the printer is connected on the `/auth` page.

### Cloud mode: email-code flow

```dotenv
BAMBULAB_TRANSPORT=cloud_mqtt
BAMBULAB_SERIAL=01P00A000000000
BAMBULAB_SECRET_KEY=<your-generated-key>
BAMBULAB_CLOUD_EMAIL=you@example.com
```

1. Start the container **without** `BAMBULAB_CLOUD_CODE`. It finds no valid credentials, sends
   one verification code to your Bambu account email, and waits.
2. Add `BAMBULAB_CLOUD_CODE=<code from email>` and recreate the container.
3. The container logs in and saves the credentials encrypted in the config volume.
4. **Remove `BAMBULAB_CLOUD_CODE`**: codes are single-use and it is not needed afterwards.

The saved credentials are used on every restart, and the refresh token renews them
automatically. A new code is only needed if the saved credentials are lost (fresh config volume,
changed `BAMBULAB_SECRET_KEY`) or rejected (expired session, changed password). In every case,
logging in on the `/auth` page is the simplest fix.

### Cloud mode: command-line tool

`bambulab-cloud-auth` in the image can obtain and save credentials without starting the
exporter (no local Python needed):

```bash
# 1. send a verification code to your Bambu account email
docker run --rm -it \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --send-code

# 2. exchange the code and save encrypted credentials into the config volume
docker run --rm -it \
  -v /path/to/config:/config/bambulab-metrics-exporter \
  -e BAMBULAB_SECRET_KEY=<your-generated-key> \
  ghcr.io/theblackbush/bambulab_metrics_exporter:latest \
  bambulab-cloud-auth --email you@example.com --code 123456 \
    --serial <printer_serial> --save
```

Use the same config volume and key as the running exporter so it picks the credentials up. For
a running container, `docker exec -it <container> bambulab-reauth` is simpler.

---

## Next Steps

- Configure Prometheus to scrape the exporter: [Prometheus Setup](Prometheus-Setup)
- All settings: [Configuration](Configuration)
- Import the dashboard: [Grafana Dashboard](Grafana-Dashboard)
