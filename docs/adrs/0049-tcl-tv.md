# ADR 0049 — TCL Roku television brand

## Status

Accepted. Amends ADR 0029 (one television tool list). The television
slot stays off until an installation binds it. Google TV, Android TV
Remote, TCL Home, and infrared are not implemented by this ADR.

## Context

ADR 0029 keeps one closed tool list (`tv.read`, `tv.set_power`,
`tv.open`, `tv.set_volume`). ADR 0047 adds an LG webOS brand on that
list. A TCL set cannot use either transport.

Some TCL televisions run Roku OS. Those sets answer the Roku External
Control Protocol: plain HTTP on port 8060, no credential. Device info
reports `power-mode`. An active app reports a numeric channel id.
`PowerOn` and `PowerOff` are keypresses. Launch is `POST /launch/{id}`
with an empty body. There is no volume query and no mute query.
`VolumeUp`, `VolumeDown`, and `VolumeMute` are blind keypresses, and
mute is a toggle.

A TCL Google TV speaks Android TV Remote v2. That is TLS, a pairing
PIN, and protobuf. A TCL Home or MagiConnect login is a vendor account.
Neither is this brand.

## Decision

1. **The tool list does not change.** A TCL Roku set is still a set.
   The model sees the set id, spoken aliases, and target aliases. It
   does not see the address, the channel id, or the brand.
2. **The binding selects the brand.** `brand: samsung` remains the
   default when the field is omitted. A set may set `brand: tcl`. One
   `$TWO_DATA_DIR/devices/tv.yaml` may mix `samsung`, `lg`, and `tcl`.
   There is no second catalog slot. Landing this code does not enable
   the slot.
3. **The client is stdlib HTTP.** The package stays `two.devices.tv`.
   The port is 8060 and the scheme is HTTP. `secure: true`, a
   `token_env`, a `mac`, and a `volume_url` are refused. A target is a
   decimal channel id copied from `two tv apps`. A `KEY_` name is
   refused. There is no client key. `two tv pair` raises and stores
   nothing. Redirects are refused. The address stays a private IPv4
   address.
4. **The four tools map onto ECP.** `tv.read` reports power and the
   bound channel. `PowerOn` is on. `Headless` and `DisplayOff` are off
   and reachable. Any other `power-mode` is not observable. `volume`
   and `mute` stay null. `tv.set_power` sends `PowerOff` or `PowerOn`
   once and accepts the new mode only from a later device-info read.
   A failed wake does not invent `on`. `tv.open` launches the bound
   channel id and requires that id to read back. `tv.set_volume` raises
   before any request. The approval gate stays brand-blind, and a
   later approval does not make the write succeed.
5. **A stick is not a television.** When device-info contains `is-tv`
   and it is not `true`, a write raises and `tv.read` is offline.
   `vendor-name` is not used. Discovery is not the agent.

## Consequences

- Architecture §5.2 and §5.4 point here. ADR 0029 remains the tool
  contract. This ADR adds a brand.
- An existing file with no `brand` field still loads as Samsung.
- Absolute volume, mute, HDMI keys, and Wake-on-LAN are not claimed.
- The action digest stays the address, application id, and key from
  ADR 0029. The channel id is stored in the existing application id.

## Alternatives rejected

- **Android TV Remote or a hand-rolled protobuf codec.** That is a new
  dependency, or a second copy of protobuf. ADB is not these tools.
- **TCL Home, MagiConnect, and infrared.** A vendor account or a
  blaster, the same class ADR 0047 rejected for ThinQ and Netcast.
- **Blind volume keypresses.** The read-back could not show the level,
  and mute would toggle an unknown state.
- **A new catalog slot.** The tool list is already closed.
