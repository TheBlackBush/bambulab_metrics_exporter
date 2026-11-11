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
from pathlib import Path

# One sanitizer for fixtures and the diagnostic report (needs the package installed).
from bambulab_metrics_exporter.diagnostics import sanitize


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
