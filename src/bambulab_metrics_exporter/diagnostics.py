"""Diagnostic report and payload sanitizer.

The report is a JSON file users download from the status or /auth page and attach to a
GitHub issue: it carries what is needed to add a printer, a feature or a metric, or to fix
a wrong value, without access codes, tokens, serial numbers, addresses or names.

The same sanitizer turns captured payloads into test fixtures
(`tests/fixtures/printers/sanitize_fixture.py`).
"""

from __future__ import annotations

import ipaddress
import itertools
import logging
import math
import os
import platform
import re
import statistics
import sys
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bambulab_metrics_exporter import __version__, ssdp
from bambulab_metrics_exporter.config import is_auto_host

if TYPE_CHECKING:
    from bambulab_metrics_exporter.certificates import CertificateFacts
    from bambulab_metrics_exporter.config import Settings
    from bambulab_metrics_exporter.metrics import ExporterMetrics
    from bambulab_metrics_exporter.models import PrinterSnapshot

REPORT_FORMAT = 1
_ENV_SCRUB_KEYS = (
    "BAMBULAB_HOST", "BAMBULAB_SERIAL", "BAMBULAB_ACCESS_CODE", "BAMBULAB_CLOUD_USER_ID",
    "BAMBULAB_CLOUD_ACCESS_TOKEN", "BAMBULAB_CLOUD_REFRESH_TOKEN", "BAMBULAB_CLOUD_EMAIL",
    "BAMBULAB_CLOUD_CODE", "BAMBULAB_SECRET_KEY", "PRINTER_NAME_LABEL", "BAMBULAB_PRINTER_NAME",
)

# Values replaced outright (key -> fake value).
_FIXED: dict[str, str | int] = {
    "tag_uid": "0000000000000000",
    "tray_uuid": "00000000000000000000000000000000",
    "mac": "000000000000",
    "ssid": "fixture-wifi",
    "dev_name": "Fixture Printer",
    "subtask_name": "fixture",
    "gcode_file": "fixture.gcode.3mf",
    "file": "fixture.3mf",
    "url": "",
    "model_id": "FIXTUREMODELID00",
    "task_id": "0",
    "subtask_id": "0",
    "job_id": "0",
    "project_id": "0",
    "profile_id": "0",
    "design_id": "0",
    "uid": "0",
    "user_id": "0",
    "mc_print_line": "",
    "chip_id": "00000000000000000000000000000000",
    "idx2": 0,
    "t_utc": 0,
    "lan_task_id": "0",
    "img_id": "0",
}
_SERIAL_KEYS = {"sn", "dev_id"}
# Keys that can hold a user-chosen name, a file name or a storage link; replaced outright.
# Not `project_name`: in the module list it is a hardware code that model detection uses.
_NAME_KEY_RE = re.compile(
    r"^(ssid\w*|hostname|host_name|task_name|plate_name|tar_name|file_?name|\w*_path|"
    r"oss_url|\w*_file_url)$",
    re.I,
)
# Keys that could hold a credential. Reports are not known to carry any; a match is
# blanked anyway.
_SECRET_KEY_RE = re.compile(r"token|password|passwd|secret|access_code|auth_key", re.I)
# 192.0.2.1 (RFC 5737 documentation range) as the printer's little-endian uint32.
_FIXTURE_IP_INT = 192 + (0 << 8) + (2 << 16) + (1 << 24)
# Valid IPv4 octets without leading zeros: Bambu firmware versions ("01.12.00.00")
# always carry leading zeros, so they are never mistaken for addresses.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
# Digit boundaries only, so an address at the end of a sentence ("to 10.0.0.5.") or glued
# to a word ("printer_10.0.0.5") is still found, but not inside a longer dotted number.
_IPV4_RE = re.compile(rf"(?<!\d)(?<!\d\.){_OCTET}(?:\.{_OCTET}){{3}}(?!\.?\d)")
_IPV4_KEEP = {"0.0.0.0", "127.0.0.1", "255.255.255.255"}
_IPV6_CANDIDATE_RE = re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f:]{6,39}(?![0-9A-Fa-f:])")
_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:-])")
# Pydantic validation errors repeat the rejected value ("input_value='...'").
_INPUT_VALUE_RE = re.compile(r"input_value=('[^']*'|\"[^\"]*\"|\S+)")
# Longer strings are cut before scrubbing: keeps the regexes fast on any input.
_MAX_TEXT = 2000
_EMAIL_RE = re.compile(r"[^@\s\"']+@[^@\s\"']+\.[a-z]{2,}", re.I)
_REDACTED = "[redacted]"
# Extra values shorter than this are not scrubbed from text: too likely to hit
# unrelated words or numbers.
_MIN_SCRUB_LENGTH = 4


