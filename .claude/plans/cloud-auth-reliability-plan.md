# Cloud Authentication Reliability Fix Plan

## Status (verified 2026-10-07)

Not started. Code on `main` still shows both root causes:

- `cloud_auth.refresh_access_token()` raises `CloudAuthInvalidError` only when
  `invalid_errors and not transient_errors`, so a 401 plus a DNS failure on another endpoint
  is still classified as transient.
- `main._bootstrap_cloud_credentials()` still returns early when both
  `BAMBULAB_CLOUD_USER_ID` and `BAMBULAB_CLOUD_ACCESS_TOKEN` are set, never consulting the
  encrypted store.

Related finding for Phase 5: the refresh error strings built in `refresh_access_token()`
include raw HTTP response bodies (`HTTP {code}: {body}`) and the server `error` field. Sanitize
them as part of the diagnostics work.

## Objective

Prevent expired Bambu Cloud credentials from trapping the exporter in a permanent startup
loop, especially on Unraid, while preserving safe behavior during genuine network outages.

The observed failure has two root causes:

1. A refresh attempt that receives HTTP 401/403 from one API endpoint and a network failure
   from another is classified as transient. Startup therefore refuses to enter OTP recovery.
2. Explicit stale credentials supplied by the Unraid container template can take precedence
   over newer rotated credentials in the encrypted credential store.

Runtime MQTT token expiration is related but crosses more architectural boundaries. Implement
it as a separate follow-up after the startup recovery fix is released.

## Phase 1: Reproduce the Failure

Add regression tests before changing production behavior.

Files:

- `tests/unit/test_cloud_auth.py`
- `tests/unit/test_startup.py`
- `tests/unit/test_main.py`

Test cases:

1. Primary API returns HTTP 401 while the secondary API has a DNS/network failure.
2. Primary API returns 401 while the secondary API returns 503.
3. All endpoints have network failures.
4. All endpoints return 401/403.
5. One endpoint fails but another successfully refreshes.
6. Stale environment credentials exist while the encrypted store contains newer credentials.
7. An invalid refresh token correctly enters OTP recovery.
8. Transient-only failures do not trigger OTP recovery.

All tests must mock network access. They must not contact Bambu Cloud or a real printer and
must use fake tokens, users, serials, emails, hosts, and payloads.

## Phase 2: Correct Refresh-Error Classification

Modify `src/bambulab_metrics_exporter/cloud_auth.py`, primarily
`refresh_access_token()`.

Current behavior:

```text
HTTP 401 + DNS failure -> CloudAuthTransientError
```

Required precedence after every configured endpoint has been attempted:

```text
Any endpoint succeeds               -> return refreshed credentials
At least one 401/403, none succeeds  -> CloudAuthInvalidError
Only network/408/429/5xx failures    -> CloudAuthTransientError
```

Implementation requirements:

- Preserve multi-base fallback: do not stop at the first failed endpoint when another could
  succeed.
- Treat a definitive authentication rejection as invalid credentials when no endpoint
  succeeds, even if another endpoint has a network failure.
- Keep 408, 409, 425, 429, 500, 502, 503, and 504 in the transient category.
- Preserve bounded retry and backoff for transient failures.
- Never include token values in exceptions or logs.
- Do not remove a regional endpoint without separate evidence and review.

Acceptance criteria:

- The reported primary-401-plus-EU-DNS-failure combination raises
  `CloudAuthInvalidError`.
- Startup enters the existing OTP recovery path for that result.
- Pure outages remain transient and do not generate unnecessary OTP emails.
- A successful fallback endpoint still wins over earlier invalid or transient responses.

## Phase 3: Recover from Stale Unraid Environment Credentials

The encrypted credential store and explicit environment currently have conflicting
precedence. `main._bootstrap_cloud_credentials()` skips the encrypted store whenever both
`BAMBULAB_CLOUD_USER_ID` and `BAMBULAB_CLOUD_ACCESS_TOKEN` are already present. On Unraid,
those values can be stale container-template variables that hide newer rotated credentials
saved on disk.

Implement a conservative fallback rather than globally reversing precedence:

1. Preserve explicit environment credentials as the first choice.
2. Probe those credentials normally.
3. If the probe fails, load encrypted credentials when the configured file and secret exist.
4. If the stored credentials differ, probe them before attempting token refresh or OTP.
5. Continue with refresh or OTP only if both credential sources fail.

Suggested refactor:

- Extract reusable encrypted-store loading from `main.py` into a focused helper.
- Prefer returning a validated credential mapping instead of immediately mutating global
  environment state.
- Apply the chosen credentials deliberately and construct fresh `Settings` afterward.
- Log only which source was selected: `environment` or `encrypted store`.
- Keep credential file decryption and permission behavior unchanged.

Likely affected files:

- `src/bambulab_metrics_exporter/main.py`
- `src/bambulab_metrics_exporter/startup.py`
- `src/bambulab_metrics_exporter/credentials_store.py`, only if a narrowly reusable helper
  belongs there
- `tests/unit/test_main.py`
- `tests/unit/test_startup.py`
- `tests/unit/test_credentials_store.py`, if its public behavior changes

Required tests:

- Valid environment credentials remain preferred.
- Invalid environment credentials plus valid encrypted credentials recover successfully.
- Identical stored credentials are not needlessly reprobed.
- Missing credential file falls through safely.
- Wrong secret, invalid ciphertext, invalid JSON, or incomplete stored credentials fail with
  actionable sanitized behavior.
- A newly rotated access and refresh token pair is persisted and loaded on the next startup.
- No token, OTP, email, secret, or encrypted blob appears in logs.

## Phase 4: Make the Unraid Template Safe by Default

