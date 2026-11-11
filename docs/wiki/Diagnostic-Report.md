# Diagnostic Report

The diagnostic report is a small JSON file the exporter builds from what your printer sends. Attach
it to a GitHub issue when:

- your printer model is new or not tested yet,
- a feature or metric you want is missing,
- a metric shows a wrong value, or none,
- the exporter does not connect, or behaves oddly.

With the report, support for your printer or a metric can be added or fixed without access to
your printer.

---

## 1. Download the report

Open the **Diagnostics** page at `http://exporter-host:9109/diagnostics`. The status page and the
Printer Connection page (`/auth`) both have a **Diagnostics** button that leads there.

Click **Run diagnostics**. The page shows a summary per printer (model, state, connection,
firmware, metrics without a value) and the full report. Then:

| Button | What it does |
|---|---|
| **Copy** | Copies the report as a code block, ready to paste into an issue |
| **Download** | Saves it as `bambulab-exporter-diagnostics-<date>-<time>.json` |
| **Create GitHub issue** | Opens the GitHub issue form with a title that tells reports apart (for example `[H2D] Connection error: firmware 01.04.20.00, LAN, exporter 0.4.0` or `[Unsupported printer ZZZ] Model not recognized: Cloud, exporter 0.4.0`), a summary table (model, state, error message, firmware, connection) and the exporter version, model, firmware and connection mode filled in. A small report (for example from a printer that is not connected) is filled into the **Diagnostic report** box too. A full report is too long for a link, so it is copied and downloaded instead: paste it into the box (Ctrl+V) or drag the file there |

One report covers every printer the exporter monitors. Copy works on plain `http://` addresses
too. If the report is too large to paste (several printers, over GitHub's comment size) or the
browser blocks the clipboard, Copy says so: use Download. GitHub does not let a page attach a
file to a new issue, so the file always needs your one drag (or paste) into the issue. If the browser blocks the new tab, allow pop-ups
for the exporter page, or use the link the page shows.

Without a browser, for example on a headless server:

```bash
curl -o diagnostics.json "http://localhost:9109/diagnostics/report?download=1"
```

> **Get it while the problem shows.** The report holds the printer's latest data. For a value
> that only exists during a print, while drying, with an accessory fitted or a tool head mounted,
> run it at that moment. If the exporter just started, wait for the first update (the status
> page shows "Last update").

If the page answers `host_not_allowed`, open it by IP address, or add the host name you use to
`AUTH_ALLOWED_HOSTS` (see [Configuration](Configuration)).

## 2. Check it

Read it on the Diagnostics page, in the downloaded file, or in the issue preview. It is plain
JSON. The exporter removes or replaces:

| Removed or replaced | How |
|---|---|
| Access code, cloud tokens, user id, email, secret key | Never added; if one shows up anyway, it is replaced with `[redacted]` |
| Printer serial numbers (printer, AMS, modules, nozzles) | Replaced; only the first 3 characters stay, because they tell the printer model |
| IP addresses (IPv4 and IPv6), MAC addresses | Replaced with documentation values (`192.0.2.1`, `2001:db8::1`); `0.0.0.0` and `127.0.0.1` stay. A version written like an address (`1.2.3.4`) is replaced too; printer firmware versions (`01.08.00.00`) are not |
| Wi-Fi network names (`ssid` fields), host names | Replaced with `[redacted]` |
| Printer names and the printer host you configured | Replaced with `[redacted]` or `Fixture Printer` wherever they appear. A name that is also a model or state word (for example "P1S" or "IDLE") is left alone, because it says nothing about you |
| Job and file names, file paths and storage links, task and plate names, job/task/project/profile/image ids, camera URL | Replaced with fixed placeholders |
| Rejected settings values in error messages | Replaced with `[redacted]` |
| Spool tag ids (RFID), chip ids | Replaced with zeros |
| Email addresses anywhere in text | Replaced with `operator@example.invalid` |

Everything else stays, because it is what makes the report useful: temperatures, fan speeds, AMS
and spool details (type, color, remaining), HMS error codes, firmware versions, module list, and
the raw printer state.

If you still see something you do not want to share, replace that value by hand with `"x"` before
attaching. Do not delete whole sections: missing fields can look like a printer that does not
report them.

## 3. Send it with an issue

**Create GitHub issue** on the Diagnostics page does this for you. To do it by hand, open a new
issue with the **Printer support, metric request or bug** form:
[new issue](https://github.com/TheBlackBush/bambulab_metrics_exporter/issues/new?template=diagnostic.yml).
Fill in the fields, then paste the copied report into the **Diagnostic report** box or drag the
file there. If GitHub refuses the `.json` file, zip it and attach the zip.

Describe what you expected: for a wrong value, what the printer screen shows; for a new metric,
where you see the value (printer screen, Bambu Studio or Bambu Handy).

---

## Not connected? Run it anyway

The report also works when the exporter cannot reach the printer: a wrong IP or access code, the
printer off, an expired cloud login, or nothing set up yet. The summary then shows the state
(`Connection error`, `Login required`, `Setup required`) with the reason, the model taken from
the serial number, and "no data yet" for the metrics. The `logs` section shows the connection
attempts. That is usually enough to find a connection problem, so send it the same way.

## What is in the report

| Section | Content |
|---|---|
| `exporter` | Exporter version, Python version, platform, and whether it runs in Docker |
| `printers[]` | One entry per printer (see below) |
| `logs` | The last 200 exporter log lines at the configured `LOG_LEVEL` (info and above by default; long lines cut at 1000 characters), with the same values removed |

Each printer entry:

| Field | Content |
|---|---|
| `serial` | Placeholder serial with the real model prefix |
| `transport` | `local_mqtt` or `cloud_mqtt` |
| `state`, `message` | Connection state, as on the status page |
| `ready`, `connected`, `last_success_age_seconds` | Whether data arrived, and how long ago the last update was |
| `settings` | Polling interval, request timeout, `BAMBULAB_REQUEST_PUSHALL` and the configured model hint (no credentials) |
| `model`, `model_source` | The detected model (`null` when not recognized), and where it came from: `printer_data`, or `serial_or_setting` (serial prefix or configured model, when no data has arrived) |
| `capabilities` | The hardware features the exporter assumes for the model (only with printer data) |
| `empty_metrics` | Metrics with no value for this printer: not reported by the printer, or not readable yet. `null` when no data has arrived at all |
| `modules` | Firmware modules (`get_version`): names, product names, hardware and software versions |
| `payload` | The printer's latest state as the exporter holds it, sanitized |

The report is read-only: building it sends nothing to the printer or to Bambu Cloud.

## For fixtures

Maintainers can save a report's `payload` object as `capture.json` and turn it into a test
fixture with the same sanitizer:

```bash
python -I tests/fixtures/printers/sanitize_fixture.py capture.json tests/fixtures/printers/<model>.json \
    --model <MODEL> --source "diagnostic report from issue #<number>"
```