def _fake_serial(value: str) -> str:
    """Keep the 3-character model prefix (model detection needs it), replace the rest."""
    if not value or value in {"REDACTED", "N/A"}:
        return value
    prefix = value[:3].upper()
    return (prefix + "FIXTURE00000001")[: max(len(value), 15)]


def _replace_ipv4(match: re.Match[str]) -> str:
    text = match.group(0)
    return text if text in _IPV4_KEEP else "192.0.2.1"


def _replace_ipv6(match: re.Match[str]) -> str:
    text = match.group(0)
    groups = [g for g in text.split(":") if g]
    if len(groups) < 2 or ("::" not in text and text.count(":") < 7):
        return text  # times like 12:30:45, "::" and other short colon runs
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return text
    return "2001:db8::1"


def scrub_text(text: str, serials: Iterable[str] = (), extra: Iterable[str] = ()) -> str:
    """Remove addresses, emails, serials and the given extra values from free text."""
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT] + f" [{len(text) - _MAX_TEXT} characters cut]"
    text = _INPUT_VALUE_RE.sub("input_value=[redacted]", text)
    text = _IPV4_RE.sub(_replace_ipv4, text)
    text = _IPV6_CANDIDATE_RE.sub(_replace_ipv6, text)
    text = _MAC_RE.sub("00:00:00:00:00:00", text)
    text = _EMAIL_RE.sub("operator@example.invalid", text)
    for serial in serials:
        if len(serial) >= 8:
            text = re.sub(re.escape(serial), _fake_serial(serial), text, flags=re.I)
    for value in sorted({v for v in extra if _scrubbable(v)}, key=len, reverse=True):
        # Whole words only, so a name never eats part of a longer token.
        text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", _REDACTED, text, flags=re.I)
    return text


def _scrubbable(value: str) -> bool:
    """Extra values (printer names, hosts, credentials) worth scrubbing: long enough, and
    not protocol vocabulary such as a model name or a printer state, which a user may have
    picked as a printer name and which the report needs."""
    folded = value.strip().casefold()
    return len(folded) >= _MIN_SCRUB_LENGTH and folded not in _vocabulary()


_VOCABULARY: set[str] = set()


def _vocabulary() -> set[str]:
    """Model names, product names and gcode states (lazy: models imports a lot)."""
    if not _VOCABULARY:
        from bambulab_metrics_exporter.models import (
            _SN_PREFIX_TO_PRINTER,
            PRODUCT_NAME_TO_PRINTER,
        )

        _VOCABULARY.update(PRODUCT_NAME_TO_PRINTER)
        # Display names without the brand ("a1 mini", "x1 carbon", "h2d pro").
        _VOCABULARY.update(
            name.removeprefix("bambu lab ") for name in PRODUCT_NAME_TO_PRINTER
        )
        _VOCABULARY.update(v.casefold() for v in _SN_PREFIX_TO_PRINTER.values())
        _VOCABULARY.update(("bambu lab", "bambu", "bambulab", "carbon"))
        _VOCABULARY.update(
            s.casefold() for s in ("IDLE", "RUNNING", "PAUSE", "FINISH", "FAILED", "PREPARE",
                                   "SLICING", "UNKNOWN", "AMS", "AMS Lite", "AMS HT",
                                   "AMS 2 Pro", "AMS 3H", "Filament Buffer", "Exhaust Fan")
        )
    return _VOCABULARY


def _is_serial_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SERIAL_KEYS or lowered.endswith("_sn") or "serial" in lowered


def _fake_serials(value: Any, serials: set[str]) -> Any:
    """A serial value, or a list of them."""
    if isinstance(value, str):
        serials.add(value)
        return _fake_serial(value)
    if isinstance(value, list):
        return [_fake_serials(v, serials) for v in value]
    return value


