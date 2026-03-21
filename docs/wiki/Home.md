# bambulab_metrics_exporter

Production-oriented Prometheus exporter for Bambu Lab printers — homelab and self-hosted friendly.

Connects to your printer via LAN MQTT or Cloud MQTT, requests periodic full-state snapshots, and exposes stable Prometheus metrics for print state, temperatures, AMS, fans, and more.

> **Note:** Development and real-world validation are currently done on an X1C.  
> If you want to help improve support for additional printer models, please open an issue on GitHub.

---

## Wiki Navigation

| Page | Description |
|------|-------------|
| [Installation](Installation) | Prerequisites, quick start (local & Docker) |
| [Configuration](Configuration) | All environment variables and options |
| [Metrics Reference](Metrics-Reference) | Full metric list grouped by category |
| [Grafana Dashboard](Grafana-Dashboard) | Dashboard import steps and sample |
| [Troubleshooting](Troubleshooting) | Common issues and fixes |
| [Release Process](Release-Process) | How releases are cut and published |

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
