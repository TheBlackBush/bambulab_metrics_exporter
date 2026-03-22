# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.1.37] - 2026-03-22

### Added
- Added `bambulab_lid_open` gauge metric. For H2-family printers, lid state is inferred from `print.stat` bit 24 (`0x01000000`) when direct `print.lid_open` is not present.

### Changed
- `PrinterSnapshot.lid_open` now prefers direct `print.lid_open` when available, falls back to H2 `print.stat` bit 24, and remains `None` on non-H2 models when no direct lid state exists.
- Existing door state behavior is unchanged.

### Tests
- Added unit tests covering H2 stat-bit fallback, direct `print.lid_open` override precedence, non-H2 behavior, and unchanged door-state logic.

## [0.1.36] - 2026-03-20

### Changed
- Refreshed Grafana dashboard sample (`examples/`) with updated layout, revised panels, and new screenshots in `docs/`.

## [0.1.35] - 2026-03-20

### Fixed
- `bambulab_ams_status_name` label now correctly decodes the firmware-encoded `ams_status` field.
  The raw value packs the status category in bits 15-8; decoding now extracts `(raw >> 8) & 0xFF`
  before mapping.  Single-byte map keys (`0x00`–`0xFF`) replace the previous multi-byte keys.
- `bambulab_ams_rfid_status_name` mapping extended with code `6 → reading_stop`.

### Added
- `AMS_DRY_HEATER_STATE_NAMES` and `AMS_DRY_SUB_STATUS_NAMES` reference tables in `models.py`
  for human-readable AMS Gen2 drying state and sub-status codes.

## [0.1.34] - 2026-03-18

### Fixed
- `bambulab_ams_slot_active` metric now correctly identifies the active AMS slot.
  Previously `tray_now` was read from the per-unit AMS dict (where it does not exist),
  causing all slots to always report 0. The fix reads `tray_now` from the top-level
  AMS wrapper in the MQTT payload and applies the correct bit-shift decoding
  (`ams_index = tray_now >> 2`, `slot_index = tray_now & 0x3`).
- `ams_tray_now` property in `models.py` now correctly handles integer values from
  the printer (previously only `str` was accepted, causing it to always return `None`).

## [0.1.33] - 2026-03-18

### Added
- Root `/` GET endpoint that returns a modern HTML landing page showing the exporter version, health status (always "Live"), and readiness status ("Connected" or "Warming Up") with color-coded pill indicators.
- Landing page now displays the BambuLab logo (served from `/static/bambulablogo.png`) above the app name heading.
- Landing page includes a "View Metrics →" link below the status cards, pointing to `/metrics`.
- Landing page shows the printer name (from `BAMBULAB_PRINTER_NAME` env var / `printer_name_label` config) next to the version badge (e.g. `v0.1.32 · My Printer`). Hidden when unset.
- Static files mount at `/static` in `api.py` (FastAPI `StaticFiles`) serving assets from `src/bambulab_metrics_exporter/static/`.
- `static/*.png` included in `[tool.setuptools.package-data]` so the logo is bundled in the installed package.
- `build_app()` now accepts an optional `settings: Settings` parameter used to inject printer name into the landing page.

### Changed
- Moved the root `/` HTML template from inline Python string in `api.py` to a dedicated file at `src/bambulab_metrics_exporter/templates/index.html`, loaded once at startup via `pathlib`.
- Redesigned landing page with a modern minimalist dark-mode aesthetic (Vercel/Linear-inspired): dark `#0f0f0f` background, card-style status sections, animated pill/badge status indicators, responsive two-column layout, and inline GitHub SVG link. No external resources or additional dependencies required.

## [0.1.32] - 2026-03-17

### Changed
- `tray_color` label values in `bambulab_ams_slot_tray_info` and `bambulab_external_spool_info` now include a `#` prefix for valid hex color codes (e.g. `#F98C36FF`). Empty or missing values remain `"unknown"`.

## [0.1.31] - 2026-03-17

### Changed
- Merged `bambulab_ams_slot_tray_type_info` and `bambulab_ams_slot_tray_color_info` into a single `bambulab_ams_slot_tray_info` metric with both `tray_type` and `tray_color` labels (**breaking change**).
## [0.1.30] - 2026-03-17

### Changed
- Fan metrics now follow step-aware normalization for raw fan levels (`0..15` -> percent) with nearest-10 rounding.
- Added secondary auxiliary fan metric: `bambulab_fan_secondary_aux_speed_percent` from `print.device.airduct.parts[id=160]`.
- Unified fan parsing behavior across dedicated fan fields: `big_fan1`, `big_fan2`, `cooling`, and `heatbreak`.
- Removed legacy `fan_gear` fan-speed parsing path (no longer used for fan metrics).

