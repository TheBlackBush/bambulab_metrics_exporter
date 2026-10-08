# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Quick Reference

```bash
# setup (root .venv is the convention; Makefile targets assume it)
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pip install -e .

make test                     # full suite, coverage gate 90% (required before handoff)
make lint                     # ruff check src tests
.venv/bin/python -m mypy src  # strict; tests are excluded

# single file / single test: pass --no-cov, otherwise the global 90% coverage gate fails
.venv/bin/python -m pytest -q --no-cov tests/unit/test_metrics.py
.venv/bin/python -m pytest -q --no-cov tests/unit/test_metrics.py::test_metrics_update_smoke
.venv/bin/python -m pytest -q --no-cov -k "ams and not cloud"
```

Pytest output (coverage XML, `.coverage`, cache) goes to `tests/results/`; do not commit it.

# Common Pitfalls

- Running `bambulab-exporter` is a live operation: it probes a real printer or Bambu Cloud and
  may rewrite `.env`. Verify changes through tests (fake clients), not by starting the app.
- Raw MQTT state is cumulative (deep-merged, never cleared on disconnect), so metrics can
  show stale values while `bambulab_printer_connected` is 0. Absence of a field in a new
  message does not mean the value was removed.
- New telemetry usually touches three places in lockstep: a property in `models.py`
  (`PrinterSnapshot`), the gauge and update logic in `metrics.py`, and tests in
  `tests/unit/test_models.py` / `tests/unit/test_metrics.py`, plus
  `docs/wiki/Metrics-Reference.md`, `examples/sample_metrics.prom`, and `CHANGELOG.md`.
- `mqtt-samples/` and `examples/sample_mqtt_message.json` may contain device-derived data.
  Sanitize anything derived from them before adding fixtures.

# Project Overview

This repository is a Python 3.11+ Prometheus exporter for Bambu Lab 3D printers. It is
intended for self-hosted and homelab operators who run one exporter process or container
per printer and scrape it with Prometheus. Docker is the supported production deployment;
the project is packaged locally for its container and development environment, not
published to PyPI.

The runtime flow is:

```text
Bambu Lab printer or cloud broker
  -> TLS MQTT report topic
  -> cumulative, lock-protected raw state
  -> PrinterSnapshot tolerant property adapter
  -> PollingCollector
  -> ExporterMetrics private Prometheus registry
  -> FastAPI /metrics, /health, /ready, and / endpoints
```

The primary external systems are a printer's LAN MQTT broker or Bambu Cloud MQTT and
HTTP APIs, Prometheus, Grafana, Docker/GHCR, and the optional Unraid deployment template.
There is no Home Assistant integration (one parser comment only references its behavior),
and there are no Kubernetes or Helm resources.

Important boundaries:

- `client/` owns transport and MQTT lifecycle; `models.py` interprets cumulative raw
  telemetry; `metrics.py` owns public time-series behavior; `collector.py` schedules
  polling; `api.py` exposes the registry.
- Cloud authentication and encrypted persistence span `cloud_auth.py`, `startup.py`,
  `main.py`, `credentials_store.py`, `security.py`, and `env_sync.py`. Treat them as one
  security-sensitive subsystem.
- A process has one serial, client, state store, registry, and collector. Multiple printers
  require separate processes/containers. Do not imply same-process multi-printer support.
- Model recognition is broader than hardware validation. The README says real-world
  development and validation currently occur only on an X1C.

# Repository Map

## Runtime source

- `src/bambulab_metrics_exporter/main.py`: `bambulab-exporter` entry point and composition
  root. It loads `.env`, applies `/auth` page overrides, bootstraps cloud credentials,
  starts `ExporterRuntime`, creates FastAPI, and runs Uvicorn immediately. Changes affect
  every deployment and require broad tests.
- `src/bambulab_metrics_exporter/runtime.py`: `ExporterRuntime`, the background connection
  lifecycle (states `starting`, `connecting`, `running`, `setup_required`, `auth_required`,
  `error`). It validates, starts the collector, retries every 60 s, waits for credentials,
  and rebuilds settings/metrics/client on `reconfigure()`. The process never exits on
  connection problems.
- `capabilities.py`: per-model hardware table (chamber sensor/heater, door source, lid, aux
  and chamber fans, extruders, hotend rack, laser/cutter). Gate model-specific metrics with
  `PrinterSnapshot.capabilities` instead of checking model names; unknown models are
  permissive. Keep it in sync with the wiki "Supported models" table.
- `auth_actions.py` and `overrides.py`: backend for the `/auth` page. Overrides are stored
  encrypted (`connection-overrides.enc.json`) and take precedence over env vars;
  `overrides.set_env` records original values so reset can restore them.
- `src/bambulab_metrics_exporter/config.py`: Pydantic settings, defaults, and basic
  validation. Coordinate changes with `.env.example`, Compose, Unraid, wiki docs,
  startup validation, and config tests.
- `src/bambulab_metrics_exporter/startup.py`: mandatory startup connection probes, cloud
  token refresh, OTP recovery, and credential persistence. Do not change failure policy
  without cloud/local startup tests and operator documentation.
- `src/bambulab_metrics_exporter/client/`: `BambuClient` interface, local MQTT
  implementation, cloud adapter, and transport factory. Topic, TLS, QoS, merge, or
  reconnect changes need focused MQTT tests and broader review.
- `src/bambulab_metrics_exporter/models.py`: large tolerant adapter from raw nested MQTT
  data to normalized properties, model detection, AMS interpretation, flags, and stage
  names. Prefer focused additions; avoid broad rewrites. Changes are tightly coupled to
  `metrics.py` and `tests/unit/test_models.py`.
