# ADR 0029 — Samsung television tools on `home-action`

## Status

Accepted (protocol and executor). The television slot stays off until
an installation binds it. Title search, account resume, activities,
and a second transport are not implemented by this ADR.

## Context

ADR 0022 keeps device tools closed and performed by the control plane.
ADR 0027 says discovery is not the agent: the operator writes a private
address, and the transport is the protocol the device already speaks.
ADR 0028 advertises the three climate tools on the pinned ACP session
and does not send `execute`.

The first television sets on this installation are Samsung models on
the same LAN as the Mac mini. Putting another stick, app, or agent on
the set would add a device the operator has to manage. The sets already
speak a local HTTP and websocket API, and a UPnP RenderingControl
service for absolute volume. The websocket remote is a key click. It
does not set an absolute volume, and `KEY_POWER` is a toggle.

Application ids differ by region and year. The operator can read them
from the set. The model must not see addresses, application ids, keys,
or tokens. A later request to search a title or resume an account is a
conversation, not one of these tools.

## Decision

1. **The closed tool list is the contract.** `home-action` may request
   `tv.read`, `tv.set_power`, `tv.open`, and `tv.set_volume` when a
   television binding is enabled. Arguments are a set id plus, for the
   writes, `power` (`on` or `off`), a target alias, or volume `level`,
   `mute`, or `step` (`up` or `down`). `level` and `mute` may combine.
   `step` is exclusive. The result is a read-back: set, power, active
   target, volume, mute, and reachability. The model sees set ids and
   target aliases. It does not see addresses, application ids, keys, or
   tokens.
2. **The control plane performs the call.** This amends ADR 0028: the
   session advertises the closed tools of each binding that loaded.
   A climate-only install does not advertise television tools. A
   television-only install does not advertise climate tools. The
   advertisement does not perform a call, and this process does not
   send `execute`. One tool ends the turn. A sentence with no tool is
   stored and does not touch a set. `home-action` is executable when
   either the climate binding or the television binding is valid.
   Missing both stays `profile_not_executable`.
3. **The slot stays off.** `config/adapters/catalog.yaml` marks `tv`
   shipped, selectable, and `default_enabled: false`. The package is
   `src/two/devices/tv/`. Importing it does not enable the slot. The
   binding is `$TWO_DATA_DIR/devices/tv.yaml`. A missing, disabled, or
   invalid file leaves the slot off. The example uses documentation
   addresses and MAC values. Real MAC addresses and tokens are not
   committed.
4. **The operator binds the set.** Each set has a private IPv4 address,
   a MAC address copied from the router, a `token_env` name, a volume
   band, and named targets. A target is exactly one application id or
   one remote key such as `KEY_HDMI1`. Addresses are unique. A
   `volume_url` override, when present, must use that set's host.
   Otherwise volume uses
   `http://{address}:9197/upnp/control/RenderingControl1`. An unknown
   set or target is `tv_set_denied` and is not approvable.
5. **Pairing writes nothing.** `two tv pair --set ID` opens the bound
   set, waits for the on-screen Allow prompt, and prints
   `TOKEN_ENV=value`. The operator adds that line to `$TWO_DATA_DIR/env`
   and restarts the worker. `two tv apps --set ID` prints application
   ids and writes nothing. `two tv send`, `show`, `approve`, and
   `reject` talk only to the control API.
6. **Power is observed before a toggle.** `tv.set_power` is
   pre-authorized. When the REST device info already matches the
   requested power, no key is sent. `off` sends `KEY_POWER` only while
   the set reads as on, then waits until device info says standby.
   `on` sends `KEY_POWER` when a token is present, or a Wake-on-LAN
   magic packet to the bound MAC when the API is down, then polls.
   A receipt after a failed wake says the set is off or unreachable.
   It does not invent `on`.
7. **Opening a target wakes inside the control plane.** `tv.open` is
   pre-authorized. An application target is launched and must then read
   back as running. An input key is sent after the set is on.
   `active_target` stays null unless a bound application is observably
   running. The receipt does not claim the HDMI input.
8. **Volume is read back.** Mute is pre-authorized. A level from 0 to
   100 inside the binding band runs. A level outside the band and still
   inside 0–100 waits for an approval digest. Outside 0–100 is refused.
   A step reads the current level, adds or subtracts `volume_step`, and
   never writes above `volume_max`. If the current level is already
   above that maximum, step up writes nothing and step down clamps to
   the maximum. If the volume service cannot be read, `tv.read` still
   returns power with volume and mute null. `tv.set_volume` fails
   `tv_upstream` rather than inventing a level.
9. **The token and the TLS exception stay local.** The worker reads the
   named environment variable when it opens the broker. The websocket
   uses port 8002 with a certificate check disabled only on that socket
   to the bound private address. REST stays on port 8001. Redirects are
   refused. The digest includes the address, application id, and key so
   a binding edit invalidates an open approval. The stored arguments do
   not include those fields.
10. **Schema v9** rebuilds `home_action_turns` so the tool check includes
    the four television tools, and adds `tv_approvals`. A rejected
    television approval stores `tv_rejected`. Upstream failure stores
    `tv_upstream`. A missing binding stores `tv_not_configured`.

## Consequences

- Later activities, title search, and recommendations stay on `chat` or
  a later tool. They are not key macros in this list.
- Home Assistant is not a television transport in this ADR.
- A set without a MAC address cannot be woken while its API is down.
- Input changes are not confirmed by a source read-back.
- ADR 0028's "only the three climate tools" sentence applies when the
  climate binding is the only device binding loaded.
