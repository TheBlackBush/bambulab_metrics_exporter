<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/TheBlackBush/bambulab_metrics_exporter/main/docs/brand/svg/icon.svg">
    <img src="https://raw.githubusercontent.com/TheBlackBush/bambulab_metrics_exporter/main/docs/brand/png/lockup-2400x640.png" alt="bambulab_metrics_exporter" height="120">
  </picture>
</p>

# bambulab_metrics_exporter

See your Bambu Lab 3D printer in Grafana: print progress, temperatures, fans, AMS filament and
humidity, errors and more. The exporter runs as a small Docker container, talks to your printer
over your home network (or through Bambu Cloud), and publishes the data for Prometheus and
Grafana.

**New here?** Start with the [Quick Start](Quick-Start): start the container with a secret key,
then connect the printer in your browser.

> **Supported printers:** X1, X1C, X1E, X2D, P1P, P1S, P2S, A1, A1 mini, A2L, H2D, H2D Pro, H2S
> and H2C are recognized. Real-world testing so far is on an X1C, and an H2D was checked on real hardware while idle and while printing; if you own another model and
> want to help, please open an issue on GitHub.

---

## Wiki Navigation

| Page | Description |
|------|-------------|
| [Quick Start](Quick-Start) | Get up and running in minutes; the `/auth` connection page |
| [Installation](Installation) | Docker, Docker Compose, Unraid, and env-variable setup |
| [Configuration](Configuration) | All environment variables and options |
| [Prometheus Setup](Prometheus-Setup) | Scrape config, alert rules, and recording rules |
| [Grafana Dashboard](Grafana-Dashboard) | Dashboard import steps and sample panels |
| [Metrics Reference](Metrics-Reference) | Full metric list grouped by category |
| [Troubleshooting](Troubleshooting) | Common issues and fixes |

---

## Quick Links

- **GitHub Repository:** https://github.com/TheBlackBush/bambulab_metrics_exporter
- **Container Registry (GHCR):** https://github.com/TheBlackBush/bambulab_metrics_exporter/pkgs/container/bambulab_metrics_exporter
- **Releases:** https://github.com/TheBlackBush/bambulab_metrics_exporter/releases

---

## How it works

- The exporter connects to the printer's MQTT service, either on the LAN (`local_mqtt`) or through
  Bambu Cloud (`cloud_mqtt`), and listens to the printer's status reports
  (`device/<serial>/report`).
- It only reads. The only messages it sends are two read-only requests: `pushall` (a full status
  report, every poll) and `get_version` (the module list, once per connection). Set
  `BAMBULAB_REQUEST_PUSHALL=false` to turn both off.
- The printer model is detected from the module list, the serial number prefix, or
  `BAMBULAB_PRINTER_MODEL`. Each model has a hardware profile, so metrics for parts a printer does
  not have (for example a chamber heater) are left empty instead of showing placeholder values.
- One exporter serves every printer it monitors on one `/metrics` endpoint. Each series carries
  `printer_name` and `serial` labels.

---

## Known limitations

1. Only the X1C has been fully tested on real hardware (an H2D was checked while idle and while
   printing). Other models are recognized from their data and may report some values differently.
2. One exporter monitors up to 32 printers (one Bambu account for the cloud ones). Running several
   printers in one exporter has not been validated on real hardware; separate containers remain
   supported.
3. The MQTT connection is encrypted, but the printer's certificate is not verified (the printers
   use self-signed certificates).
4. Some values depend on the printer model and firmware. Missing values are left empty rather than
   shown as zero.

---

## Endpoints

Once running, the exporter exposes:

| Endpoint | Description |
|----------|-------------|
| `GET /` | Status page: health, printer connection, last update |
| `GET /auth` | Printer connection page: local or Bambu Cloud login |
| `GET /auth/status` | Connection state as JSON |
| `GET /metrics` | Prometheus metrics |
| `GET /health` | Liveness check |
| `GET /ready` | Readiness check |

> The `/auth` page has no login of its own. Keep port 9109 on a trusted network.

Default port: **9109**