def _sanitize(obj: Any, serials: set[str]) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if isinstance(key, str) and _SECRET_KEY_RE.search(key):
                out[key] = _REDACTED
            elif isinstance(key, str) and _is_serial_key(key) and isinstance(value, (str, list)):
                out[key] = _fake_serials(value, serials)
            elif key == "rtsp_url" and isinstance(value, str) and value.startswith("rtsp"):
                out[key] = "rtsps://192.0.2.1/streaming/live/1"
            elif isinstance(key, str) and _NAME_KEY_RE.match(key) and isinstance(value, str):
                out[key] = _REDACTED if value else value
            elif isinstance(key, str) and _NAME_KEY_RE.match(key) and isinstance(value, list):
                out[key] = [_REDACTED for _ in value]
            elif key in _FIXED and isinstance(value, (str, int)) and value not in ("", 0):
                out[key] = _FIXED[key]
            elif key == "ams_id" and isinstance(value, str) and not value.strip().isdigit():
                # A unit serial (some firmware), not the small numeric unit index.
                serials.add(value)
                out[key] = _fake_serial(value)
            elif key == "ip" and isinstance(value, int) and value != 0:
                out[key] = _FIXTURE_IP_INT
            else:
                out[key] = _sanitize(value, serials)
        return out
    if isinstance(obj, list):
        return [_sanitize(item, serials) for item in obj]
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None  # NaN and infinity are not valid JSON for most readers
    return obj


def _scrub_mentions(obj: Any, serials: set[str], extra: Iterable[str]) -> Any:
    """Replace serials and extra values that appear inside other strings and keys."""
    if isinstance(obj, dict):
        return {
            scrub_text(str(k), serials, extra): _scrub_mentions(v, serials, extra)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub_mentions(v, serials, extra) for v in obj]
    if isinstance(obj, str):
        return scrub_text(obj, serials, extra)
    return obj


def sanitize_payload(
    payload: Any, serials: Iterable[str] = (), extra: Iterable[str] = ()
) -> Any:
    """Sanitized deep copy of a raw MQTT state. `serials` and `extra` (printer names,
    hosts) are also removed wherever they appear inside text."""
    found = {s for s in serials if s}
    cleaned = _sanitize(payload, found)
    return _scrub_mentions(cleaned, found, list(extra))


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Fixture form: `{"pushall": ..., "get_version": ...}` (a bare report is wrapped)."""
    if "pushall" not in payload:
        payload = {"pushall": payload, "get_version": {}}
    result: dict[str, Any] = sanitize_payload(payload)
    return result


# -- recent log lines -------------------------------------------------------------------


_MAX_LOG_MESSAGE = 1000


class RecentLogHandler(logging.Handler):
    """Keeps the last exporter log lines in memory for the diagnostic report."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__(level=logging.INFO)
        self._records: deque[str] = deque(maxlen=capacity)
        self._records_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stamp = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            message = record.getMessage()[:_MAX_LOG_MESSAGE]
            line = f"{stamp} {record.levelname} {record.name} {message}"
            if record.exc_info and record.exc_info[0] is not None:
                line += f" [{record.exc_info[0].__name__}]"
        except Exception:  # noqa: BLE001 - logging must never raise
            return
        with self._records_lock:
            self._records.append(line)

    def lines(self) -> list[str]:
        with self._records_lock:
            return list(self._records)


_LOG_HANDLER = RecentLogHandler()


def install_log_handler() -> None:
    """Attach the in-memory handler to the package logger once."""
    package_logger = logging.getLogger("bambulab_metrics_exporter")
    if _LOG_HANDLER not in package_logger.handlers:
        package_logger.addHandler(_LOG_HANDLER)


def recent_log_lines() -> list[str]:
    return _LOG_HANDLER.lines()


# -- LAN announcements (SSDP) ------------------------------------------------------------

# Header values kept (still scrubbed). Any other header keeps only its name: the format is
# not documented, so an unknown field could carry an identifier.
_SSDP_KEEP = frozenset({
    "server", "nt", "cache-control", "devmodel.bbl", "devconnect.bbl", "devbind.bbl",
    "devseclink.bbl", "devsignal.bbl", "devversion.bbl", "devcap.bbl",
})
_SSDP_START_RE = re.compile(
    r"^(?:NOTIFY \* HTTP/1\.[01]|M-SEARCH \* HTTP/1\.[01]|HTTP/1\.[01] 200 OK)$", re.I
)
# Serial-like tokens: 8 or more uppercase letters and digits, at least one digit. Bambu
# serials are uppercase; lowercase words such as `3dprinter` in NT and USN urns are kept.
_SERIAL_TOKEN_RE = re.compile(r"(?=[A-Z0-9]*\d)[A-Z0-9]{8,}")
_MAX_SSDP_DEVICES = 32


def _group_address(value: str) -> bool:
    """HOST names where the packet was sent. A multicast or broadcast address says how the
    printer announces; a unicast one is a LAN address, so it is not kept."""
    host = value.rsplit(":", 1)[0] if value.count(":") == 1 else value
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_multicast or str(address) == "255.255.255.255"