- `src/bambulab_metrics_exporter/metrics.py`: all public metric definitions and snapshot
  updates. Metric names, types, labels, and missing-value behavior are API contracts.
  Coordinate changes with model parsing, tests, metric docs, sample exposition, Prometheus
  rules, and Grafana assets.
- `src/bambulab_metrics_exporter/collector.py`: daemon polling thread, error boundary,
  readiness, and scrape self-metrics. Lifecycle changes require failure/recovery and
  shutdown tests.
- `src/bambulab_metrics_exporter/api.py`: FastAPI landing page and `/metrics`, `/health`,
  `/ready`, plus `/auth` (HTML), `/auth/status` (JSON) and form posts `/auth/local`,
  `/auth/cloud/send-code`, `/auth/cloud/login`, `/auth/reset` when built with a runtime.
  `/health` is process liveness; `/ready` becomes ready after a nonempty payload (sticky).
  `/auth` is unauthenticated by maintainer decision; keep its protections: escaped output, no
  stored secrets rendered, same-origin check, Host allowlist (`_host_allowed`, DNS rebinding,
  `AUTH_ALLOWED_HOSTS`), anti-framing headers (middleware), 8 KB form cap, send-code and login
  rate limits, per-visitor result cookie, and `overrides.lock` around every page change.
  Preserve endpoint contracts.
- `src/bambulab_metrics_exporter/cloud_auth.py`: Bambu Cloud HTTP/OTP CLI, token refresh,
  device discovery, bounded HTTP retry/backoff, and credential output. Never expose
  response bodies, emails, tokens, codes, or device IDs carelessly.
- `credentials_store.py`, `security.py`, `env_sync.py`: Fernet credential encryption,
  restrictive permissions, and `.env` persistence. Broad review is required for format,
  key derivation, permission, or allow-list changes.
- `flags.py` and `logging_utils.py`: bit/flag helpers and logging setup. Keep helpers small
  and tested.
- `templates/` and `static/`: packaged landing-page assets. Preserve packaging entries in
  `pyproject.toml`; API tests cover rendering behavior.

## Tests and fixtures

- `tests/unit/`: primary behavior suite for API, auth, collection, configuration, MQTT,
  metrics, models, security, startup, and helpers. Add regression tests beside the owning
  module.
- `tests/integration/test_api_contract.py`: HTTP/exposition contract without a real printer.
- `tests/e2e/test_collector_cycle_e2e.py`: deterministic collector-to-HTTP flow using a fake
  client, not live hardware.
- `examples/sample_mqtt_message.json` and `mqtt-samples/`: recorded/sample telemetry. Treat
  these as potentially device-derived and sensitive. Inspect before reuse; sanitize all new
  fixtures.
