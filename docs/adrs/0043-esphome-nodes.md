# ADR 0043 — Shared ESPHome nodes behind climate zones

## Status

Accepted. Amends ADR 0027 (document-wide climate transport) and ADR 0039
(`install.propose_binding` slots). Does not add climate tools, a catalog
slot, a harness profile, or a schema version. Speech, raw IR/RF blaster
tools, and BLE proxy subscription are not implemented by this ADR.

## Context

ADR 0022 keeps one closed tool list (`climate.read`,
`climate.set_setpoint`, `climate.set_mode`) and performs those calls in
the control plane. ADR 0027 adds ECHONET Lite as a second transport and
selects it for every zone in the climate file. That choice cannot name
an older infrared LG unit on the same install as a Mitsubishi ECHONET
zone.

The board in this installation is an ESPHome node: an IR transmitter,
optional 433 MHz radio, and a BLE proxy. ESPHome already owns the LG
infrared dialect (`climate_ir_lg`). Majesta Two must not grow an LG
package and must not speak raw IR or RF. The node connection is useful
for later device categories. Climate is the first consumer.

ESPHome's native API is a custom TCP protocol. Password authentication
was removed in ESPHome 2026.1.0. Encryption uses a 32-byte base64 Noise
key. Infrared is unidirectional: a successful reply is the node, not
proof of the air conditioner's room state.

## Decision

1. **Shared nodes, not a device slot.** `$TWO_DATA_DIR/devices/esphome.yaml`
   lists nodes: id, private IPv4 address, port (default 6053), and
   `key_env`. The value of that variable is the native-API encryption
   key (`openssl rand -base64 32`). The key is never stored in the file,
   sent to the harness, or printed on an operator reply. A hostname, a
   public address, and a plaintext API are refused. Chip type is not a
   field: ESP8266 and ESP32-class boards use the same API. There is no
   `esphome` catalog slot and no `home-action` profile for the node
   file. Landing this code does not enable climate.

2. **A zone may select ESPHome.** `transport: home_assistant` remains
   the document default. `transport: echonet` remains valid. A zone may
   set `transport: esphome`, `node`, and `entity` (the ESPHome climate
   `object_id`). It still has a logical `entity_id` of `climate.*`, a
   Celsius band, and modes of `off` / `heat` / `cool` / `auto`. Zones
   that omit `transport` keep the document transport. A file may mix
   ECHONET and ESPHome zones. `upstream` and `token_env` are required
   only when some zone still uses Home Assistant.

3. **Read-back is the node, not the AC.** Infrared is one-way.
   `reachable` means the node answered. Setpoint and mode are the
   entity's assumed state (`climate_ir_lg` can also track the handheld
   remote when a receiver is configured). Room Celsius is set only when
   that entity reports `current_temperature`; otherwise it is null. Dry,
   fan, and swing are not closed modes. A reported dry or fan state
   comes back with mode null. Unknown node, missing key, timeout, or a
   non-climate object id fails the turn with `climate_upstream` and does
   not invent a state.

4. **No raw blaster and no BLE proxy.** `two esphome entities` may list
   other domains (including `infrared`, `radio_frequency`, and BLE) as
   names only. This slice does not transmit raw codes and does not
   subscribe to advertisements. Later categories can bind those names
   without a second connection client. The worker does not discover
   devices on a turn.

5. **The client is `aioesphomeapi`.** The package is MIT-licensed and
   runs on Python 3.11+. The public surface in this repository is a
   small sync wrapper. Unit tests inject that wrapper and do not open a
   socket. One connect, command, read, and disconnect runs per climate
   call. The control plane still performs the closed climate tools.

6. **Operator writes configuration only.** `install.propose_binding`
   accepts slot `esphome` and still writes only the matching yaml under
   the data directory after approval. It does not flash firmware.
   Replacing a file still replaces the whole document, so a climate
   proposal must repeat zones already on the install. The model does
   not receive the encryption key.

## Consequences

- Architecture §5.2, §5.4, and §16 point here. ADR 0022 remains the
  tool contract. ADR 0027 remains the ECHONET dialect. This ADR adds a
  node file and a per-zone climate transport.
- Pins and LG timings that differ by region stay in the ESPHome yaml
  flashed to the board, not in this repository.
- SQLite stays at schema v12. Operator tool names do not change.

## Alternatives rejected

- **A third exclusive document transport.** That would force a choice
  between Mitsubishi ECHONET units and an ESPHome LG zone.
- **Home Assistant in front of every ESPHome node.** That transport
  stays available. It is not required when this process can speak the
  native API on the private LAN.
- **An LG climate package or raw IR tools.** ADR 0022 already rejected
  a tool list that tracks firmware. The capability is still a zone.
- **A data-directory plugin or a catalog slot named `esphome`.** Nodes
  are configuration for shipped device packages. Climate, television,
  and vacuum stay the device slots.
- **Letting the harness hold the Noise key.** ADR 0019 keeps device I/O
  on this side of the tool request.
