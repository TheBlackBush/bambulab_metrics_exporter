# Changelog

All notable changes to this project are documented in this file.

## [0.1.2] - 2026-03-13

### Changed
- CI pipeline refined:
  - PRs run essential checks only.
  - Push/merge to `main` runs full tests and Docker build in the same pipeline job.
- Fixed pytest cache option compatibility in CI.
- README Docker Compose section updated to match current cloud-first minimal compose file.

### Updated
- `.gitignore` expanded with common OS/editor noise entries.

## [0.1.1] - 2026-03-13

### Changed
- Switched default branch/workflows/templates from `master` to `main`.
- Updated Unraid XML to use clearer setup guidance and transport-specific field descriptions.
- Updated Unraid XML icon/template URLs and transport dropdown defaults.
- Simplified `docker-compose.yml` for cloud-first default run with minimal inline env comments.
- Moved test artifacts/coverage output to `tests/results` and updated CI artifact upload path.

### Added
- Added `docs/logo.png` (Unraid icon) and `docs/logo2.png` (repository image).

### Removed
- Removed `docker-compose.test.yml`.

## [0.1.0] - 2026-03-12

### Added
- Initial production-ready Python exporter for Bambu Lab metrics.
- Local MQTT and Cloud MQTT transport support.
- Startup preflight validation with cloud re-auth flow support.
- Encrypted local credential storage with `BAMBULAB_SECRET_KEY`.
- Runtime env synchronization support for containerized deployments.
- Full Docker support with non-root runtime flow and PUID/PGID mapping.
- Unraid template: `unraid-bambulab-metrics-exporter.xml`.
- Prometheus files under `prometheus/`:
  - `prometheus.scrape.yml`
  - `prometheus.alerts.yml`
  - `prometheus.recording.yml`
- Grafana sample dashboard with printer/transport telemetry panels.
- GitHub Action workflow for Docker build & publish to GHCR.

### Metrics
- Core status and health metrics (`printer_up`, `printer_connected`, scrape self-metrics).
- Print progress, remaining time, and layer metrics.
- Temperature metrics: nozzle/bed/chamber + target values.
- Fan metrics: aggregate + big1/big2/cooling/heatbreak.
- State/action metrics: gcode state, stage/sub-stage/action codes.
- AMS metrics: slot active/remain, status, RFID, humidity, temperature.
- Queue metrics: total, estimated seconds, number, status, position.
- Light and XCam feature metrics.

### Notes
- Release tag format: `v0.1.0`.
