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

The same images are published to Docker Hub as
[`blackbush/bambulab_metrics_exporter`](https://hub.docker.com/r/blackbush/bambulab_metrics_exporter), with the same tags. Use
whichever registry you prefer; GHCR has no pull rate limit for public images, Docker Hub limits
anonymous pulls.

### Development builds

Every push to the `develop` branch publishes a pre-release image (to GHCR and Docker Hub) after
the full test suite passes:

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

## Docker networking

The default bridge network is enough unless you use `BAMBULAB_HOST=auto`: the exporter connects
out to the printer (LAN) or to Bambu Cloud, and Docker handles that without extra settings.

One limit: on a bridge network the container does not receive the announcements printers
broadcast on the LAN (SSDP, UDP port 2021). Publishing the port (`-p 2021:2021/udp`) does not
change that, because Docker only forwards traffic addressed to the host itself. This affects
`BAMBULAB_HOST=auto` (see [Automatic address](#automatic-address-auto) below) and the `ssdp`
section of the [diagnostic report](Diagnostic-Report#lan-announcements), which then shows
`none`. To let the container see the announcements, use host networking:

```yaml
services:
  bambulab-metrics-exporter:
    network_mode: host
```

or `docker run --network host ...`. With host networking, `ports:` is ignored: the exporter
listens on port 9109 of the host directly (change it with `LISTEN_PORT`).

**Printer IP keeps changing (DHCP)?** Either of these works without host networking:

- Use a host name instead of an IP (`BAMBULAB_HOST`, or the IP field on the `/auth` page), if
  your router or local DNS gives the printer a stable name.
- Or enter the new IP on the `/auth` page with the same serial and access code: the exporter
  updates that printer and reconnects without a restart.
- Bambu Cloud mode does not depend on the printer's IP at all.
- Or let the exporter follow the printer: set the host to `auto` (next section).

### Automatic address (`auto`)

Set `BAMBULAB_HOST=auto` (or type `auto` as the IP on the `/auth` LAN form) and the exporter
finds the printer from the announcements it broadcasts on the LAN (UDP port 2021), matched by
serial number. It is opt-in: an empty host still means "set it up", and a fixed IP or host name
works as before.

On the `/auth` page, **Find printers on my network** does this for you: pick the printer and the
host is saved as `auto` (or, with **Keep finding it if the address changes** off, as the address
found). The printer list shows the address it found, for example `LAN, auto (found at
192.168.1.50)`, or `auto (not found yet)` with the reason below it.

- In Docker it needs `network_mode: host` (see above). On the default bridge network the
  announcements never reach the container; a fixed IP keeps working there. The scan on `/auth`
  then finds nothing and says so.
- The exporter connects only to the address that sent the announcement, and only if it is a
  private or link-local IPv4 address (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16,
  169.254.0.0/16). If two devices announce the same serial, it does not connect and says so.
- After the printer has been offline for 2 minutes, the exporter connects to a new announced
  address if there is one.
- Certificate check: with `auto`, the exporter checks the printer's TLS certificate during the
  TLS handshake, before it sends the LAN access code. A certificate signed by a Bambu Lab CA
  that the exporter knows must name the printer's serial. Any other certificate is trusted when
  the printer accepts the access code, and its SHA-256 fingerprint is remembered for that
  printer. Later connections must show the same certificate. The exporter ships no Bambu Lab CA
  yet, so today every `auto` printer uses the remembered fingerprint.
- If the certificate changes, the exporter does not connect. The `/auth` page shows
  **Certificate changed** with the new fingerprint and a **Trust new certificate** button (see
  [Troubleshooting](Troubleshooting)). The fingerprints are kept in `printer-certificates.json`
  in the config directory (see [Configuration](Configuration)).
- Remaining risk: the first certificate is trusted as it is. A device on your LAN that announces
  your printer's serial and answers first, while the printer is off, would be trusted and could
  receive the access code. Add the printer while it is on and on your network. A fixed IP or
  host name is not checked (as before), and neither is Bambu Cloud.

If the exporter reports a discovery problem, see
[Troubleshooting](Troubleshooting) ("Automatic address (`auto`) does not connect").

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
3. The container logs in and saves the credentials encrypted in the config volume. If the account
   has several printers, tick the ones to monitor on the `/auth` page (up to 32 per exporter).
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
