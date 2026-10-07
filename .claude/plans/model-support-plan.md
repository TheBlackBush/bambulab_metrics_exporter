# Printer Model Support Plan

## Status (2026-10-07)

Phases 1, 2 (door group only), 3 and 5 implemented on branch `feat/model-detection`
(uncommitted). Phase 4 (`get_version` request on connect) implemented after explicit
maintainer instruction. Unknown models keep omitting `bambulab_printer_model_info`. Sources: BambuStudio `da8b44ee` (AGPL-3.0),
ha-bambulab `0e027ff1` (MIT), OpenBambuAPI `cc383a2c` (FDL-1.3). Reimplement facts and
identifiers only; do not copy code. The Bambu Handy APK could not be obtained (all mirrors
behind Cloudflare challenges) and is not needed: BambuStudio carries the same identifiers.

## Findings that drive the plan

1. **Most modern printers on LAN are currently labelled `X1C`.** A regular `pushall` carries
   no `print.sn` and no `module` list (product names only arrive in a `get_version` reply,
   which the exporter never requests). Detection therefore falls to `print.device.type`, and
   `_DEVICE_TYPE_TO_PRINTER[1] = "X1C"`. But `device.type` is a mode bitmask in BambuStudio
   (`DevInfo.h`: FDM=0x1, LASER=0x10, CUT=0x100), and every modern mock reports `1`: H2D,
   H2D Pro, H2S, H2C, P2S, X2D, A2L, X1C. Those printers get `model="X1C"` and the X1
   `home_flag` door path; H2 printers lose `lid_open` because `X1C` does not start with `H2`.
2. **`print.model_id` is not a model.** In mocks it is a 16-character opaque ID that differs
   per capture (empty on H2D Pro). The step-5 passthrough would emit it as an unbounded label.
3. **BambuStudio identifies printers by the first 3 characters of the serial**
   (`DevConfigUtil.cpp` `find_printer_by_sn_prefix`, prefixes in `resources/printers/*.json`).
   `BAMBULAB_SERIAL` is required config, so the exporter always has this.
4. **Product name matching misses the X1C.** Firmware reports `"Bambu Lab X1-Carbon"`; the
   table key is `"bambu lab x1 carbon"`.
5. **The cloud-discovered model is stored but never used for detection.**

## Verified identity table

| Model | Code | SN prefix | ota product_name | Source confidence |
|---|---|---|---|---|
| X1 Carbon | BL-P001 | 00M | Bambu Lab X1-Carbon | BS + ha |
| X1 | BL-P002 | 00W | not observed | BS (ha disagrees: 00M) |
| X1E | C13 | 03W | not observed | BS + ha |
| P1P | C11 | 01S | Bambu Lab P1P | BS + ha |
| P1S | C12 | 01P | Bambu Lab P1S | BS + ha |
| A1 mini | N1 | 030 | Bambu Lab A1 mini | BS + ha |
| A1 | N2S | 039 | Bambu Lab A1 | BS + ha |
| P2S | N7 | 22E | Bambu Lab P2S | BS + ha |
| X2D (new) | N6 | 20P | Bambu Lab X2D | BS; product name ha |
| A2L (new) | N9 | 26A | Bambu Lab A2L | BS; product name ha |
| H2D | O1D | 094 | Bambu Lab H2D | BS + ha |
| H2D Pro | O1E | 239 | Bambu Lab H2D Pro | BS; product name ha |
| H2S | O1S | 093 | Bambu Lab H2S | BS + ha |
| H2C | O1C / O1C2 | 31B | Bambu Lab H2C | BS; product name ha |
| "N8" (unreleased, laser only) | N8 | 35F | unknown | BS only; do not map yet |

AMS type from `ams[].info` bits 0-3 (BS `DevDefs.h`): 0 external spool, 1 AMS, 2 AMS Lite,
3 AMS 2 Pro (N3F), 4 AMS HT (N3S), 5 AMS Lite mixed (A2L). The exporter lacks 0 and 5.

## Phase 1: Correct model identity (highest value, needs label-change sign-off)

New resolver order:

