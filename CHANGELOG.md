# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.2.0] - 2026-10-07

### Added
- Grafana dashboard (`examples/grafana/dashboard.sample.json`): new rows for health and
  firmware (HMS errors, firmware update, module versions), chamber/airduct/accessories,
  extruders and nozzles, and AMS drying, plus HMS and airduct fan trends.
- Firmware: `bambulab_firmware_update_available` and
  `bambulab_module_firmware_info{module,version}` (from `get_version`).
- Accessories: `bambulab_tool_head_info{tool}` (laser, cutter, cooling fan) and
  `bambulab_accessory_present{accessory}` (filament buffer, external exhaust fan, fire
  extinguisher, rotary attachment, filament switch, air pump).
- `bambulab_light_mode_info{light,mode}` covering `chamber_light2` and `heatbed_light`.
- `bambulab_toolhead_filament_present{extruder_id}` and X2D timelapse storage
  (`bambulab_timelapse_storage_{free,total}_bytes{storage}`).
- Print stage names for codes 59-84 and 88 (previously `unknown_<n>`).
- AMS drying (AMS 2 Pro, AMS HT): `bambulab_ams_drying_remaining_seconds{ams_id}`,
  `bambulab_ams_drying_target_temperature_celsius{ams_id}` and
  `bambulab_ams_drying_duration_seconds{ams_id}`.
- Airduct (P2S, X2D, H2 family): `bambulab_airduct_mode_info{mode}` and
  `bambulab_airduct_fan_speed_percent{fan}` with a fixed fan name set.
- Mounted nozzles: `bambulab_nozzle_wear_ratio{extruder_id}` (raw value, unit unconfirmed)
  and `bambulab_nozzle_print_time_seconds{extruder_id}`.
- `bambulab_chamber_target_temperature_celsius` and `bambulab_chamber_heater_state` for
  models with a chamber heater (X1E, X2D, H2D, H2D Pro, H2S, H2C).
- `bambulab_extruder_loaded_slot_info{extruder_id,ams_id,slot_id}`: filament loaded in each
  extruder (AMS slot or external spool).
- HMS error counts: `bambulab_hms_active_errors{severity}` and
  `bambulab_hms_active_errors_by_module{module}`, with fixed label sets (full HMS codes are
  never used as labels). New example alert `BambuHmsSeriousError`.
- Per-model capability table (`capabilities.py`, documented in the wiki Metrics Reference as
  "Supported models"), replacing scattered model checks.
- Model codes: `O2D` and the cloud short name `H2DP` (H2D Pro), `A1M`, `A04`, `A12`, `N2`
  (A1 mini), `A11` (A1), and `-V2` hardware revisions (`N6-V2`, `O1D-V2`, `O1C2-V2`, ...).
- R1 laser engraver (serial prefix `35F`, Bambu Studio code `N8`) is recognized as model `R1`;
  no FDM metrics are reported for it.
- `bambulab_filament_tangle_detection_enabled`: the tangle-detection setting, NaN when the
  printer does not support it.
- `bambulab_hotend_rack_hotend_print_time_seconds` (`p_t`) and
  `bambulab_hotend_rack_hotend_max_temperature_celsius` (`tm`) for H2C hotend rack slots.
- Model detection for **X2D** (`20P`), **A2L** (`26A`), **H2D Pro** (`239`) and **H2C**
  (`31B`) by serial prefix, plus `Bambu Lab X2D` and `Bambu Lab A2L` product names.
  Detection only: these models are not hardware-validated.
- Model detection from the configured `BAMBULAB_SERIAL`. Regular `pushall` reports omit
  `print.sn`, so the configured serial is now the main identity source.
- `BAMBULAB_PRINTER_MODEL` (set manually or by cloud discovery) is used as a model hint
  when the serial prefix is unknown. Accepts marketing names (`X1 Carbon`), internal codes
  (`BL-P001`, `N6`) and normalized names (`H2DPRO`); unrecognized values are ignored.
