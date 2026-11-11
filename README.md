<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/svg/icon.svg">
    <img src="docs/brand/png/lockup-2400x640.png" alt="bambulab_metrics_exporter" height="160">
  </picture>
</p>

<p align="center"><em>Not affiliated with Bambu Lab.</em></p>

# bambulab_metrics_exporter

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3110/)
[![GitHub Release](https://img.shields.io/github/v/release/TheBlackBush/bambulab_metrics_exporter?style=for-the-badge)](https://github.com/TheBlackBush/bambulab_metrics_exporter/releases)
[![Docker Publish](https://img.shields.io/github/actions/workflow/status/TheBlackBush/bambulab_metrics_exporter/docker-publish.yml?style=for-the-badge&label=Docker%20Publish)](https://github.com/TheBlackBush/bambulab_metrics_exporter/actions/workflows/docker-publish.yml)
[![GHCR Package](https://img.shields.io/badge/image-bambulab__metrics__exporter-blue?style=for-the-badge&logo=github)](https://github.com/TheBlackBush/bambulab_metrics_exporter/pkgs/container/bambulab_metrics_exporter)
[![GHCR Pulls](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fghcr-badge.elias.eu.org%2Fapi%2FTheBlackBush%2Fbambulab_metrics_exporter%2Fbambulab_metrics_exporter&query=downloadCount&label=ghcr%20pulls&style=for-the-badge&logo=docker&logoColor=white)](https://github.com/TheBlackBush/bambulab_metrics_exporter/pkgs/container/bambulab_metrics_exporter)
[![Docker Hub Pulls](https://img.shields.io/docker/pulls/blackbush/bambulab_metrics_exporter?style=for-the-badge&logo=docker&logoColor=white&label=docker%20hub%20pulls)](https://hub.docker.com/r/blackbush/bambulab_metrics_exporter)
[![Grafana Dashboard Downloads](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fgrafana.com%2Fapi%2Fdashboards%2F25033&query=%24.downloads&label=grafana%20downloads&style=for-the-badge&logo=grafana&logoColor=white)](https://grafana.com/grafana/dashboards/25033-bambulab-metrics)
[![Ko-fi](https://img.shields.io/badge/support_me_on_ko--fi-F16061?style=for-the-badge&logo=kofi&logoColor=f5f5f5)](https://ko-fi.com/M4M11W3R7J)

A Prometheus exporter for Bambu Lab 3D printers. It runs as a small Docker container, reads your
printer's live status over your home network or through Bambu Cloud, and publishes it for
[Prometheus](https://prometheus.io/) to collect and [Grafana](https://grafana.com/) to chart.
Watch prints, temperatures, filament and errors on a dashboard, keep history, and get alerts.

![Grafana dashboard sample](examples/grafana/images/bambulab-dashboard-0-full.png)

## Features

- **Printer status:** connection, state and stage, errors (HMS) by severity, door, lid, lights,
  camera, network, SD card or USB drive, firmware versions and available updates.
- **Print progress:** percent, layers, time left, job source, file download progress, skipped
  objects and fail reason.
- **Temperatures and fans:** nozzle (per extruder and the active one on dual-nozzle printers),
  bed, chamber and their targets, plus every fan and the airduct mode.
- **AMS:** model, filament type and color per slot, remaining filament, humidity, temperature and
  drying status, per zone on the AMS 3H.
- **Extruders and nozzles:** filament change steps, filament sensors and buffer, nozzle type,
  diameter and wear.
- **Model aware:** detects the printer model and leaves out metrics for hardware it does not have.
- **Easy setup:** connect the printer in your browser on the built-in `/auth` page (LAN or Bambu
  Cloud login). Settings are stored encrypted and survive restarts.
- **Several printers:** one exporter can monitor up to 32 printers, cloud and LAN mixed.
- **Diagnostics:** a built-in page builds a sanitized report (no serials, addresses, names or
  credentials) and opens a prefilled GitHub issue, for new printers, missing metrics or problems.
- **Read-only:** it never sends control commands to the printer.
- **Ready to use:** a [Grafana dashboard](https://grafana.com/grafana/dashboards/25033-bambulab-metrics/),
  Prometheus alert and recording rules, and an Unraid template.

## Supported printers

X1, X1C, X1E, X2D, P1P, P1S, P2S, A1, A1 mini, A2L, H2D, H2D Pro, H2S, H2C and H3C are recognized.
Real-world testing so far is on an **X1C**, and an **H2D** was checked on real hardware while idle
and while printing. Other models are recognized from their data and may report some values
differently. If you own another model and want to help, please
[open an issue](https://github.com/TheBlackBush/bambulab_metrics_exporter/issues/new?template=diagnostic.yml)
with a [diagnostic report](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Diagnostic-Report):
run it on the exporter's Diagnostics page, with serials, addresses, names and credentials
removed, and create the issue from there.

**Running several printers in one exporter?** This is new and has only been tested with simulated
printers, so feedback is very welcome. Please
[open an issue](https://github.com/TheBlackBush/bambulab_metrics_exporter/issues/new) and tell us
what worked, including your printer models and whether they use cloud or LAN.

## Quick start

You need a machine that runs Docker, and Prometheus and Grafana to store and chart the data.

1. Create a secret key once and keep it safe. It encrypts the saved printer settings and cloud
   login:

   ```bash
   openssl rand -hex 32
   ```

2. Start the container:

   ```bash
   docker run -d \
     --name bambulab-exporter \
     --restart unless-stopped \
     -p 9109:9109 \
     -v /path/to/config:/config/bambulab-metrics-exporter \
     -e BAMBULAB_SECRET_KEY=<your-secret-key> \
     ghcr.io/theblackbush/bambulab_metrics_exporter:latest
   ```

3. Open `http://<your-server-ip>:9109/auth`, choose **Local** (IP, serial number and LAN access
   code) or **Bambu Cloud** (email and a code), and connect. No restart is needed.

4. Add `<your-server-ip>:9109` as a Prometheus scrape target and import Grafana dashboard
   **25033**.

The image is also on Docker Hub as `blackbush/bambulab_metrics_exporter`. Docker Compose, Unraid,
environment-variable setup and every option are covered in the wiki:
[Quick Start](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Quick-Start) and
[Installation](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Installation).

> The `/auth` page has no password of its own. Keep port 9109 on your home network.

## Documentation

The [wiki](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki) has the full guides:

| Page | What it covers |
|------|----------------|
| [Quick Start](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Quick-Start) | Step-by-step setup and the `/auth` connection page |
| [Installation](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Installation) | Docker, Docker Compose, Unraid and environment-variable setup |
| [Configuration](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Configuration) | Every environment variable |
| [Prometheus Setup](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Prometheus-Setup) | Scrape config, alert and recording rules |
| [Grafana Dashboard](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Grafana-Dashboard) | Import steps and panels |
| [Metrics Reference](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Metrics-Reference) | Every metric, per-model support and PromQL examples |
| [Troubleshooting](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Troubleshooting) | Common problems and fixes |
| [Diagnostic Report](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki/Diagnostic-Report) | The report to attach to issues for new printers, metrics or fixes |

How the exporter works and its known limitations are on the
[wiki home page](https://github.com/TheBlackBush/bambulab_metrics_exporter/wiki).
Release notes are in [CHANGELOG.md](CHANGELOG.md), and examples (dashboard JSON, Prometheus
rules, sample output) in [`examples/`](examples/).

## Development

The project ships as a Docker image only (no PyPI package). To run the tests:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pip install -e .
make test   # full suite with coverage gate
make lint
```

To build the image locally: `docker build -t bambulab-metrics-exporter:latest .`

## License

[GPL-3.0](LICENSE)
