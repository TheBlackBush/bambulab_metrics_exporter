# Printer payload fixtures

One sanitized MQTT capture per printer model, used by `tests/unit/test_printer_fixtures.py` to
check model detection and per-model metric behavior. Each file holds:

- `model`: the expected detected model.
- `source`: where the capture came from.
- `pushall`: the full `{"print": {...}}` report.
- `get_version`: the `{"info": {"module": [...]}}` reply (may be empty).

| File | Model | Notes |
|------|-------|-------|
| `a1.json` | A1 | AMS Lite, legacy flat block |
| `a2l.json` | A2L | AMS Lite on unit id 16, `info` type 5 |
| `h2c.json` | H2C | dual extruder, hotend rack |
| `h2d.json` | H2D | dual extruder, laser module mounted |
| `h2d_external_spool.json` | H2D | external spool active on extruder 0, AMS HT units |
| `h2d_pro.json` | H2D Pro | AMS HT, wired network |
| `h2s.json` | H2S | chamber heater active (packed chamber temperature) |
| `p1p_no_ams.json` | P1P | no AMS, external spool |
| `p2s.json` | P2S | airduct fans, filament buffer |
| `x1_legacy_firmware.json` | X1 | older X1 firmware, no product name |
| `x1c_multi_ams.json` | X1C | AMS, AMS 2 Pro drying, AMS HT |
| `x1c_fw0112_ams1.json` | X1C | firmware 01.12.00.00, new `device.*` blocks, AMS (1) |
| `x2d.json` | X2D | dual extruder, airduct part 160, exhaust fan, timelapse storage |

Fixtures describe payload shapes. Only the X1C is validated on real hardware.

## Adding a fixture

Never commit a raw capture. Run it through the sanitizer first:

```bash
.venv/bin/python -I tests/fixtures/printers/sanitize_fixture.py capture.json \
  tests/fixtures/printers/<model>.json --model <MODEL> --source "<where it came from>"
```

The sanitizer keeps the first three characters of serial numbers (model detection needs them),
replaces every other identifier (serials, tag and tray ids, task, job and project ids, MAC,
SSID, file names, emails) with fixed fake values, and maps IP addresses to `192.0.2.1`.
Review the output before committing.

## Attribution

All fixtures except `x1c_fw0112_ams1.json` are sanitized versions of the mock payloads in
[ha-bambulab](https://github.com/greghesp/ha-bambulab)
(`custom_components/bambu_lab/pybambu/mock_data`, commit `0e027ff`), used under the MIT License:

```text
MIT License

Copyright (c) 2023 ha-bambulab contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

`x1c_fw0112_ams1.json` was captured read-only from the maintainer's X1C and sanitized.
