# ADR 0038 — Ecovacs vacuum tools on `home-action`

## Status

Accepted (protocol and executor). The vacuum slot stays off until an
installation binds it. Room cleaning, maps, fan speed, mop control, and
a second transport are not implemented by this ADR.

## Context

ADR 0022 keeps device tools closed and performed by the control plane.
ADR 0028 advertises that closed list and does not send `execute`. ADR
0029 added television the same way. ADR 0030 and ADR 0036 route and
compile an obvious device utterance.

The next devices on this installation are two Ecovacs vacuum robots.
Ecovacs publishes an MCP server and an Open API. The MCP server is a
process that POSTs four calls to `https://open.ecovacs.com` or
`https://open.ecovacs.cn` with an API key. Running it would put that key
and an open tool list beside the model. ADR 0022 already rejects an
install-registered MCP server. The advertisement in this repository
lists closed tools and performs nothing.

These robots do not speak a documented private-LAN protocol the way a
Samsung television speaks local HTTP or an air conditioner speaks
ECHONET Lite. Community libraries still depend on the Ecovacs account,
a model-specific firmware quirk, or a second server. Architecture says
device traffic stays on the private network. This vendor is the
exception: the account already uses the Open API, and that API is the
protocol a third party can call.

## Decision

1. **The closed tool list is the contract.** `home-action` may request
   `vacuum.read`, `vacuum.clean`, and `vacuum.dock` when a vacuum
   binding is enabled. Arguments are a robot id plus, for the writes,
   `action`. Clean actions are `start`, `pause`, `resume`, and `stop`.
   Dock actions are `start` (return to the dock) and `stop`. The result
   is a read-back: robot, activity (`cleaning`, `paused`, `idle`,
   `returning`, `docked`, `other`), charging, station (`idle`, `wash`,
   `dry`, `dust`, `clean`, `paused`, `unknown`), and reachability. The
   model sees robot ids. It does not see nicknames, the API host, or
   the key.
2. **The control plane performs the call.** This amends ADR 0028 and
   ADR 0029: the session advertises the closed tools of each binding
   that loaded. A vacuum-only install does not advertise climate or
   television tools. The advertisement does not perform a call, and
   this process does not send `execute`. One tool ends the turn. A
   sentence with no tool is stored and does not touch a robot.
   `home-action` is executable when the climate binding, the television
   binding, or the vacuum binding is valid. Missing all three stays
   `profile_not_executable`.
3. **A known robot is pre-authorized.** Read, clean, and dock on a
   bound robot run. There is no out-of-band argument in this slice, so
   there is no approval table. An unknown robot is `vacuum_robot_denied`
   and is not approvable. Silence is not approval. A missing binding is
   `vacuum_not_configured`. An upstream or status failure is
   `vacuum_upstream` and does not invent a state.
4. **The slot stays off.** `config/adapters/catalog.yaml` marks
   `vacuum` shipped, selectable, and `default_enabled: false`. The
   package is `src/two/devices/vacuum/`. Importing it does not enable
   the slot. The binding is `$TWO_DATA_DIR/devices/vacuum.yaml`. A
   missing, disabled, or invalid file leaves the slot off. The example
   uses placeholder nicknames. The key is not committed.
5. **The operator binds exact nicknames.** Each robot has an operator
   id and the nickname the Ecovacs account already uses. Nicknames are
   unique. The client sends that exact nickname. It does not use the
   vendor fuzzy match, which can select the wrong of two robots. The
   model does not see the nickname. `two vacuum robots` prints the
   account's nicknames and writes nothing.
6. **The transport is the Open API, called from this process.** The
   client is the standard library. `api_host` is only
   `open.ecovacs.com` (the default, including this Australian
   installation) or `open.ecovacs.cn`. Any other host is refused.
   Redirects are refused. The key is the value of the environment
   variable named by `token_env`. It is sent in the JSON body, not the
   query string, and it is not stored, not sent to the harness, and
   not returned on the API. This is the only device transport that
   leaves the private network. No other host is allowed.
7. **The read-back is the result.** A clean or dock call is followed
   by a status read. The receipt's `vacuum` object is that observation.
   A model sentence is not completion.
8. **Schema v11** rebuilds `home_action_turns` so the tool check
   includes the three vacuum tools. It does not add an approvals table.

## Consequences

- `docs/architecture.md` records the private-network exception for this
  transport only. Later room cleaning stays a later ADR.
- Home Assistant vacuum REST and a local cloud replacement can be a
  later transport behind the same three tools. They are not required
  for these two robots.
- ADR 0028's closed-list sentence applies to whichever device bindings
  are loaded.

## Alternatives rejected

- **Run `ecovacs-robot-mcp` or point the harness at the vendor SSE
  endpoint.** The key and the tool list would leave the control plane.
  The server is a wrapper over the same four HTTP calls.
- **A direct socket on the robot.** Ecovacs does not publish a LAN
  protocol for these models. `sucks`, Bumper, and `deebot-client` are
  model-specific, often still need the account, and would be a new
  runtime dependency or a second server.
- **Home Assistant as the first transport.** It is a valid later
  transport. This installation can reach the two robots through the
  Open API without that extra process.
- **Fuzzy nickname matching.** Two robots on one account make a partial
  name able to hit the wrong machine.
- **An approval digest on every start.** Power on a bound television
  is pre-authorized. Start and dock on a bound robot are the same
  class of action. An unknown robot stays refused.
