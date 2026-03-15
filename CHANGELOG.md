# Changelog

All notable changes to this project are documented in this file.

## [0.1.20] - 2026-03-15

### Added
- Added dedicated high-value binary metrics decoded from `home_flag`:
  - `bambulab_wired_network`
  - `bambulab_camera_recording`
  - `bambulab_ams_auto_switch`
  - `bambulab_filament_tangle_detected`
  - `bambulab_filament_tangle_detect_supported`

### Updated
- README metric inventory updated with the new flag-derived binary metrics.

## [0.1.19] - 2026-03-15

### Added
- Added Grafana panels for decoded bitmask metrics:
  - `Home Flag States`
  - `Stat Flag States`
- Added `BambuSdCardAbnormal` alert rule.
- Added `bambulab:sdcard_abnormal:latest` recording rule.

### Updated
- Expanded README with PromQL examples for decoded flag metrics and SD abnormal checks.

## [0.1.18] - 2026-03-15

### Added
- Added full decoded flag-state metrics from bitmasks:
  - `bambulab_home_flag_state{flag}`
  - `bambulab_stat_flag_state{flag}`
- Added decoder foundation module for phased binary parity rollout.

### Changed
- `bambulab_sdcard_status_info` now derives `abnormal` state when both SD present+abnormal bits are set.

## [0.1.17] - 2026-03-15

### Fixed
- Corrected `bambulab_door_open` decoding across printer models:
  - Uses door bitmask `0x00800000` (aligned with upstream constants).
  - Adds `stat` hex parsing support for models that report door state via `stat`.
  - Keeps direct `door_open` field precedence when explicitly present.
  - Applies model-aware source selection (`X1/X1C` prefer `home_flag`, others prefer `stat`).

### Added
- Added full printer-type resolver from module metadata (`product_name`, `hw_ver`, `project_name`) with fallbacks.

### Tests
- Added/updated tests for door decoding from `home_flag` and `stat`, source precedence, and printer-type detection.

## [0.1.16] - 2026-03-15

### Removed
- Removed `bambulab_ams_slot_k_value{ams_id,slot_id}` metric (MQTT payloads do not reliably provide this field in current setup).
- Removed the related Grafana panel and README references.

### Tests
- Updated AMS tests to focus on `remain` parsing and tray type fallback without K-value assumptions.

## [0.1.15] - 2026-03-15

### Fixed
- Corrected AMS humidity field mapping (strict MQTT semantics):
  - `bambulab_ams_unit_humidity_index{ams_id}` now maps only to MQTT `humidity` (range-limited to 1..5).
  - `bambulab_ams_unit_humidity{ams_id}` now maps only to MQTT `humidity_raw` (range-limited to 1..100).
- Improved AMS slot K-value extraction with fallback keys: `k`, `k_value`, `K`.

### Tests
- Added coverage for strict humidity mapping (`humidity` index vs `humidity_raw`) and K-value fallback keys.

## [0.1.14] - 2026-03-15

### Added
- `bambulab_usage_hours_total` metric for total printer usage hours.
- `bambulab_sdcard_status_info{status}` info metric for SD card status.
- `bambulab_door_open` binary sensor (0/1) for door state.
- `bambulab_filament_loaded` binary sensor (0/1) for extruder filament state.
- `bambulab_timelapse_enabled` binary sensor (0/1) for timelapse recording.
- `bambulab_stg_cur` numeric gauge for current print stage ID.
- `bambulab_print_stage_info{stage}` info metric with human-readable stage name.
- Stage ID mapping dictionary (0-35, 255) based on upstream stage reference analysis.
- AMS slot K-value metric: `bambulab_ams_slot_k_value{ams_id,slot_id}`.
- AMS unit humidity index metric: `bambulab_ams_unit_humidity_index{ams_id}`.

### Changed
- AMS parsing is more tolerant:
  - `remain` accepts numeric strings.
  - tray type falls back to `ctype` when `tray_type` is absent.
  - humidity index accepts firmware/model variants in priority order:
    `humidity_index`, `humidity_level`, `humidityIndex`, `humidityLevel`.
- Grafana sample dashboard updated with v0.1.12+ panels including AMS slot K-value and AMS humidity index.
- Prometheus alerts updated with `BambuDoorOpenWhilePrinting` and `BambuExporterStale`.
- Prometheus recording rules updated with:
  - `bambulab:stage_id:latest`
  - `bambulab:door_open:latest`
- README updated with metric inventory and practical PromQL operator examples.

### Compatibility
- Changes are additive and backward compatible.
- New metrics emit only when valid data is present; missing/invalid payload fields are skipped.

## [0.1.10] - 2026-03-14

### Added
- Significant increase in test coverage to >95%.
- New test suites for MQTT callbacks, discovery probe, and complex model edge cases.
- Coverage for startup validation and shutdown handlers.

### Fixed
- Resolved `mypy` type mismatch in speed level lookup.

## [0.1.9] - 2026-03-14

### Added
- Auto-discovery of printer name during initial connection (persisted as `BAMBULAB_PRINTER_NAME`).
- Mandatory `serial` label on all metrics (derived from `BAMBULAB_SERIAL`).

### Changed
- Refactored labels: Removed `site` and `location`.
- Renamed `PRINTER_NAME` env var to `PRINTER_NAME_LABEL`.
- Improved printer name resolution: uses `PRINTER_NAME_LABEL` if set, falls back to discovered `BAMBULAB_PRINTER_NAME`.

### Fixed
- Updated test suite and mocks to support the new label schema and connection probe.

## [0.1.8] - 2026-03-14

### Added
- Added explicit MQTT-aligned metrics for `print_error` and `fan_gear` as `bambulab_print_error` and `bambulab_fan_gear`.
- Added info metric for fail reason: `bambulab_fail_reason_info` (label: `fail_reason`).

### Changed
- Kept existing derived metrics while exposing clearer MQTT field names for dashboards.

## [0.1.7] - 2026-03-14

### Added
- Added print subtask info metric: `bambulab_subtask_name_info` (label: `subtask_name`).

### Fixed
- Fixed WiFi signal parsing when MQTT reports values with `dBm` suffix (e.g. `-42dBm`) so `bambulab_wifi_signal` no longer appears empty.
- Fixed work light metric mapping so `lights_report.mode=flashing` is treated as ON for `bambulab_work_light_on`.

## [0.1.6] - 2026-03-13

### Added
- Added AMS tray metadata metrics: `bambulab_ams_slot_tray_type_info` and `bambulab_ams_slot_tray_color_info`.
- Added sample artifacts for regression/debugging: `examples/sample_mqtt_message.json` and `examples/sample_metrics.prom`.

### Changed
- Updated README with new AMS tray metrics and sample artifact references.
- Expanded metrics tests to cover AMS tray type/color labels.

## [0.1.5] - 2026-03-13

### Changed
- CI workflow simplified to PR essential checks only.
- Release workflow (`docker-publish`) remains the single place for full tests + Docker build/push.
- Release notes are now updated automatically with published Docker image paths after successful release publish workflow.

## [0.1.4] - 2026-03-13

### Changed
- README updated with clear CI/CD behavior summary for PR, main merge, and release flows.
- `.gitignore` updated with additional local editor temp-file ignores.

## [0.1.3] - 2026-03-13

### Changed
- CI flow aligned to release policy:
  - PRs run essential tests only.
  - Push/merge to `main` runs full test suite.
  - Docker build/publish runs only when a release is published.
- Adjusted workflow setup to avoid duplicate runs and keep release builds explicit.

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