def _fake_serial_tokens(value: str) -> str:
    return _SERIAL_TOKEN_RE.sub(lambda m: _fake_serial(m.group(0)), value)


def _ssdp_value(name: str, value: str, serials: list[str], scrub: list[str]) -> str:
    key = name.lower()
    if key == "usn":
        return _fake_serial_tokens(scrub_text(value, serials, scrub))
    if key == "location":
        return "192.0.2.1" if value else ""
    if key == "host":
        return value if _group_address(value) else _REDACTED
    if key in _SSDP_KEEP:
        return _fake_serial_tokens(scrub_text(value, serials, scrub))
    return _REDACTED


def _printer_index(usn: str, printers: list[PrinterDiagnostics]) -> int | None:
    for index, item in enumerate(printers, start=1):
        serial = str(item.settings.bambulab_serial or "").upper()
        if serial and serial in usn:
            return index
    return None


def _median_gap(packets: list[ssdp.Packet]) -> float | None:
    times = sorted(packet.received_at for packet in packets)
    gaps = [later - earlier for earlier, later in itertools.pairwise(times)]
    return round(statistics.median(gaps), 1) if gaps else None


def _source_matches_location(packet: ssdp.Packet) -> bool | None:
    """Whether the sender is the address the packet advertises. False points at a relay or
    NAT between printer and exporter, or a packet sent on another device's behalf."""
    found = _IPV4_RE.search(packet.header("Location"))
    if found is None or not packet.source:
        return None
    return found.group(0) == packet.source


def _ssdp_report(
    capture: ssdp.Capture | None,
    printers: list[PrinterDiagnostics],
    serials: list[str],
    scrub: list[str],
) -> dict[str, Any] | None:
    if capture is None:
        return None
    by_device: dict[str, list[ssdp.Packet]] = {}
    for packet in capture.packets:
        by_device.setdefault(packet.header("USN").upper(), []).append(packet)
    devices: list[dict[str, Any]] = []
    for usn, packets in list(by_device.items())[:_MAX_SSDP_DEVICES]:
        latest = packets[-1]
        start = latest.start_line
        devices.append({
            "printer_index": _printer_index(usn, printers),
            "packets": len(packets),
            "interval_seconds": _median_gap(packets),
            "source_matches_location": _source_matches_location(latest),
            "start_line": start if _SSDP_START_RE.match(start) else _REDACTED,
            "headers": {
                _fake_serial_tokens(scrub_text(name, serials, scrub)): _ssdp_value(
                    name, value, serials, scrub
                )
                for name, value in latest.headers
            },
        })
    return {
        "status": capture.status,
        "port": ssdp.PORT,
        "listen_seconds": capture.listen_seconds,
        "waited_seconds": capture.waited_seconds,
        "bambu_packets": len(capture.packets),
        "other_packets": capture.ignored,
        "error": capture.error or None,
        "devices": devices,
    }


# -- report ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrinterDiagnostics:
    """What one runtime hands to the report. Raw values; the report sanitizes them."""

    settings: Settings
    state: str
    message: str
    ready: bool
    snapshot: PrinterSnapshot | None
    metrics: ExporterMetrics
    # The latest certificate check of an `auto` printer (None: not checked).
    certificate: CertificateFacts | None = None


def detect_model(
    settings: Settings, snapshot: PrinterSnapshot | None
) -> tuple[str | None, str]:
    """(model, source). With printer data the full detection runs; without it (never
    connected, unreachable, login needed) the serial prefix or the configured model hint
    still tells the model. None means the exporter does not recognize the printer."""
    if snapshot is not None and snapshot.raw:
        return snapshot.printer_type, "printer_data"
    serial = str(settings.bambulab_serial or "")
    hint = str(settings.bambulab_printer_model or "")
    if not serial and not hint:
        return None, "none"
    from bambulab_metrics_exporter.models import PrinterSnapshot as _Snapshot

    offline = _Snapshot(
        connected=False, raw={}, configured_serial=serial or None, configured_model=hint or None
    )
    return offline.printer_type, "serial_or_setting"


def _certificate_report(
    facts: CertificateFacts | None, serial: str, serials: list[str], scrub: list[str]
) -> dict[str, Any] | None:
    """The latest certificate check of an `auto` printer. Common name and issuer go through
    the serial sanitizer. Only the first 8 hex digits of a fingerprint stay: the full value
    identifies the device as well as its serial does."""
    if facts is None:
        return None
    return {
        "result": facts.result,
        "subject_cn": _fake_serial_tokens(scrub_text(facts.subject_cn, serials, scrub)),
        "cn_matches_serial": bool(serial)
        and facts.subject_cn.strip().upper() == serial.strip().upper(),
        "issuer": _fake_serial_tokens(scrub_text(facts.issuer, serials, scrub)),
        "not_before": facts.not_before or None,
        "not_after": facts.not_after or None,
        "fingerprint_prefix": facts.fingerprint[:8] or None,
        "pinned_prefix": facts.pinned[:8] or None,
    }


