# bambulab_metrics_exporter

Production-oriented Prometheus exporter for Bambu Lab printers — homelab and self-hosted friendly.

Connects to your printer via LAN MQTT or Cloud MQTT, requests periodic full-state snapshots, and exposes stable Prometheus metrics for print state, temperatures, AMS, fans, and more.

> **Note:** Development and real-world validation are currently done on an X1C.  
> If you want to help improve support for additional printer models, please open an issue on GitHub.

---

## Wiki Navigation

| Page | Description |
|------|-------------|
| [Quick Start](Quick-Start) | Get up and running in minutes |
| [Installation](Installation) | Prerequisites and install options (local, Docker, Unraid) |
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
| `GET /` | Landing page — version, health, readiness |
| `GET /metrics` | Prometheus metrics |
| `GET /health` | Liveness check |
| `GET /ready` | Readiness check |

Default port: **9109**
