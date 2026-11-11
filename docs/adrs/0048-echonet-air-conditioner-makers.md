# ADR 0048 — Japan ECHONET air-conditioner makers

## Status

Accepted. Amends ADR 0027 (one ECHONET Lite transport). The climate slot
stays off until an installation binds it. Dry, fan, vanes, and half
degrees are not implemented by this ADR.

## Context

ADR 0027 keeps one closed tool list (`climate.read`,
`climate.set_setpoint`, `climate.set_mode`) and speaks ECHONET Lite
class `0x0130` on UDP 3610. The installation units are Mitsubishi
Electric. The same class is the Japan home-air-conditioner object.
Daikin, Panasonic, Hitachi, Toshiba, Fujitsu General, and Sharp certify
room adapters for those same properties: operation status `0x80`, mode
`0xB0`, setpoint `0xB3`, and room temperature `0xBB`. The application
spec makes each of those one byte. Mode bytes are `0x41` auto, `0x42`
cool, and `0x43` heat. A setpoint is unsigned Celsius `0x00`–`0x32`,
and `0xFD` means no setpoint. Room temperature is signed Celsius, and
`0x7E` means unmeasurable.

Other common Wi-Fi dialects are not this class. MELCloud, Comfort
Cloud, FGLair, airCloud, ONECTA, and Smart M-Air send the command
through a vendor account or a different local HTTP API. A binding that
names one of those as ECHONET would store a unit this client cannot
answer.

## Decision

1. **The tool list does not change.** A Japan room air conditioner is
   still a zone. The model sees the zone id and Celsius. It does not
   see the address, the object, or the maker.
2. **The binding may name the maker.** `manufacturer` is optional and
   per zone. Omitted, it is `mitsubishi` (Mitsubishi Electric). The
   allowed names are `mitsubishi`, `daikin`, `panasonic`, `hitachi`,
   `toshiba`, `fujitsu`, and `sharp`. Any other string unloads the
   binding. A Home Assistant or ESPHome zone that carries the field is
   invalid. There is no second catalog slot. Landing this code does
   not enable the slot.
3. **The seven names share the current bytes.** There is no codec per
   maker and no branch in the frame builder. One `Get` reads each of
   the four properties. `off` is one `SetC` of status. `heat`, `cool`,
   and `auto` are one `SetC` of status and mode. A setpoint is one
   unsigned whole-degree byte from `0` to `50`. `0xFD` and `0x7E` stay
   unknown. A two-byte temperature stays unknown. `SetC_SNA` fails the
   turn and does not send a second frame. Dry (`0x44`) and fan (`0x45`)
   stay outside the mode list.
4. **The out-of-scope dialects do not answer this client.** MELCloud
   and MAC-567IF-E, the MAC-577IF-2E and MAC-587 HTTP dialect, Daikin
   export local HTTP (BRP069 and the later ONECTA adapters), Panasonic
   Comfort Cloud, Hitachi airCloud, Toshiba Home AC Control, Fujitsu
   General FGLair, a Sharp unit that only has COCORO AIR, and
   Mitsubishi Heavy Industries Smart M-Air need their own ADR. This
   one does not read maker code `0x8A`.

## Consequences

- Architecture §5.2, §5.4, and §16 point here. ADR 0022 remains the
  tool contract. ADR 0027 remains the transport. This ADR names the
  makers.
- An existing ECHONET file with no `manufacturer` field still loads as
  Mitsubishi Electric. A rewrite of that file does not grow the line.
- The action digest does not gain a field. The frames do not change
  when the operator sets `manufacturer: daikin` on a Japan adapter that
  already speaks this class.
- A narrower vendor setpoint band comes back as `SetC_SNA` or as the
  read-back. The zone band stays the policy.

## Alternatives rejected

- **A new climate tool or catalog slot per maker.** ADR 0022 already
  rejected that.
- **One codec per maker.** The class properties this client uses are
  mandatory and one byte. A second frame after `SetC_SNA` would be a
  different dialect.
- **MELCloud, Comfort Cloud, FGLair, airCloud, ONECTA, BRP069, and
  Smart M-Air.** Each is a cloud account or another local API.
- **Reading `0x8A` to discover the brand.** The operator writes the
  name. The client does not trust a byte it does not need.