## [0.1.29] - 2026-03-17

### Changed
- Removed deprecated `bambulab_mc_print_stage_state{stage}` metric.
- Aligned `STG_CUR_NAMES` with Home Assistant (`upstream reference`) `CURRENT_STAGE_IDS`, including stage IDs `36..58` and idle mapping for `255`.
- Updated stage resolution to match optimized behavior:
  - prefer `print.stage._id` over `print.stg_cur`
  - normalize `print_type=idle` + stage `0` to `255`
  - retain unknown fallback as `unknown_<id>`
- Updated tests and README migration guidance for stage-metric migration.

## [0.1.28] - 2026-03-16

### Added
- Added explicit test hierarchy with dedicated suites:
  - `tests/unit/`
  - `tests/integration/`
  - `tests/e2e/`
- Added integration contract test for API endpoints (`/health`, `/ready`, `/metrics`).
- Added end-to-end collector cycle test that validates readiness transition and metric emission through HTTP.
- Added security/logging coverage tests (encryption roundtrip, `ensure_parent` chmod-failure path, logging level fallback).

### Changed
- Moved all existing `tests/test_*.py` files under `tests/unit/`.
- Updated pytest discovery paths in `pyproject.toml` to run unit/integration/e2e suites explicitly.
- Improved overall coverage while keeping existing coverage gate intact.

## [0.1.27] - 2026-03-16

### Added
- Added initial multi-extruder telemetry support (H2D/H2D Pro payload-compatible):
  - `bambulab_active_extruder_index`
  - `bambulab_extruder_temperature_celsius{extruder_id}`
  - `bambulab_extruder_target_temperature_celsius{extruder_id}`
  - `bambulab_extruder_nozzle_info{extruder_id,nozzle_type,nozzle_diameter}`
  - `bambulab_active_nozzle_info{nozzle_type,nozzle_diameter}`
- Added Hotend Rack core telemetry support:
  - `bambulab_hotend_rack_holder_position_info{position}`
  - `bambulab_hotend_rack_holder_state_info{state}`
  - `bambulab_hotend_rack_slot_state_info{slot_id,state}`
  - `bambulab_hotend_rack_hotend_info{slot_id,nozzle_type,nozzle_diameter}`
  - `bambulab_hotend_rack_hotend_wear_ratio{slot_id}`
  - `bambulab_hotend_rack_hotend_runtime_minutes{slot_id}`

### Changed
- Added parser support for `print.device.extruder.state`, `print.device.extruder.info[]`, and `print.device.nozzle.info[]` in the snapshot model.
- Added packed extruder temperature unpacking (`low16=actual`, `high16=target`) for dual-extruder payloads.
- Added Hotend Rack parsing from `print.device.holder` and `print.device.nozzle` (`exist`, `info`, `tar_id`) with slot-state normalization (`mounted|docked|empty`) for rack slots `16..21`.

## [0.1.26] - 2026-03-16

### Added
- Added external spool telemetry support:
  - `bambulab_external_spool_active` (1 when `print.ams.tray_now == 254`, else 0)
  - `bambulab_external_spool_info{external_id,tray_type,tray_info_idx,tray_color}` from `vir_slot` / `vt_tray`

### Changed
- External spool metadata extraction now normalizes `tray_color` to uppercase and prefers `vir_slot` over `vt_tray` when both are present.

## [0.1.25] - 2026-03-16

### Fixed
- Cloud AMS model detection now also parses AMS type from string-based payload keys (`info` / `ams_info`), including bare digit strings and hex forms (`0x...`).
- Improved AMS type inference for cloud payloads like `info="1001"` by preferring interpretations that produce a known AMS type nibble.
- Gen2 drying telemetry parsing now uses the same AMS info extraction path, so string-based payloads emit drying metrics consistently.

### Changed
- `bambulab_ams_unit_info` labels simplified to `{printer_name,serial,ams_id,ams_model,ams_series}`.
- Removed `ams_serial` label from `bambulab_ams_unit_info` to avoid empty/unstable label values in cloud payloads where AMS serial is not provided.

## [0.1.24] - 2026-03-16

### Added
- **AMS model/series detection** per AMS unit with full precedence chain:
  - `ams_info` bits 0-3 (`ams_type`) when valid and nonzero (highest priority)
  - AMS serial prefix mapping: `006→ams_1`, `03C→ams_lite`, `19C→ams_2_pro`, `19F→ams_ht`
  - `unknown` fallback