Update:

- `unraid-bambulab-metrics-exporter.xml`
- `docs/wiki/Installation.md`
- `docs/wiki/Configuration.md`
- `docs/wiki/Troubleshooting.md`
- `README.md`

Required changes:

- Describe the encrypted credentials file as the recommended steady-state source.
- Mark Cloud User ID, Cloud Access Token, and Cloud Refresh Token as advanced manual
  overrides.
- Warn that populated manual-token fields can override rotated stored credentials.
- Tell Unraid users to leave those three fields empty after successful OTP enrollment.
- Keep Cloud One-Time Code empty during steady state and remove it after successful use.
- Keep `BAMBULAB_SECRET_KEY` stable and preserve the persistent appdata mapping.
- Document safe recovery by selecting a new credential filename rather than deleting the old
  file.
- Tell Unraid users to click **Apply** so the container is recreated; a simple restart does
  not change container environment variables.
- Correct troubleshooting text that currently says only to restart for expired cloud access.
- Remove the README claim that automatic refresh is a future enhancement because startup
  refresh already exists.

Do not remove the advanced manual-token fields outright; some operators may intentionally
manage credentials externally.

## Phase 5: Improve Diagnostics

Make startup logs describe the actual decision without exposing credentials.

Desired messages include:

```text
Cloud MQTT access token rejected
Attempting refresh using stored refresh token
Refresh token rejected by cloud API; OTP re-authentication required
```

For mixed endpoint failures, report the classification clearly:

```text
Refresh token was rejected by at least one API endpoint; other endpoint failures were network-related
```

Logging requirements:

- Do not include raw HTTP response bodies unless explicitly sanitized.
- Never log email, access token, refresh token, OTP, secret key, encrypted data, full serial,
  or a serial-bearing MQTT topic.
- Do not describe a definitive 401/403 as merely a connectivity problem.
- Preserve enough endpoint/status-category context for troubleshooting.

## Phase 6: Validate the Immediate Fix

Run focused checks during development:

```bash
.venv/bin/python -m pytest -q tests/unit/test_cloud_auth.py --no-cov
.venv/bin/python -m pytest -q tests/unit/test_startup.py --no-cov
.venv/bin/python -m pytest -q tests/unit/test_main.py --no-cov
```

Run repository-wide checks before handoff:

```bash
make lint
.venv/bin/python -m mypy src
.venv/bin/python -m compileall -q src tests
make test
docker build -t bambulab-metrics-exporter:auth-fix .
```

Review the Unraid template manually for:

- Persistent `/config/bambulab-metrics-exporter` mapping
- Masked secret, token, and OTP fields
- Stable secret-key instructions
- Clear manual-override warnings
- No real credentials, device identifiers, hosts, IPs, or personal data
- Correct credential filename behavior

## Phase 7: Runtime MQTT Refresh as a Separate Change

The immediate patch fixes startup recovery. It does not address an access token expiring
while the exporter remains running. Runtime recovery should be a separate change because it
crosses MQTT callbacks, client lifecycle, collection, authentication, and credential
persistence.

Design goals:

1. Detect MQTT `Not authorized` distinctly from an ordinary disconnect.
2. Stop repeated unauthorized reconnect attempts.
3. Trigger one synchronized refresh attempt.
4. Persist the rotated access and refresh tokens.
5. Rebuild or reauthenticate the cloud MQTT client with the new token.
6. Reconnect with bounded exponential backoff.
7. If the refresh token is invalid, expose a stable, actionable `reauthentication required`
   condition instead of looping or repeatedly sending OTP emails.
8. Prevent concurrent refresh attempts.
9. Preserve local MQTT behavior unchanged.
10. Keep the exporter operationally read-only; do not add printer-control publishes.

Likely affected files:

- `src/bambulab_metrics_exporter/client/base.py`
- `src/bambulab_metrics_exporter/client/local_mqtt.py`
- `src/bambulab_metrics_exporter/client/cloud_mqtt.py`
- `src/bambulab_metrics_exporter/collector.py`
- `src/bambulab_metrics_exporter/startup.py` or a new focused credential-refresh service
- Relevant client, collector, startup, and end-to-end tests

Runtime acceptance criteria:

- Simulated MQTT authorization rejection triggers at most one refresh at a time.
- Successful refresh reconnects with the new token without restarting the process.
- Transient refresh failure uses bounded backoff and does not cause a tight loop.
- Invalid refresh stops unauthorized reconnect churn and reports manual OTP action clearly.
- Local MQTT behavior and existing `pushall` telemetry requests remain unchanged.
- Tests remain offline and deterministic.

## Delivery Order

1. Add regression tests for the observed failure.
2. Fix refresh classification.
3. Add encrypted-store fallback after invalid environment credentials.
4. Improve diagnostics.
5. Update Unraid and operator documentation.
6. Run full validation and release the startup-recovery fix.
7. Implement runtime MQTT refresh as a separate follow-up change.

## Definition of Done

The immediate fix is complete when:

- The exact 401-plus-DNS failure no longer becomes a permanent transient-error loop.
- Invalid refresh credentials enter the existing OTP recovery flow.
- Pure network failures remain transient.
- Newer encrypted credentials can recover from stale explicit Unraid credentials.
- Steady-state Unraid documentation instructs users not to pin rotated tokens.
- Authentication logs contain no credentials or personal device information.
- Focused tests, full tests, Ruff, strict mypy, and compile validation pass.
- The affected container builds successfully.
- The complete diff is reviewed for credential leaks, unrelated changes, and backward
  compatibility.

The runtime-refresh follow-up is complete only when authorization loss can recover without a
process restart and cannot create an aggressive reconnect or OTP-email loop.