- AMS info type 5 (AMS Lite on the A2L) maps to `ams_lite`.
- On each successful MQTT connect the exporter sends one read-only `get_version` request.
  The reply's module list supplies the printer product name for model detection. Disabled
  together with `pushall` by `BAMBULAB_REQUEST_PUSHALL=false`.
- Development images: every push to the `develop` branch publishes
  `ghcr.io/theblackbush/bambulab_metrics_exporter:develop` and `:develop-<short-sha>`
  (amd64/arm64) after the full test suite passes. Stable `latest` and version tags are
  unchanged.
- **`/auth` connection page:** choose local (IP, serial, access code) or Bambu Cloud (email
  verification code) in the browser; the exporter reconnects without a restart. Linked from
  the landing page. `GET /auth/status` returns the connection state as JSON. The page has no
  login of its own: anyone who can reach port 9109 can change the connection, so keep the port
  on a trusted network. Protections: saved secrets are never displayed, verification emails
  are limited to one per minute and login attempts to five per minute, cross-site form posts
  are rejected, only IP addresses and local-network host names are accepted (DNS-rebinding
  protection; add others with `AUTH_ALLOWED_HOSTS`), pages cannot be framed by other sites,
  form bodies are capped at 8 KB, and each visitor only sees their own results.
- Settings saved on `/auth` are stored encrypted (`connection-overrides.enc.json` in
  `BAMBULAB_CONFIG_DIR`, requires `BAMBULAB_SECRET_KEY`) and override env vars, including
  container template values, after restarts. They are never written to `.env`.
  **Reset to env vars** removes them and also undoes a cloud login made on the page
  (the previous credentials file and the container's tokens are restored).
- `AUTH_ALLOWED_HOSTS` setting: extra host names allowed for the `/auth` page.
- Landing page redesign: shows the printer connection state (Connected, Connecting, Login
  required, ...), the mode (Local or Bambu Cloud), and the time since the last successful
  poll. A banner links to `/auth` when a login or setup is needed. The page refreshes itself.
- The startup log lists the web UI addresses: status page `/`, printer connection `/auth`,
  `/metrics`, `/health` and `/ready`.
- `bambulab-reauth` command for cloud re-authentication inside the running container:
  `docker exec -it <container> bambulab-reauth`. It sends (or accepts) the email
  verification code and saves encrypted credentials; a waiting exporter resumes without a
  restart. Files are handed back to `PUID`/`PGID`, or to the owner of the config folder when
  those are not set in the container (Compose default). It refuses to write through symlinks.

### Changed
- **The web server starts immediately** and the printer connection runs in the background.
  The process no longer exits on connection problems:
  - Rejected cloud credentials (the Bambu broker refuses the login): logs a
    `BAMBU CLOUD RE-AUTHENTICATION REQUIRED` banner and waits for a login on `/auth` or
    `bambulab-reauth`, re-checking every 5 minutes. This ends restart loops and repeated
    verification emails: at most one code is sent per container start when
    `BAMBULAB_CLOUD_EMAIL` is set without a code, and each `BAMBULAB_CLOUD_CODE` is tried once.
  - Local connection failures, cloud API or broker outages, and a cloud printer that does not
    answer (powered off): retried every 60 seconds, never treated as expired credentials and
    never sending a code (previously the process exited and relied on the restart policy).
  - Missing settings: reported as `setup_required` on `/auth` instead of exiting.
  - Invalid values (for example `BAMBULAB_TRANSPORT=lan`) and an unreadable credentials file:
    logged, with `/auth` still reachable, instead of exiting.
  `/health` stays `ok` (process liveness) and `/ready` stays 503 until the first data, then
  stays ready (sticky), as before.
- Startup tries the encrypted credential file when env tokens are rejected, so stale tokens in
  a container template (for example Unraid) no longer hide newer rotated credentials.
- The `BAMBULAB_CLOUD_EMAIL` + `BAMBULAB_CLOUD_CODE` env flow is unchanged and still supported.

### Fixed
- An expired or revoked cloud token (or a changed LAN access code) while the exporter is
  running is now detected: the exporter re-validates (token refresh first, then the
  re-authentication state on `/auth`) instead of reconnecting with rejected credentials and
  reporting `running`.
- "Reset to env vars" on `/auth` is no longer undone after a restart: the cloud token
  refresh no longer writes page settings into `.env`, and tokens from a page cloud login stay
  in the encrypted store (never `.env`). A page login still survives restarts, and reset
  returns to the container's own credentials.
- A1 / A1 mini AMS Lite no longer exports placeholder temperature 0 and humidity index 5
  before the `get_version` reply arrives or with `BAMBULAB_REQUEST_PUSHALL=false`; AMS HT
  units (ids 128-135) on legacy firmware are recognized without it.
- R1 laser engravers no longer report nozzle, bed, part-cooling/heatbreak fan, extruder or
  AMS metrics.
- Shutdown and reconnect: a stop during connection validation no longer starts a collector,
  a fetch that outlives a reconnect no longer writes into the new registry, and credentials
  written by `bambulab-reauth` during validation are used right away.
- `examples/sample_metrics.prom` regenerated from the sanitized X1C fixture (current labels
  and metrics); missing Metrics Reference rows added (`bambulab_lid_open`,
  `bambulab_print_error_code`, `bambulab_mc_stage`, `bambulab_mc_print_sub_stage`,
  `bambulab_print_real_action`, `bambulab_print_gcode_action`, `bambulab_online_ahb`,
  `bambulab_online_ext`).
- Fixture sanitizer now replaces AMS `chip_id` and serial-style `ams_id` values.
- Grafana "Lights" panel shows one readable entry per light with a colored state (Off,
  On, Flashing) instead of the same green text for every mode.
- Grafana dashboard: target temperature, total layer, stage and error queries now filter on
  `$printer` (they mixed printers sharing a job); remaining-time trend uses seconds (was
  minutes, 60x too large); AMS temperature and humidity show one value per unit instead of
  the maximum; removed an empty query that made "Print Errors" fail; "Print Percentage
  Remaining" renamed to "Print Progress"; AMS "Printer Model" renamed to "AMS Model"; the
  tangle panel shows Enabled/Disabled for the detection setting.
- `bambulab_fan_big_1_speed_percent` / `bambulab_fan_big_2_speed_percent` are NaN on A1,
  A1 mini and A2L, which have no aux or chamber fan but report 0.
- X1-family door state no longer falls back to `stat` bit 23 when `home_flag` is missing;
  that bit is always set on the X1C and reported the door as open.
- **Chamber temperature on heated printers** (H2C, H2D, H2D Pro, H2S, X2D, P2S): the packed
  `device.ctc` value (target << 16 | current) is unpacked; an H2S heating to 60 °C reported
  3,932,220 °C. Models without a chamber sensor (A1, A1 mini, A2L, P1P, P1S) report NaN
  instead of a firmware placeholder (5 °C).
- **Secondary aux fan** (X2D) read a field that does not exist and was always NaN; it now
  reads the airduct part `state` percentage.
- **Active AMS slot and external spool on dual-extruder printers** (H2D, H2D Pro, H2C, X2D):
  read from the active extruder's loaded slot instead of `ams.tray_now`, which only holds the
  local slot (an H2D printing from AMS 1 slot 3 showed AMS 0 slot 3). AMS HT units
  (`tray_now` 128 and up) now show as active.
- **AMS 2 Pro / AMS HT drying state**: `info` strings are always hexadecimal; digit-only
  values such as `2003` were read as decimal and produced impossible states.
- **Unknown remaining filament** (`remain` -1) is exported as NaN instead of -1 %, so the
  documented `< 15` alert no longer fires for spools without an estimate.
- AMS Lite no longer exports placeholder temperature and humidity (it has no sensors), and
  drying metrics are only exported for AMS 2 Pro and AMS HT.
- `bambulab_door_open` is NaN on models without a door sensor (A1, A1 mini, A2L, P1P, P1S).
- `bambulab_camera_recording` follows the camera setting (`ipcam.ipcam_record`); newer
  firmware no longer sets home_flag bit 5 (verified on an X1C with firmware 01.12.00.00).
- AMS model is taken from `get_version` module names when units carry no `info` or serial
  (A1 AMS Lite, AMS HT on older firmware).
- Early H2C units with the H2D serial prefix `094` are detected as H2C (hotend rack present).
- Empty external-spool virtual slots are no longer exported with `unknown` labels.
- Nozzle type and diameter are exported on A1, P1 and older X1 firmware (top-level
  `nozzle_type`).
- **MQTT TLS is capped at version 1.2**: P2S firmware 01.02.00.00 never answers a TLS 1.3
  handshake, so the connection hung. All Bambu brokers support TLS 1.2; certificate checking
  is unchanged.
- **Expired cloud tokens caused an endless restart loop.** A refresh rejected with HTTP 401
  by one API endpoint and a DNS failure on another was classified as a transient outage, so
  re-authentication never started. Any 401/403 with no successful endpoint now counts as
  rejected credentials.
- Removed the `api-eu.bambulab.com` API endpoint: the host does not exist (it never resolved)
  and caused the DNS failure above. Bambu Studio and ha-bambulab use only `api.bambulab.com`
  outside China.
- After a successful token refresh at startup, the MQTT client was still built with the old
  token and failed with `Not authorized`. Refreshed credentials now apply to the running
  configuration.
- A token refresh response without a `refreshToken` (or with `null`) no longer replaces the
  stored refresh token with the text `None`; the previous refresh token is kept.
- A refresh rejected with HTTP 400 counts as an invalid refresh token (re-authentication)
  instead of a transient error retried forever.
- **Most LAN-connected printers were reported as `X1C`.** Without identity fields in the
  payload, detection fell through to `print.device.type`, a mode bitmask (FDM=0x1,
  laser=0x10, cut=0x100) that reads 1 on every FDM printer and was mapped to `X1C`.
  Affected H2D, H2D Pro, H2S, H2C, P2S, X2D and A2L. These printers also read the door from
  `home_flag` (X1 logic) instead of `stat`, and H2 printers reported `lid_open` as NaN.
- The `Bambu Lab X1-Carbon` product name (with hyphen, as sent by firmware) now matches.
- X1E reads the door sensor from `home_flag` like the X1 and X1C.

### Removed
- `print.device.type` and `print.model_id` are no longer used for model detection
  (`model_id` is an opaque per-job id and could leak into the `model` label). The ambiguous
  `AP05` hardware-version fallback to `X1C` is removed; `AP05` is shared by X1C, H2D, H2S,
  H2C and A1.

### Security
- Cloud API error messages and logs no longer include HTTP response bodies.
- The printer name on the landing page is HTML-escaped.

### Migration notes
- **AMS dryer state labels are names now** (AMS 2 Pro / AMS HT only):
  `bambulab_ams_heater_state_info{state}` uses `off`, `self_check`, `drying`, `cooling`,
  `stopped`, `error`, `thermal_runaway`, `test_mode` instead of `0`-`7`, and
  `bambulab_ams_dry_sub_status_info{state}` uses `none`, `heating`, `dehumidifying`. The
  sub-status is a 2-bit field (bits 22-23); values above 2 were misread before. Update
  queries that select on numeric `state` values.
- **Deprecated, removed in a future release:**
  - `bambulab_filament_tangle_detected`: it is the tangle-detection setting (home_flag
    bit 20), not a detected tangle. Use `bambulab_filament_tangle_detection_enabled`. Both
    are now NaN on printers that report no tangle-detection support (for example the X1C),
    where the bit carries no meaning. The sample Grafana panel is renamed "Tangle Detection".
  - `bambulab_hotend_rack_hotend_runtime_minutes`: it carries the hotend's maximum
    temperature (`tm`, 350 on H2C), not a runtime. Use
    `bambulab_hotend_rack_hotend_print_time_seconds` or
    `bambulab_hotend_rack_hotend_max_temperature_celsius`.
- The `model` label of `bambulab_printer_model_info` changes for printers that were
  mislabelled `X1C` (see Fixed), which starts a new series. Update Grafana panels and alerts
  that select on `model`.
- `bambulab_door_open` changes source for those printers (from `home_flag` to `stat`), and
  `bambulab_lid_open` starts reporting for H2 printers.
- A printer whose serial prefix, product name and `BAMBULAB_PRINTER_MODEL` are all
  unrecognized now has no `bambulab_printer_model_info` series instead of a guessed model.

## [0.1.40] - 2026-03-22

### Added
- **`bambulab_xcam_halt_print_sensitivity_info`** metric: exposes the
  `print.xcam.halt_print_sensitivity` MQTT field as an info-labeled gauge with a `level`
  label (`low`, `medium`, or `high`). The gauge is set to `1` for the current level and
  cleared on each update cycle. Unrecognised or missing values produce no metric.
  - New `xcam_halt_print_sensitivity` property on `PrinterSnapshot` (normalises to
    lowercase; returns `None` for missing/invalid values).
  - 17 new unit tests across `test_models.py` and `test_metrics.py` covering all three
    levels, case normalisation, missing/unknown handling, and clear-on-update behaviour.
  - Existing `bambulab_xcam_feature_enabled` metric is unchanged.

## [0.1.39] - 2026-03-22

### Added
- **Automatic cloud token refresh** (`cloud_auth.py`, `startup.py`): When the cloud access
  token is invalid at startup, the exporter now silently refreshes it via
  `BAMBULAB_CLOUD_REFRESH_TOKEN` before falling back to email/2FA re-authentication.
  - `refresh_access_token()` in `cloud_auth.py` uses the existing multi-base request pattern
    and returns an updated `LoginResult` with new `access_token` + `refresh_token`.
  - Two new exception types for precise error classification:
    - `CloudAuthInvalidError`: credentials definitively rejected (HTTP 401/403 or error
      body); triggers 2FA fallback.
    - `CloudAuthTransientError`: network/server issue (connection error, 5xx); does **not**
      force 2FA, surfaces a clear transient error instead.
  - On successful refresh, updated credentials are persisted to the encrypted store (when
    `BAMBULAB_SECRET_KEY` is set) and synced to `.env`.

### Tests
- 9 new unit tests covering the full refresh-token decision tree: happy-path bypass, invalid
  refresh → 2FA fallback, transient error → no forced 2FA, credential persistence, and HTTP
  4xx/5xx classification.
- Reverted test layout to flat `tests/unit/` structure (no process-domain subdirectories) for
  consistency with the existing test suite.
- Coverage raised to **97.22%** (401 tests, threshold: 90%).

## [0.1.38] - 2026-03-22

### Fixed
- Unraid template `WebUI` URL now opens the exporter landing page root (`/`) instead of `/metrics`, fixing the default click-through behavior in Unraid.

### Changed
- Simplified and clarified the Unraid template `Overview` copy with concise setup and operational guidance.
- Landing page status cards now center health/readiness content for cleaner visual alignment.
- Added footer credit on the landing page: "Created by TheBlackBush".
- `RELEASE_RULES.md` was removed from repository tracking and is now local-only workflow guidance.

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
- Existing AMS-scoped metrics (`bambulab_ams_unit_humidity*`, `bambulab_ams_slot_*`) retain their original label sets unchanged; model/series is only available via `bambulab_ams_unit_info`
- **Gen2 drying telemetry metrics** (emitted only when `ams_info` is present):
  - `bambulab_ams_heater_state_info{...,ams_id,ams_model,ams_series,state}=1`: heater/dry state (bits 4-7)
  - `bambulab_ams_dry_fan_status{...,ams_id,ams_model,ams_series,fan_id}`: fan1/fan2 state (bits 18-21)
  - `bambulab_ams_dry_sub_status_info{...,ams_id,ams_model,ams_series,state}=1`: drying sub-status (bits 22-25)
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