1. `product_name` from any module list, normalized (lowercase, `-` and whitespace collapsed
   to a single space).
2. Payload `print.sn` prefix.
3. Configured `BAMBULAB_SERIAL` prefix (supersedes PR #45's approach; see Phase 6).
4. Cloud-discovered model (`dev_product_name` / `model`), normalized through the same tables.
5. Legacy `hw_ver` + `project_name`, keeping only unambiguous entries (C11, C12, N1, N2S).
   Drop `("AP05", "")` and `("AP02", "")`: AP05 is shared by X1C, H2D, H2S, H2C and A1.
6. Otherwise unknown.

Removals: `_DEVICE_TYPE_TO_PRINTER` (mode bitmask) and the `model_id` passthrough.

Table updates: full BambuStudio prefix table (adds 20P, 26A, 239, 31B), product names for
X2D and A2L.

Decision needed: for an unknown model, keep omitting `bambulab_printer_model_info` (current
behavior, hides the printer from the sample dashboard's `job` dropdown) or emit
`model="unknown"`. Recommendation: emit `unknown`, a fixed bounded value.

Plumbing: pass the configured serial and cloud model into `PrinterSnapshot` from the client
and composition root, and update the e2e/integration fake clients so `make test-profile`
exercises the same path.

## Phase 2: Model capabilities as data

Replace `X1_HOMEFLAG_MODELS` and the `startswith("H2")` lid check with one capability table
per model (door source, lid source, chamber sensor, dual extruder, laser/cut modes).

- Door: X1 family uses `home_flag` bit 0x00800000, others `stat` bit 0x00800000. Verify
  whether X1E belongs in the X1 group (currently excluded).
- Lid: no source documents a separate lid sensor. Keep the H2 `stat` 0x01000000 decode for
  compatibility, but list it as unverified.
- Unknown models keep the generic path (stat first), as today.

## Phase 3: AMS decoding

Add info types 0 (external spool, ignore) and 5 (AMS Lite mixed, map to `ams_lite`). Keep the
serial prefix fallback. Label values stay within the existing bounded set.

## Phase 4 (optional, needs approval): request `get_version`

A single read-only `get_version` request at connect (no printer control) returns the module
list: product names, firmware versions, AMS units. This enables product-name detection and
future firmware-version info metrics. It is a new publish, so it needs explicit approval per
the project's MQTT safety rules.

## Phase 5: Tests and docs

- Synthetic fixtures per model (structure based on public mocks, no copied IDs): pushall
  without identity, get_version module lists, unknown prefix, conflicting sources.
- Tests: every table entry, resolver priority, unknown handling, `printer_model_info`
  emission and clearing, door/lid per capability, AMS types 0 and 5.
- Docs: supported-models table (detected vs hardware-validated; only X1C validated), fix
  Troubleshooting's claim that the metric shows `unknown`, Metrics-Reference `lid_open`
  entry, CHANGELOG migration note listing which printers change label.

## Phase 6: Coordinate with PR #45

PR #45 (X2D via configured serial) is a subset of Phase 1. The local follow-up commit
`97af50b` on `pr-45` skips the serial fallback when `model_id` is present, which is wrong
given finding 2 (X2D reports a non-empty `model_id`, so it would fall back to `X1C`). Do not
push it. Options: merge PR #45 as-is after removing the real serial from its tests, then do
Phase 1 on top, or close it in favor of Phase 1 with credit to the contributor.

## Compatibility impact

- `model` label changes for affected printers, most notably LAN-connected H2D, H2D Pro,
  H2S, H2C, P2S, X2D and A2L currently shown as `X1C`. This is a correction, but it starts
  new series; dashboards and alerts filtering on `model` need updating.
- `door_open` source changes for those printers (from `home_flag` to `stat`), and
  `lid_open` starts reporting for H2 printers that were mislabelled.
- No metric names, types or base labels change.

## Open questions

- AMS 2 Pro serial prefix (19C) is unverified.
- X1, X1E and A1 product names on current firmware are not observed.
- X1 prefix conflict (BS 00W vs ha 00M); trust BS.
- Real-hardware confirmation for anything beyond X1C needs community payloads.
