# bambulab_metrics_exporter

See your Bambu Lab 3D printer in Grafana: print progress, temperatures, fans, AMS filament and
humidity, errors and more. The exporter runs as a small Docker container, talks to your printer
over your home network (or through Bambu Cloud), and publishes the data for Prometheus and
Grafana.

**New here?** Start with the [Quick Start](Quick-Start): start the container with a secret key,
then connect the printer in your browser.

> **Supported printers:** X1, X1C, X1E, X2D, P1P, P1S, P2S, A1, A1 mini, A2L, H2D, H2D Pro, H2S
> and H2C are recognized. Real-world testing so far is on an X1C; if you own another model and
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