def _empty_metric_families(metrics: ExporterMetrics) -> list[str]:
    """Metric families with no series or only NaN values: telemetry the printer does not
    report (or the exporter cannot read yet)."""
    empty: list[str] = []
    for family in metrics.registry.collect():
        values = [s.value for s in family.samples]
        if not values or all(isinstance(v, float) and math.isnan(v) for v in values):
            empty.append(family.name)
    return sorted(empty)


def _in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _printer_report(
    index: int, item: PrinterDiagnostics, now: float, serials: list[str], scrub: list[str]
) -> dict[str, Any]:
    settings = item.settings
    serial = str(settings.bambulab_serial or "")
    snapshot = item.snapshot
    last = item.metrics.last_success_timestamp()
    report: dict[str, Any] = {
        "index": index,
        "serial": _fake_serial(serial),
        "transport": str(settings.bambulab_transport),
        "state": item.state,
        "message": scrub_text(item.message, serials, scrub),
        "ready": item.ready,
        "last_success_age_seconds": round(now - last, 1) if last else None,
        "settings": {
            "polling_interval_seconds": settings.polling_interval_seconds,
            "request_timeout_seconds": settings.request_timeout_seconds,
            "request_pushall": settings.bambulab_request_pushall,
            "host_auto": is_auto_host(str(settings.bambulab_host or "")),
            "configured_model": settings.bambulab_printer_model or None,
        },
        "certificate": _certificate_report(item.certificate, serial, serials, scrub),
    }
    model, source = detect_model(settings, snapshot)
    report["model"] = model
    report["model_source"] = source
    if snapshot is None or not snapshot.raw:
        # Nothing arrived from the printer yet: every metric is empty, so the list says
        # nothing. None tells the reader there is no data, not that all metrics are missing.
        report["empty_metrics"] = None
        report["payload"] = None
        return report
    report["empty_metrics"] = _empty_metric_families(item.metrics)
    report["connected"] = snapshot.connected
    report["capabilities"] = asdict(snapshot.capabilities)
    report["modules"] = sanitize_payload(snapshot.modules, serials, scrub)
    report["payload"] = sanitize_payload(snapshot.raw, serials, scrub)
    return report


def build_report(
    printers: list[PrinterDiagnostics],
    now: float | None = None,
    announcements: ssdp.Capture | None = None,
) -> dict[str, Any]:
    """The full report. Every free-text value is scrubbed of the configured serials,
    hosts and printer names, on top of the payload sanitizer. Credentials are scrubbed
    too, although nothing in the report should ever contain them. `announcements` is the raw
    LAN capture (`ssdp.capture`); it is sanitized here."""
    now = time.time() if now is None else now
    scrub: list[str] = []
    serials: list[str] = []
    for item in printers:
        s = item.settings
        scrub += [
            s.bambulab_host, s.printer_name_label, s.bambulab_printer_name,
            s.bambulab_access_code, s.bambulab_cloud_access_token,
            s.bambulab_cloud_refresh_token, s.bambulab_cloud_user_id,
            s.bambulab_secret_key,
        ]
        if s.bambulab_serial:
            serials.append(str(s.bambulab_serial))
    # The environment as well: with invalid settings the runtime only holds defaults.
    scrub += [os.environ.get(key, "") for key in _ENV_SCRUB_KEYS]
    # `auto` is a mode word, not an address: scrubbing it would blank every "auto" in the text.
    scrub = [str(v) for v in scrub if v and not is_auto_host(str(v))]
    return {
        "report": "bambulab-metrics-exporter diagnostic report",
        "format": REPORT_FORMAT,
        "generated_at": datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exporter": {
            "version": __version__,
            "python": platform.python_version(),
            "platform": sys.platform,
            "machine": platform.machine(),
            "in_docker": _in_docker(),
        },
        "printers": [
            _printer_report(i + 1, item, now, serials, scrub)
            for i, item in enumerate(printers)
        ],
        "ssdp": _ssdp_report(announcements, printers, serials, scrub),
        "logs": [scrub_text(line, serials, scrub) for line in recent_log_lines()],
    }
