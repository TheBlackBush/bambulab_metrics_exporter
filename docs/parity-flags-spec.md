# Flag Parity Spec (Phases 0-1)

## Goal
Build a stable bitmask decoding foundation for full parity rollout of binary status signals.

## Canonical masks (current rollout)

- `door_open`: `0x00800000`
- `sd_card_present`: `0x00000100`
- `sd_card_abnormal`: `0x00000200`

## Source fields

- `home_flag` (integer bitmask)
- `stat` (hex string bitmask)
- direct fields when explicitly provided (e.g. `door_open`, `sdcard`)

## Decoder layer (Phase 1)

Implemented in `src/bambulab_metrics_exporter/flags.py`:

- `to_int(value)`
- `to_hex_int(value)`
- `is_flag_set(raw, mask)`
- `decode_home_flags(home_flag)`
- `decode_stat_flags(stat)`

The decoder layer is intentionally independent from metric emission so parity extensions can be added safely.

## Door source-selection policy

- Use direct `door_open` when explicitly present.
- For `X1`/`X1C`: prefer `home_flag`, fallback to `stat`.
- For other models: prefer `stat`, fallback to `home_flag`.

## SD card policy

- Use direct `sdcard` when explicitly present.
- Otherwise derive from `home_flag`:
  - present + abnormal => `abnormal`
  - present only => `present`
  - not present => `absent`

## Next phases

- Expand mask map to full binary parity set.
- Add corresponding metrics + dashboards + alerts in staged batches.
- Validate each added flag against live MQTT payload samples before enabling alerts.