- `examples/sample_metrics.prom`: sample exposition that should track metric behavior.
- `tests/fixtures/printers/`: one sanitized real payload per model (12 from ha-bambulab,
  MIT, attribution in its README; one from the maintainer's X1C), checked by
  `tests/unit/test_printer_fixtures.py`. Add new captures only through
  `sanitize_fixture.py` and review the output; never commit a raw capture.

## Packaging, deployment, and automation

- `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`: package metadata, console
  entry points, dependency bounds, pytest/coverage, Ruff, and strict mypy configuration.
  Dependency changes require justification, compatibility review, and container validation.
- `Makefile`: supported local test profiles and lint target. Do not document nonexistent
  targets.
- `Dockerfile` and `entrypoint.sh`: Python 3.11 slim image, package installation, dynamic
  PUID/PGID/umask setup, config ownership, and privilege drop through `gosu`. Preserve the
  non-root application runtime.
- `docker-compose.yml`: cloud-first Compose example, port 9109, `.env` and config mounts,
  and `/health` healthcheck. Note that its transport default differs from the application's
  local default.
- `unraid-bambulab-metrics-exporter.xml`: supported Unraid template. Coordinate ports,
  paths, variables, secret masking, and image behavior with Docker changes.
- `.github/workflows/ci.yml`: compile, Ruff, and full pytest checks on pull requests to
  `main` and `develop`.
- `.github/workflows/docker-publish.yml`: release-only full checks (including mypy), then
  amd64/arm64 GHCR build and publish (`<version>` and `latest` tags).
- `.github/workflows/docker-develop.yml`: on every push to the `develop` branch, the same
  full checks, then amd64/arm64 GHCR images tagged `develop` and `develop-<short-sha>`.
  Never publishes `latest` or version tags. Feature branches target `develop`; `develop`
  merges into `main` for releases.
- `.github/workflows/wiki-sync.yml`: syncs `docs/wiki/*.md` to the GitHub Wiki on `main`.
- `scripts/` and `config/` currently contain no tracked implementation files. Do not invent
  validation commands for them.

## Documentation and integrations

- `README.md`: user overview, quick start, metric summary, testing, limitations, and links.
- `docs/wiki/`: canonical operator installation, configuration, Prometheus, metric, Grafana,
  and troubleshooting documentation. Wiki changes on `main` are published automatically.
- `examples/prometheus/`: scrape, alert, and recording-rule examples.
- `examples/grafana/`: supported dashboard JSON and screenshot. Dashboard changes can be
  large; give one agent exclusive ownership and validate metric references.
- `CHANGELOG.md`: public compatibility and release history. Update for user-visible changes,
  especially metrics, configuration, security, and deployment behavior.
- `LICENSE`: GPL-3.0 license; do not change without explicit maintainer direction.

# Architecture and Data Flow

## Startup

1. The `bambulab-exporter` console script calls `main.run()`.
2. `.env` is loaded best-effort without overriding existing process variables, then saved
   `/auth` page overrides are applied over the environment.
3. Cloud mode may load an encrypted credential file when an explicit user/token pair is
   absent and `BAMBULAB_SECRET_KEY` is available.
4. `ExporterRuntime` starts its background thread and Uvicorn starts serving immediately.
5. The runtime reads `Settings`; missing required settings give `setup_required` (no exit).
   Cloud mode may discover the printer name/model from the cloud device list.
6. `startup.startup_validate` performs a live MQTT connection probe. `startup._probe` returns
   `ok`, `rejected` (only a CONNACK 4/5 refusal, via `BambuClient.auth_rejected`) or
   `unreachable` (connect failure, timeout, printer not answering). Local failure raises and
   the runtime retries every 60 s. Cloud mode (`startup._validate_cloud`, updates `settings`
   in place) tries env credentials, then the encrypted store if it differs, then the refresh
   token, then the legacy `BAMBULAB_CLOUD_EMAIL`/`BAMBULAB_CLOUD_CODE` login (at most one OTP
   email and one try per code value per process). `unreachable` at any step raises a plain
   `RuntimeError` (retried, never re-auth or OTP). Only rejections end in
   `ReauthRequiredError`; the runtime then logs a banner and waits for a `/auth` login, a
   change of the encrypted store (written by `bambulab-reauth`), or the 5-minute re-check.
7. Allowed runtime values are synchronized to `.env` (best-effort mode `0600`), excluding keys
   that currently come from `/auth` overrides (`overrides.overridden_keys()`), and the
   collector starts with a client built from the validated settings. The metrics registry is
   rebuilt whenever the printer label or serial changes (`ExporterRuntime._ensure_metrics`),
   including after cloud discovery fills in the printer name.

Running the application locally is therefore not an offline smoke test: it requires valid
configuration and reachable printer/cloud services and may update `.env`.

## Connection and message lifecycle

- Local MQTT authenticates with `BAMBULAB_USERNAME` (default `bblp`) and the LAN access code.
  Cloud MQTT reuses the same implementation with the cloud host/port, username
  `u_<cloud-user-id>`, and access token as password.
- Both transports use TLS but currently set `CERT_NONE` and insecure verification. This is
  documented compatibility behavior and a security limitation, not proof that the channel
  authenticates the broker. TLS is capped at 1.2 (`client/local_mqtt._tls_context`): P2S
  firmware 01.02.00.00 never answers a TLS 1.3 ClientHello.
- The client subscribes at QoS 1 to `device/<serial>/report` after a successful connection.
  Paho's network loop owns callbacks and may handle underlying reconnects, but this code
  configures no explicit retry/backoff policy. `RECONNECT_INTERVAL_SECONDS` is currently
  unused; do not claim it controls reconnect behavior.
- By default, each fetch publishes one QoS 1 `pushall` snapshot request to
  `device/<serial>/request`, and each successful connect publishes one QoS 1 `get_version`
  request (module list with product names, used for model detection). These are the only
  publishes; both are read-only telemetry requests, not printer-control operations. Setting
  `BAMBULAB_REQUEST_PUSHALL=false` disables both and makes collection subscription-driven.
- Exact-topic messages are decoded as UTF-8 JSON and recursively merged under a lock into
  `_latest_state`: dictionaries merge; lists and scalar values replace. Partial reports
  retain previously received fields. Fetch returns a deep copy after state exists or the
  configured timeout elapses.
- State is not cleared on disconnect. Metrics can retain previous telemetry while
  `bambulab_printer_connected` reports 0. `_last_message_ts` is not used for freshness.
  Preserve or deliberately migrate these semantics; never assume absence means deletion.
- `PrinterSnapshot` reads the raw dictionary defensively and resolves model-specific fields.
  Unknown and missing firmware fields should not crash the collector.

## Collection, exposition, and shutdown

- `PollingCollector` connects once, starts one daemon thread, fetches at the configured
  cadence, updates metrics, and catches broad per-cycle exceptions so the loop continues.
  Every cycle records exporter scrape duration/success; successful cycles update the last
  success timestamp.
- Readiness becomes true after the first nonempty raw snapshot and is sticky. Health is
  currently unconditional process liveness. Do not describe either as ongoing printer
  connectivity.
- `ExporterMetrics` uses a private `CollectorRegistry`, preventing unrelated default-process
  metrics and isolating instances. FastAPI serializes this registry at `/metrics`.
- On application shutdown, `runtime.stop()` wakes the runtime thread and joins it for up to
  10 seconds; the collector stop event is set, its thread is joined for up to `REQUEST_TIMEOUT_SECONDS` + 2 s (at least 5 s),
  and MQTT disconnects.
- Tests: `tests/conftest.py` restores `os.environ` and the override/legacy-login state after
  every test, and blocks all outbound sockets and DNS: any test that would reach a printer,
  broker or Bambu Cloud fails with "network access blocked in tests". Stub `startup._probe`
  (not `_probe_connection`) in cloud validation tests.

# Development Environment

Use Python 3.11 or newer. The repository convention is a root `.venv`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e .
```

`pip install -e '.[dev]'` is also supported by the package metadata/README. CI uses the two
explicit requirements/editable-install commands above.

Run locally only with a sanitized, valid `.env` and reachable configured service:

```bash
.venv/bin/bambulab-exporter
```

Cloud credential helper:

```bash
.venv/bin/bambulab-cloud-auth --help
```

Tests and validation:

```bash
make test                 # complete suite, coverage >= 90%
make test-unit            # unit subset; global coverage gate still applies
make test-integration     # integration subset, --no-cov
make test-e2e             # e2e subset, --no-cov
make test-profile         # deterministic integration + e2e smoke profile
make lint                 # Ruff check of src and tests
.venv/bin/python -m mypy src
.venv/bin/python -m compileall -q src tests
```

Mypy is strict and excludes tests. PR CI runs compileall, Ruff, and pytest; release CI also
runs mypy. There is no configured formatter command or Make target. Keep style consistent
and Ruff-clean, but do not claim `make format` exists. There is also no repository-provided
dependency scanner, security scanner, container linter, or docs validator.

Docker commands supported by repository documentation:

```bash
docker build -t bambulab-metrics-exporter:latest .
docker compose up -d
docker compose up -d --build
```

Compose uses `.env`, mounts it into `/app/.env`, and may allow runtime synchronization to
modify the host file. Never run it casually against production credentials. The application
uses port 9109; container health probes `/health`.

# Configuration

Environment variable names are case-insensitive through Pydantic, but documentation and
deployment files use uppercase. Use only fake values in code, tests, documentation, and
reports. “Sensitive” includes operational identifiers even when they are not authentication
secrets.

| Variable | Required / default | Purpose and expected format | Sensitive? | Fake example |
|---|---|---|---|---|
| `APP_NAME` | optional; `bambulab-metrics-exporter` | Internal application name string; currently little runtime use | no | `bambulab-metrics-exporter` |
| `LOG_LEVEL` | optional; `INFO` | Python log level such as `DEBUG`, `INFO`, `WARNING`, `ERROR` | no | `INFO` |
| `BAMBULAB_TRANSPORT` | optional; `local_mqtt` | Exactly `local_mqtt` or `cloud_mqtt` | no | `local_mqtt` |
| `BAMBULAB_HOST` | local required; empty | LAN printer IPv4/IPv6 host or DNS name | operational | `192.0.2.25` |
| `BAMBULAB_PORT` | optional; `8883` | LAN MQTT TLS port integer | no | `8883` |
| `BAMBULAB_SERIAL` | required; empty | Device ID used in MQTT topics; use a synthetic value in tests | operational | `FAKE00TEST000001` |
| `BAMBULAB_ACCESS_CODE` | local required; empty | LAN MQTT password/access code | **secret** | `fake-access-code` |
| `BAMBULAB_USERNAME` | optional; `bblp` | LAN MQTT username | operational | `bblp` |
| `BAMBULAB_REQUEST_PUSHALL` | optional; `true` | Boolean controlling the `pushall` and on-connect `get_version` requests | no | `true` |
| `BAMBULAB_CLOUD_MQTT_HOST` | optional; `us.mqtt.bambulab.com` | Cloud broker DNS name | no | `us.mqtt.bambulab.com` |
| `BAMBULAB_CLOUD_MQTT_PORT` | optional; `8883` | Cloud MQTT TLS port integer | no | `8883` |
| `BAMBULAB_CLOUD_USER_ID` | cloud conditional; empty | Cloud user identifier; needed with access token | **secret/identity** | `fake-user-123` |
| `BAMBULAB_CLOUD_ACCESS_TOKEN` | cloud conditional; empty | Cloud API/MQTT bearer credential; paired with user ID | **secret** | `fake-access-token` |
| `BAMBULAB_CLOUD_REFRESH_TOKEN` | optional; empty | Token used to refresh cloud access; can avoid OTP reauth | **secret** | `fake-refresh-token` |
| `BAMBULAB_CLOUD_EMAIL` | required for cloud recovery when usable tokens are absent; empty | Account email used to send OTP | **personal** | `operator@example.invalid` |
| `BAMBULAB_CLOUD_CODE` | bootstrap only; empty | Single-use email OTP; remove after authentication | **secret** | `000000` |
| `BAMBULAB_CONFIG_DIR` | optional; `/config/bambulab-metrics-exporter` | Directory for encrypted credentials | sensitive path | `/tmp/fake-bambu-config` |
| `BAMBULAB_CREDENTIALS_FILE` | optional; `credentials.enc.json` | Encrypted credential filename | sensitive artifact | `credentials.enc.json` |
| `BAMBULAB_SECRET_KEY` | required to persist/recover cloud credentials; empty | Stable high-entropy encryption secret | **secret** | `fake-development-key-never-use` |
| `POLLING_INTERVAL_SECONDS` | optional; `10.0` | Positive float between collector cycles | no | `10` |
| `REQUEST_TIMEOUT_SECONDS` | optional; `8.0` | Positive float for snapshot/cloud requests | no | `8` |
| `RECONNECT_INTERVAL_SECONDS` | optional; `5.0` | Declared and persisted but currently unused by runtime reconnect logic | no | `5` |
| `LISTEN_HOST` | optional; `0.0.0.0` | Uvicorn bind host | no | `127.0.0.1` |
| `LISTEN_PORT` | optional; `9109` | Uvicorn TCP port integer | no | `9109` |
| `AUTH_ALLOWED_HOSTS` | optional; empty | Extra Host names accepted by `/auth`, comma separated (IPs and local names always allowed) | operational | `exporter.example.invalid` |
| `PRINTER_NAME_LABEL` | optional; empty | Canonical stable operator override for `printer_name` label | operational/user text | `test-printer` |
| `BAMBULAB_PRINTER_NAME` | optional; empty | Discovered/persisted printer name and fallback label | operational/user text | `Test Printer` |
| `BAMBULAB_PRINTER_MODEL` | optional; empty | Discovered/persisted model; normalized model-detection hint after serial prefix | operational | `X1C` |
| `PUID` | container optional; `99` | Runtime numeric UID interpreted by `entrypoint.sh` | no | `1000` |
| `PGID` | container optional; `100` | Runtime numeric GID interpreted by `entrypoint.sh` | no | `1000` |
| `UMASK` | container optional; `002` | Shell umask consumed by `entrypoint.sh` | no | `022` |

Cloud transport accepts either a user-ID/access-token pair or an email for recovery at early
configuration validation; startup persistence additionally requires the secret key. Local
transport requires host, serial, and access code. The cloud auth CLI can discover serial,
printer name, and model.

`PRINTER_NAME`, `SITE`, and `LOCATION` are obsolete/inactive despite stale appearances in
`.env.example`, Compose, and the Unraid template. New work must use `PRINTER_NAME_LABEL` and
must not describe site/location labels as supported. Do not “fix” this drift incidentally in
an unrelated task; coordinate a focused deployment-doc update.

`.env`, config directories, access codes, tokens, OTPs, secret keys, encrypted credential
files, emails, real serials, IPs, and personal printer names must never appear in commits or
agent output. Credential parent directories are intended to be `0700`, credential files and
`.env` `0600`; preserve those protections.

# Prometheus Metric Rules

Metrics are a public compatibility surface.

- All existing exporter metrics use prefix `bambulab_`; exporter-internal poll metrics use
  `bambulab_exporter_`. Use lowercase snake case.
- Every current project metric is a Gauge. Use Gauge for current telemetry, temperatures,
  flags, levels, timestamps, and one-hot/info state. Use Counter only for a monotonically
  increasing event total that survives reset semantics conceptually. Use Histogram only for
  a measured distribution with reviewed buckets. Do not introduce Summary without a strong
  aggregation reason. Never change an existing metric type silently.
- Put units in metric names: `_seconds`, `_temperature_celsius`, `_percent`, `_ratio`,
  `_minutes`, and `_unixtime` are existing conventions. Do not retrofit inconsistent legacy
  names (`spd_lvl`, `spd_mag`, `wifi_signal`, `nozzle_diameter`) without a migration.
- Every series currently carries stable `printer_name` and `serial` base labels. Label names
  are lowercase snake case. Adding, removing, or changing a label changes series identity
  and is breaking.
- Prefer numeric scalar gauges. For bounded enumerations, use stable fixed one-hot/info
  labels with value 1 and clear old children before setting new ones. Label values must be
  normalized, bounded, documented, and stable across firmware updates.
- Missing scalar telemetry is emitted as `NaN`. Dynamic labeled/info series are cleared and
  omitted when absent. Fixed unknown gcode/speed states map to `UNKNOWN`; some stage/status
  code paths deliberately emit `unknown_<numeric-code>`. Preserve these distinctions unless
  an explicit migration is requested.
- Never add labels containing filenames/job names, full error messages or reasons,
  timestamps, raw MQTT payloads, user-generated text, arbitrary IDs, tokens, or other
  unbounded values. Existing `subtask_name` and `fail_reason` labels are legacy cardinality
  risks preserved for compatibility, not precedents. Review raw tray/spool/nozzle metadata
  and numeric-derived unknown labels carefully before extending them.
- IDs such as AMS/slot/extruder IDs must be device-bounded and normalized. Do not expose
  cloud IDs, sequence IDs, or arbitrary payload identifiers.
- Continue using an instance-private `CollectorRegistry`. Prevent duplicate registration and
  stale child series. Do not register against the global registry without architectural
  review.
- Preserve legacy aliases such as `bambulab_print_error_code` when compatibility requires
  them. Removal or rename requires explicit approval, a deprecation/migration plan, a
  changelog entry, and updates to tests, `docs/wiki/Metrics-Reference.md`, README/sample
  exposition, Prometheus rules, and Grafana queries.
- Any new/modified metric needs tests for registration, exact name/type/help, labels, values,
  missing/unknown behavior, stale-child clearing, and exposition text where appropriate.

# Bambu Lab and MQTT Safety Rules

- Treat printers, brokers, cloud APIs, networks, and firmware payloads as unreliable.
  Timeouts, disconnects, partial reports, absent nested objects, extra unknown fields,
  malformed types, and out-of-order state are normal inputs.
- Keep parsers tolerant and backward compatible. Unknown fields must be ignored. Missing or
  malformed fields must not crash the polling thread. Preserve previously supported payload
  paths and model fallbacks unless tests and migration documentation justify removal.
- Validate configured transport, positive timeouts, ports/ranges, host values, and serial
  values before using them in topics or connections. Existing validation is incomplete for
  host and serial shape; do not assume it is sufficient.
- The report subscription is passive. The existing `pushall` and `get_version` publishes are
  narrowly scoped read-only requests and are on by default. Do not add print, pause, stop, movement,
  temperature, light, calibration, firmware, or any other printer-control publish unless the
  task explicitly requests it and the user approves live-device risk. Keep the exporter
  operationally read-only by default.
- Never send traffic to a real printer in automated tests. Use fake clients and sanitized
  MQTT messages. A local `bambulab-exporter` run and startup probe are live operations.
- Do not log access codes, tokens, OTPs, secret keys, encrypted blobs, full payloads, emails,
  or HTTP response bodies. Minimize logging of serial-bearing topics, hosts, usernames, and
  personal printer names; they are operationally sensitive.
- Avoid tight reconnect/poll loops. Use interruptible waits and bounded retry/backoff when
  adding retry behavior. The collector has a minimum 0.1-second wait; cloud HTTP retries are
  bounded with exponential backoff; MQTT currently has no explicit configured retry policy.
- Preserve QoS 1 topics and TLS behavior unless intentionally changing compatibility. Never
  disable TLS entirely or disable verification merely to make a test pass. Conversely, do
  not silently enable verification: both MQTT modes currently disable certificate checking,
  and a secure migration needs broker/printer compatibility research, configuration design,
  tests, and operator documentation.
- Protect shared state with the existing lock and return copies. Changes to deep-merge,
  state clearing, freshness, readiness, or disconnect semantics require sequential work
  across client, collector, models, metrics, and tests.

# Coding Standards

- Follow Python 3.11+, PEP 8-style lowercase snake case for functions/variables/modules,
  PascalCase for classes, and uppercase constants. Keep lines at or below Ruff's configured
  100 characters.
- Type all production function signatures and meaningful containers. Mypy is strict for
  `src`; avoid `Any` except at untrusted payload boundaries, then narrow explicitly.
- Keep imports grouped as standard library, third party, then project imports. Remove unused
  imports; Ruff is authoritative for configured lint rules.
- Preserve the layered organization: transport code does not define metric semantics;
  models do not perform network I/O; API handlers do not parse MQTT; composition stays in
  `main.py`.
- Prefer small pure helpers and narrow properties over adding more complexity to already
  large `models.py` and `metrics.py`. Do not split or rewrite those modules incidentally.
- At untrusted boundaries, validate types before conversion. Catch specific exceptions when
  recovery differs; broad exceptions are acceptable only at process/thread safety boundaries
  where they are logged and the service can continue.
- Use module loggers. Log actionable context without secrets or raw payload content. Maintain
  exception chaining for translated errors. Do not turn transient cloud failures into forced
  OTP recovery.
- Add docstrings where behavior, compatibility, security, bit flags, units, or model-specific
  fallbacks are not obvious. Comments should explain why, not restate code.
- Add dependencies only when existing standard-library/project facilities cannot reasonably
  solve the problem. Pin compatible ranges in the correct requirements file, assess image
  size/security/license impact, and validate editable install, mypy, tests, and Docker build.
- Prefer focused diffs. Preserve public console entry points, endpoint contracts, metrics,
  environment names/defaults, topic/QoS semantics, and credential formats unless a breaking
  change is explicitly requested and documented.

# Testing Requirements

Every behavior change requires the smallest relevant tests plus regression coverage for the
reported bug. Tests must be deterministic and must not require a real printer, cloud account,
email OTP, external broker, or internet connection. Existing “integration” and “e2e” tests
use fakes and remain offline.

- Parser/model changes: representative sanitized partial payloads; absent parent and leaf
  fields; unknown extra fields; wrong types; unknown codes/models/firmware variants; and
  compatibility with existing payload paths.
- MQTT changes: topic filtering, QoS and subscriptions, malformed JSON and UTF-8, non-object
  JSON, deep merge of partial state, timeout behavior, connection failure, disconnect,
  reconnect/resubscribe behavior, and publish assertions. Assert no control command is sent.
- Collector changes: connect/disconnect cleanup, fetch failure, failed scrape marker,
  recovery on a later cycle, polling wait behavior, readiness, and shutdown. Use events/fakes
  instead of timing-heavy sleeps.
- Config/startup changes: required local/cloud combinations, invalid transport, invalid
  numeric values, host/serial validation when introduced, credential refresh versus OTP,
  transient failures, persistence errors, and redacted error/log output.
- Metric changes: registry isolation, duplicate-registration prevention, exact names/types,
  base and dynamic labels, values, `NaN`, unknown states, clearing/omitting stale dynamic
  series, and Prometheus exposition. Test compatibility aliases.
- Multi-printer work, if explicitly requested, needs isolation tests for state, clients,
  labels, registries, failures, and duplicate metrics. Current behavior is one printer per
  process; do not add a superficial multi-printer test that implies otherwise.
- API/deployment changes: endpoint status/body/content type, readiness/liveness semantics,
  healthcheck compatibility, configured ports, and graceful shutdown.
- Never commit real serial numbers, IPs, hostnames, usernames, emails, access codes, tokens,
  secret keys, certificates, private keys, printer names, or personal MQTT content. Use
  reserved addresses such as `192.0.2.0/24`, `.invalid` domains, and obviously fake IDs.

Run `make test` for repository-wide coverage before completion. The configured gate is 90%
for `src/bambulab_metrics_exporter`; the suite on the cloud re-auth branch had 568 passing
tests and 97.24% coverage. Subset commands are useful during iteration but are not a substitute for
the full suite. Run mypy for production changes even though PR CI currently omits it.

# Documentation Requirements

Update documentation in the same change whenever behavior changes:

- Metrics: `docs/wiki/Metrics-Reference.md`, relevant README tables/migration notes,
  `examples/sample_metrics.prom`, Prometheus alerts/recording rules, Grafana dashboard, and
  `CHANGELOG.md` as applicable.
- Environment/settings: `config.py`, `.env.example`, `docs/wiki/Configuration.md`, README,
  Compose, Unraid, and cloud-auth instructions. State exact conditional requirements and
  defaults.
- Docker/runtime: README and `docs/wiki/Installation.md`; keep ports, volumes, healthchecks,
  PUID/PGID/umask, config ownership, and architectures synchronized.
- Printer/model/MQTT: README implementation/limitations, metrics reference, troubleshooting,
  sanitized samples, and changelog. Distinguish detected models from real-hardware validation.
- Installation, Grafana, Prometheus, breaking behavior, or deployment configuration: update
  the matching file under `docs/wiki/` and examples. Never invent Home Assistant or
  Kubernetes support.

Documentation has known drift: stale `PRINTER_NAME`/`SITE`/`LOCATION` examples, incomplete
refresh-token/credential-file tables, token refresh still listed as future work, and outdated
cloud troubleshooting. Treat these as current debt and avoid copying the stale claims.

# Git and Change Management

- Inspect `git status` before work. User and other-agent changes are not yours to discard.
  Never reset, overwrite, delete, or revert unrelated work.
- Make small, atomic commits only when asked. Use descriptive imperative messages such as
  `fix: tolerate malformed AMS tray ids` or `docs: document cloud refresh token`.
- Assign explicit file ownership before parallel edits. Do not let two agents edit the same
  file or tightly coupled behavior simultaneously.
- Avoid unrelated formatting, generated caches, coverage output, egg-info, credentials,
  `.env`, and large dashboard churn. Generated dashboard or sample output belongs in a diff
  only when deliberately required and reviewed.
- Review `git diff --check`, `git diff`, and `git status --short` before completion. Report
  every changed file and distinguish pre-existing changes.
- Call out migrations, deprecated behavior, metric/label identity changes, changed defaults,
  credential-format changes, and deployment impact. Breaking changes require explicit scope,
  documentation, and changelog treatment.
- Record validation commands exactly and report pass/fail/skip honestly. Never claim a check
  ran when it did not; explain environment-related failures.

# Autonomous Multi-Agent Workflow

Use subagents (the Agent tool) only when the task benefits from independent workstreams.
Roles below are optional, not a required ceremony. Use `Explore` or `Plan` subagents for
read-only investigation; give editing subagents `isolation: "worktree"` when parallel edits
could collide. The main session acts as the lead and owns integration.

The lead agent must:

1. Investigate the request, repository status, relevant code, tests, docs, and risks.
2. Define concrete workstreams and identify behavioral/file dependencies.
3. Build a sequencing map: independent read-only audits may run together; shared behavior
   and integration proceed sequentially.
4. Delegate only independent tasks in parallel.
5. Give every sub-agent exclusive file/directory ownership for edits and list forbidden files.
6. Prevent simultaneous edits to the same file and pause work when scope overlaps.
7. Require findings, changes, risks, compatibility impact, validation, and open questions.
8. Integrate centrally; the lead owns cross-file decisions and resolves inconsistencies.
9. Run repository-wide lint, mypy, tests, and affected deployment validation after integration.
10. Review the complete diff for secrets, unrelated changes, compatibility, docs, and
    acceptance criteria before reporting completion.

Every delegated task prompt must specify:

- **Objective:** one testable outcome.
- **Scope:** behavior and directories to investigate.
- **May modify:** exact exclusive paths, or “none” for read-only work.
- **Must not modify:** overlapping/shared/security-sensitive paths outside ownership.
- **Deliverables:** code, tests, docs, findings, or review expected.
- **Required tests:** exact commands or focused assertions.
- **Completion criteria:** observable conditions for acceptance.
- **Known dependencies:** upstream decisions and downstream consumers.
- **Final report:** the communication format below.

If a delegated discovery uncovers a change outside scope, it reports the finding instead of
editing. A sub-agent must stop and notify the lead before touching another agent's files.

# Suggested Agent Roles

## Repository Investigator

Maps structure, architecture, conventions, history, risks, and relevant paths. Makes no code
changes unless explicitly assigned.

## MQTT and Printer Protocol Agent

Owns focused review/work in `client/`, MQTT fixtures, and protocol tests. Validates partial
payloads, merging, connection lifecycle, topics/QoS, and firmware variation. Does not change
metrics or publish new commands unless assigned and approved.

## Prometheus Metrics Agent

Owns `metrics.py`, relevant metric/model tests, metric reference, and affected examples when
assigned together. Audits naming, units, types, labels, cardinality, clearing, registration,
and compatibility. Coordinates any parser requirement before editing `models.py`.

## Testing Agent

Finds gaps and adds sanitized fixtures/regressions for malformed and partial payloads,
failure/recovery, labels, and exposition. Does not change production behavior unless that
path is explicitly assigned.

## Docker and Deployment Agent

Reviews Dockerfile, entrypoint, Compose, GHCR workflow, Unraid, ports, mounts, healthchecks,
architectures, privilege dropping, and image size. Reports that Kubernetes is absent rather
than inventing it.

## Documentation Agent

Keeps README, wiki, configuration, metrics, Prometheus/Grafana examples, and changelog aligned
with verified behavior. Never advertises unsupported integrations or printer validation.

## Security and Reliability Reviewer

Reviews credentials, permissions, TLS, sensitive logging, cloud error bodies, retry loops,
state freshness, cleanup, and failure boundaries. Reports findings before broad security or
compatibility changes.

## Final Integration Reviewer

Reviews combined diff, runs all supported checks, checks code/test/docs consistency, finds
regressions and leaked data, and confirms acceptance criteria without adding unrelated scope.

# Parallel Work Rules

Usually safe in parallel when file ownership is distinct:

- Read-only documentation audit and test-gap analysis.
- Docker/Unraid review and Prometheus metric/cardinality audit.
- Protocol investigation and architecture/documentation mapping.
- Focused tests in separate test files while another agent performs a read-only deployment
  review.

Normally sequential or centrally coordinated:

- Multiple agents modifying `models.py` or the same parser/property.
- Multiple agents changing metric declarations, labels, or `metrics.py` update semantics.
- Refactoring MQTT/shared state while another agent changes collector/startup behavior.
- Model-resolution changes while metrics/model-specific flags are changing.
- Cloud auth changes while credential storage, `.env` synchronization, or startup recovery
  is changing.
- Editing the same README, wiki page, Compose file, Unraid template, dashboard, or config
  example.
- Changing dependency bounds or the virtual environment while another agent validates the
  old environment.

Explicit ownership is mandatory before any parallel edit. “Source code” is not sufficiently
specific ownership; assign exact files. The lead integrates shared documentation after code
behavior stabilizes.

# Agent Communication Format

Every sub-agent returns:

## Summary

What was investigated or changed and the outcome.

## Files Changed

Exact repository-relative paths, or `None`.

## Validation

Exact commands and results, including failures and unrun checks.

## Findings

Architecture evidence, bugs, risks, limitations, and relevant paths.

## Compatibility Impact

Effects on metric names/types/labels/values, configuration/defaults, MQTT topics/publishing/
TLS/state, printer/firmware support, credentials, API, or deployment.

## Open Questions

Anything not verifiable from repository evidence.

## Recommended Next Steps

Small, actionable follow-ups, separated from completed scope.

# Definition of Done

A task is complete only when:

- The requested behavior and acceptance criteria are satisfied with a focused diff.
- Relevant unit/regression/integration tests pass, and `make test` passes before final handoff.
- `make lint` and `.venv/bin/python -m mypy src` pass for affected Python code.
- Compile validation passes when Python structure/packaging changes.
- Docker build and relevant Compose/Unraid checks pass when container behavior is affected.
- Metrics, environment, Docker, models, MQTT, Grafana/Prometheus, and breaking changes have
  synchronized documentation and examples.
- No secrets, real device/personal information, private payloads, or credential artifacts
  were added or exposed.
- Metrics and public interfaces remain backward compatible unless an explicitly requested
  breaking change includes migration guidance.
- The full diff and status were reviewed; no unrelated or user changes were overwritten.
- Known limitations, skipped validation, compatibility risks, and follow-ups are reported.

# Prohibited Actions

Agents must not:

- Commit or expose `.env`, credentials, access codes, OTPs, tokens, secret keys, certificates,
  private keys, encrypted credential blobs, real printer IDs, personal names, or private MQTT
  payloads.
- Use real serials, IPs, hosts, usernames, emails, or access codes in fixtures/examples.
- Contact a real printer/cloud account or publish printer-control commands without explicit
  approval. The existing `pushall` and `get_version` requests are not permission to add controls.
- Disable TLS or TLS verification to make tests pass, or silently change the existing insecure
  verification compatibility behavior.
- Silently rename/remove metrics, change metric type/labels/missing-value semantics, or
  remove legacy aliases.
- Add unbounded labels, including filenames, full errors, timestamps, payloads, user text, or
  arbitrary IDs. Existing legacy exceptions are not precedent.
- Assume every Bambu model or firmware uses the same fields, or claim detected models are all
  hardware-validated.
- Perform broad refactors, rewrite working modules, or change public interfaces outside the
  assigned objective.
- Modify files outside assigned ownership, delete user code, revert unrelated work, or use
  destructive Git commands.
- Add generated caches/results/egg-info or reserialize large Grafana assets unless required.
- Invent scripts, commands, integrations, configuration, reconnect behavior, formatter
  support, or test results.

# Current Project Status

Evidence at the time this manual was created:

- Version `0.2.1`; Python 3.11+ package with FastAPI, Paho MQTT, Prometheus client,
  Pydantic settings, Uvicorn, cryptography/Fernet, and dotenv.
- Local and cloud MQTT modes work through the same client architecture. Cloud supports OTP
  authentication, encrypted credential persistence, and refresh-token recovery. Model
  detection recognizes A1/A1 Mini/A2L, P1P/P1S/P2S, H2C/H2D/H2D Pro/H2S, X1/X1C/X1E/X2D and
  AMS variants; only X1C is stated as real-world validated. The serial prefix (payload
  `print.sn` or configured `BAMBULAB_SERIAL`) is the main identity source because pushall
  omits identity fields. `print.device.type` is a mode bitmask and `print.model_id` an
  opaque job id; never use either for model identity.
- Docker, Docker Compose, GHCR amd64/arm64 releases, Unraid, Prometheus examples, Grafana
  dashboard, and GitHub Wiki publishing are present. Home Assistant and Kubernetes/Helm
  integrations are not present.
- Full validation observed during initialization: 417 tests passed with 97.25% coverage
  against a 90% gate. A focused metric/model run passed 306 tests; Ruff and strict mypy passed.
- All existing application metrics are Gauges in a private registry with `bambulab_` naming
  and base `printer_name`/`serial` labels. Missing scalars use `NaN`; dynamic info series are
  cleared/omitted. Existing `subtask_name` and `fail_reason` labels are cardinality debt.

Important technical debt and high-risk areas:

- MQTT certificate verification is disabled for both transports.
- MQTT has no explicit reconnect/backoff configuration; `RECONNECT_INTERVAL_SECONDS` is
  unused. Cumulative state survives disconnect, readiness is sticky, and health is unconditional.
- MQTT decode does not safely handle malformed UTF-8 or valid non-object JSON. Some AMS/tray
  integer conversions can raise on malformed payloads.
- Collector failure/recovery, reconnect/resubscribe, duplicate metric registration, secret
  redaction, and same-process multi-printer behavior lack explicit focused tests.
- `models.py` and `metrics.py` are large and tightly coupled; auth/persistence spans several
  modules. Changes need sequential coordination.
- Deployment documentation has obsolete label variables and gaps around refresh tokens and
  credential filenames. README future work and cloud troubleshooting lag implemented refresh.
- PR CI omits mypy; mypy runs only on release. No formatter, security scanner, docs validator,
  or Kubernetes validator is configured.

Implementation plans are kept locally in `.claude/plans/` (git-ignored, may be absent). If a
plan for the area you are working on exists there, read it first.

Recommended next tasks, each as a separately scoped change:

1. Correct stale environment/deployment/wiki documentation without changing runtime behavior.
2. Add malformed MQTT payload and collector failure/recovery regression tests, then make
   parsing safer with focused fixes.
3. Decide whether to implement bounded MQTT reconnect behavior or remove the inactive setting.
4. Design and test a deliberate TLS verification migration rather than silently toggling it.
5. Audit legacy high-cardinality labels and raw cloud error/serial logging with a compatibility
   and redaction plan.
6. Add PR-time strict mypy validation if maintainers want release-equivalent checks earlier.
