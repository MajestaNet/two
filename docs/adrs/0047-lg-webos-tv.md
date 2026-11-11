# ADR 0047 — LG webOS television brand

## Status

Accepted. Amends ADR 0029 (one television transport). The television slot
stays off until an installation binds it. Title search, account resume,
pointer and keyboard input, and the ThinQ cloud are not implemented by
this ADR.

## Context

ADR 0029 keeps one closed tool list (`tv.read`, `tv.set_power`,
`tv.open`, `tv.set_volume`) and performs those calls in the control
plane. Its transport is the Samsung local API. That choice cannot name
an LG set on the same install, and a second install that only has LG
sets would have to pretend they are Samsung.

Current LG sets speak webOS SSAP on the private LAN. Plain websocket is
port 3000. TLS is port 3001, with a certificate the set signs itself.
Pairing is an on-screen prompt that returns a client key. Power off is
`system/turnOff`, not a toggle. Power on is `system/turnOn` while the
socket is up, and a Wake-on-LAN packet when it is not. Volume is 0–100
on that same socket. An application id launches and reads back as the
foreground app. HDMI inputs are application ids such as
`com.webos.app.hdmi1`, not Samsung `KEY_` names.

An older infrared LG set is still an ESPHome climate zone (ADR 0043).
It is not a television.

## Decision

1. **The tool list does not change.** A webOS set is still a set. The
   model sees the set id, spoken aliases, and target aliases. It does
   not see the address, the application id, the client key, or the brand.
2. **The binding selects the brand.** `brand: samsung` remains the
   default when the field is omitted, on the document or on a set. A
   set may set `brand: lg` and override the document. One
   `$TWO_DATA_DIR/devices/tv.yaml` may mix brands. There is no second
   catalog slot. Landing this code does not enable the slot.
3. **The client is stdlib WebSocket.** The package stays
   `two.devices.tv`. `secure: false` tries `ws://` port 3000 first.
   `secure: true` tries `wss://` port 3001 first. If that handshake
   fails, the client tries the other scheme once on the same private
   address. Certificate verification is off only on that TLS socket.
   The registration payload is the public webOS handshake, not a
   credential. The client key is the credential and stays in the
   environment variable named by `token_env`.
4. **The four tools map onto SSAP.** `tv.read` reports power, the bound
   foreground app, volume, mute, and reachability. `Active` and
   `Screen Off` are on. `Active Standby`, `Suspend`, and `Power Off`
   are off. A dead socket is off and unreachable. `tv.set_power` off
   sends `system/turnOff` only while the set reads as on, then accepts
   standby or a dead socket. `tv.set_power` on sends `system/turnOn`
   when the socket is up, `turnOnScreen` when the state is `Screen Off`,
   or a Wake-on-LAN packet to the bound MAC when the socket is down,
   then polls. A failed wake does not invent `on`. `tv.open` launches
   the bound application id and requires that id to read back. `tv.set_volume`
   uses the same band, step, and approval rules as ADR 0029. `volume_url`
   and a `KEY_` target are refused on an LG set.
5. **Pairing and the app list stay operator steps.** `two tv pair` and
   `install.pair_device` wait for the on-screen prompt and store the
   client key in `$TWO_DATA_DIR/env`. They do not print it. `two tv apps`
   prints application ids and writes nothing. The model does not see
   either result beyond the redacted operator reply.

## Consequences

- Architecture §5.2 and §5.4 point here. ADR 0029 remains the tool
  contract. This ADR adds a brand.
- An existing Samsung file with no `brand` field still loads as Samsung.
- A Netcast set, a ThinQ cloud login, and an infrared blaster will not
  answer this client. Infrared LG air conditioners stay on ESPHome.
- Input changes for a bound application id are confirmed by the
  foreground app. Unbound inputs are not claimed.
- The action digest stays the address, application id, and key from
  ADR 0029. Addresses are unique, so the brand does not need a second
  field in that digest.

## Alternatives rejected

- **A new catalog slot per brand.** ADR 0022 already rejected a new
  tool list per brand. Climate keeps one slot and selects the transport
  on the binding. Television does the same.
- **Home Assistant in front of the set.** That adds a process the
  operator has to run. The set already speaks SSAP.
- **A Python webOS dependency.** The Samsung client is stdlib. This
  client stays stdlib.
- **Samsung `KEY_` names on webOS.** The set does not speak that
  dialect. HDMI is an application id the operator copies from
  `two tv apps`.
- **The ThinQ cloud.** That puts a vendor account on the turn. The
  local socket does not need it.
