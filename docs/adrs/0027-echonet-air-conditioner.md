# ADR 0027 — Direct air-conditioner transport is ECHONET Lite

## Status

Accepted. The climate slot stays off until an installation binds it.
Speech, MQTT, Matter commissioning, and other Wi-Fi dialects are not
implemented by this ADR.

## Context

ADR 0022 keeps one closed tool list (`climate.read`,
`climate.set_setpoint`, `climate.set_mode`) and performs those calls in
the control plane. Its first transport is Home Assistant climate REST.
That still requires a second home-automation server on the LAN.

The units in this installation are Mitsubishi Electric air conditioners
joined to the local Wi-Fi. Mitsubishi documents a local protocol for
the MAC-568IF-E, MAC-578IF-E, and MAC-588IF-E interfaces: ECHONET Lite,
home air conditioner class `0x0130`, UDP port 3610. It is off until the
operator enables it in the Wi-Fi Control app. It has no authentication.
The same three thermostat fields ADR 0022 already names are standard
properties on that class: operation status, mode, setpoint, and room
temperature.

Other Mitsubishi interfaces are a different dialect. MELCloud
(MAC-567IF-E and the cloud app) still sends the command through the
vendor cloud. MAC-577IF-2E speaks an encrypted local HTTP API. Neither
is this transport.

## Decision

1. **The tool list does not change.** A direct unit is still a zone.
   The model sees the zone id and Celsius. It does not see the unit
   address, the ECHONET object, or a brand command.
2. **The binding selects the transport.** `transport: home_assistant`
   remains the default and still requires a private origin and a token
   variable. `transport: echonet` names each zone's private IPv4
   address and an instance number (default 1). It has no token and no
   upstream URL. A missing or invalid file still leaves `home-action`
   unexecutable. Landing this code does not enable the slot.
3. **The client is stdlib UDP.** The package stays `two.devices.climate`.
   One Get reads status, mode, setpoint, and room temperature. One
   SetC writes a whole-degree setpoint, or power together with
   `off` / `heat` / `cool` / `auto`. The receipt is the read-back after
   the write. A property the class refuses, a timeout, or a non-whole
   degree fails the turn with `climate_upstream` and does not invent a
   state. Dry and fan are not modes in the closed list.
4. **Discovery is not the agent.** An operator may look for home air
   conditioner instances on the LAN. The worker does not multicast, and
   `two climate` still talks only to the control API. The binding is
   the addresses the operator wrote.
5. **The address stays on the private network.** A hostname, a public
   address, and the ECHONET multicast address are refused. There is no
   credential to store. The protocol itself has none, so the LAN that
   can reach UDP 3610 can issue the same writes.

## Consequences

- Architecture §5.2, §5.4, and §16 point here. ADR 0022 remains the
  tool contract. This ADR adds a transport.
- A MAC-567IF-E unit will not answer. A MAC-577IF-2E unit will not
  answer this client. Those dialects need their own ADR. This one does
  not add a crypto dependency and does not use adapter debug
  credentials.
- Setpoints are whole degrees because that is the ECHONET property.
  Half degrees available in the vendor app are not on this class.
- One indoor unit is one zone. A ducted system that exposes a single
  home air conditioner object is one zone.

## Alternatives rejected

- **MELCloud.** The vendor manual says local control still goes through
  the internet. That puts a device credential and a public service on
  the turn.
- **The MAC-577IF-2E encrypted HTTP dialect in this slice.** It is a
  different interface, and the public write-ups of it include debug
  credentials and a telnet path. Those are not a transport we ship.
- **A new climate tool per brand.** ADR 0022 already rejected that.
  Fan speed, vanes, and dry stay outside the list.
- **Requiring Home Assistant in front of these units.** That transport
  stays available. It is not required when the unit speaks ECHONET Lite.