- **AMS series mapping**: `ams_1`/`ams_lite`→`gen_1`, `ams_2_pro`/`ams_ht`→`gen_2`
- **New info metric**: `bambulab_ams_unit_info{printer_name,serial,ams_id,ams_model,ams_series,ams_serial}=1`
- Existing AMS-scoped metrics (`bambulab_ams_unit_humidity*`, `bambulab_ams_slot_*`) retain their original label sets unchanged — model/series is only available via `bambulab_ams_unit_info`
- **Gen2 drying telemetry metrics** (emitted only when `ams_info` is present):
  - `bambulab_ams_heater_state_info{...,ams_id,ams_model,ams_series,state}=1` — heater/dry state (bits 4-7)
  - `bambulab_ams_dry_fan_status{...,ams_id,ams_model,ams_series,fan_id}` — fan1/fan2 state (bits 18-21)
  - `bambulab_ams_dry_sub_status_info{...,ams_id,ams_model,ams_series,state}=1` — drying sub-status (bits 22-25)
- New `parse_ams_info()` utility function for `ams_info` bitmask parsing
- New `resolve_ams_model()` and `resolve_ams_series()` functions in models module
- New `ams_units_with_model` property on `PrinterSnapshot` returning enriched AMS unit dicts

## [0.1.23] - 2026-03-15

### Fixed
- Aligned SN-prefix printer model mapping with the upstream model matrix:
  - `00W -> X1`
  - `00M -> X1C`
  - `03W -> X1E`
  - `01S -> P1P`
  - `01P -> P1S`
  - `030 -> A1MINI`
  - `039 -> A1`
  - `22E -> P2S`
  - `093 -> H2S`
  - `094 -> H2D`
- Updated resolver tests to enforce the corrected mappings and prevent regressions.

## [0.1.22] - 2026-03-15

### Added
- AMS status name info metric: `bambulab_ams_status_name{status="..."}` = 1 (label key: `status`).
- AMS RFID status name info metric: `bambulab_ams_rfid_status_name{status="..."}` = 1 (label key: `status`).
- AMS status mappings: `idle`, `filament_change`, `rfid_identifying`, `assist`, `calibration`, `self_check`, `debug`, `unknown_device`.
- AMS RFID status mappings: `idle`, `reading`, `writing`, `identifying`, `close`, `unknown_rfid`.
- Unknown AMS/RFID status codes now emit deterministic `unknown_<code>` labels.
- Extended printer model resolver with SN-prefix coverage for: `00W`, `00M`, `01S`, `01P`, `030`, `036`, `22E`, `093`, `094`.

### Changed
- `bambulab_ams_status` renamed to `bambulab_ams_status_id`.
- `bambulab_ams_rfid_status` renamed to `bambulab_ams_rfid_status_id`.
- STG_CUR_NAMES readability updates (including ids 1/11/15/31 and broader stage naming cleanup).
- Printer model resolver is now table-driven: `product_name -> hw_ver+project_name -> SN-prefix -> device.type -> model_id`.
- Removed corresponding Grafana panels and README references for removed debug/noisy metrics.

### Removed
- Debug flag-state metrics:
  - `bambulab_home_flag_state{flag}`
  - `bambulab_stat_flag_state{flag}`
- Fan metrics not semantically reliable for current `fan_gear` payload behavior:
  - `bambulab_fan_speed_percent`
  - `bambulab_fan_gear`

## [0.1.21] - 2026-03-15

### Added
- Dedicated high-value flag metrics:
  - `bambulab_wired_network`
  - `bambulab_camera_recording`
  - `bambulab_ams_auto_switch`
  - `bambulab_filament_tangle_detected`
  - `bambulab_filament_tangle_detect_supported`
- Alert + recording additions:
  - `BambuSdCardAbnormal`
  - `bambulab:sdcard_abnormal:latest`

### Changed
- `bambulab_door_open` decoding is model-aware and bitmask-correct (`home_flag`/`stat`, mask `0x00800000`).
- `bambulab_sdcard_status_info` now supports `abnormal` status from flag decoding.
- Test suite reorganized into module-aligned files (cleaned phase/fix fragmentation).
- Prometheus/Grafana assets moved under `examples/`.

### Removed
- Removed metrics without reliable live MQTT source in current payloads:
  - `bambulab_usage_hours_total`
  - `bambulab_filament_loaded`
  - `bambulab_timelapse_enabled`
- Removed `bambulab_ams_slot_k_value{ams_id,slot_id}` and related dashboard/docs references.

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
