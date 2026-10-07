"""Sanitize a captured Bambu Lab MQTT payload into a test fixture.

Usage:
    python -I tests/fixtures/printers/sanitize_fixture.py <input.json> <output.json> \\
        --model X1C --source "description of where the capture came from"

The input is either ``{"pushall": {...}, "get_version": {...}}`` or a bare report
``{"print": {...}}``. Identifiers are replaced with fixed fake values; the first three
characters of serial numbers are kept because model detection depends on them.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# Values replaced outright (key -> fake value or None to blank the value).
_FIXED = {
    "tag_uid": "0000000000000000",
    "tray_uuid": "00000000000000000000000000000000",
    "mac": "000000000000",
    "ssid": "fixture-wifi",
    "dev_name": "Fixture Printer",
    "subtask_name": "fixture",
    "gcode_file": "fixture.gcode.3mf",
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
}
_SERIAL_KEYS = {"sn", "dev_id", "serial"}
# 192.0.2.1 (RFC 5737 documentation range) as the printer's little-endian uint32.
_FIXTURE_IP_INT = 192 + (0 << 8) + (2 << 16) + (1 << 24)
# Valid IPv4 octets without leading zeros: Bambu firmware versions ("01.12.00.00")
# always carry leading zeros, so they are never mistaken for addresses.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4_RE = re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w.])")
_EMAIL_RE = re.compile(r"[^@\s\"']+@[^@\s\"']+\.[a-z]{2,}", re.I)


def _fake_serial(value: str) -> str:
    if not value or value in {"REDACTED", "N/A"}:
        return value
    prefix = value[:3].upper()
    return (prefix + "FIXTURE00000001")[: max(len(value), 15)]


def _sanitize(obj: Any, serials: set[str]) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            if key in _SERIAL_KEYS and isinstance(value, str):
                serials.add(value)
                out[key] = _fake_serial(value)
            elif key in _FIXED and isinstance(value, (str, int)) and value not in ("", 0):
                out[key] = _FIXED[key]
            elif key == "ip" and isinstance(value, int) and value != 0:
                out[key] = _FIXTURE_IP_INT
            elif key == "rtsp_url" and isinstance(value, str) and value.startswith("rtsp"):
                out[key] = "rtsps://192.0.2.1/streaming/live/1"
            else:
                out[key] = _sanitize(value, serials)
        return out
    if isinstance(obj, list):
        return [_sanitize(item, serials) for item in obj]
    if isinstance(obj, str):
        text = _IPV4_RE.sub("192.0.2.1", obj)
        return _EMAIL_RE.sub("operator@example.invalid", text)
    return obj


def _scrub_serial_mentions(obj: Any, serials: set[str]) -> Any:
    """Replace serials that appear inside other strings (topics, file names)."""
    if isinstance(obj, dict):
        return {k: _scrub_serial_mentions(v, serials) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_serial_mentions(v, serials) for v in obj]
    if isinstance(obj, str):
        for serial in serials:
            if len(serial) >= 8 and serial in obj:
                obj = obj.replace(serial, _fake_serial(serial))
        return obj
    return obj


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    if "pushall" not in payload:
        payload = {"pushall": payload, "get_version": {}}
    serials: set[str] = set()
    cleaned = _sanitize(payload, serials)
    return _scrub_serial_mentions(cleaned, serials)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    data = sanitize(json.loads(args.input.read_text(encoding="utf-8")))
    fixture = {"model": args.model, "source": args.source, **data}
    args.output.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
