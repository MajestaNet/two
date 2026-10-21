# ADR 0022 — Climate tool contract and the first device package

## Status

Accepted (protocol and executor). The climate slot stays off until an
installation binds it. Speech playback, profile preload, Matter
commissioning, and MQTT are not implemented by this ADR.

## Context

ADR 0017 keeps device adapters in this repository, default off, and
leaves the first protocol to a later ADR. ADR 0019 gives `home-action`
typed device tools and says the controller or the device adapter
performs them. ADR 0021 reserves `src/two/devices/<name>/` until that
protocol ADR exists, and it leaves `home-action` unexecutable.

The first action has to survive vendor firmware. Air-conditioning
brands do not share a control protocol. The stable seam is the
thermostat capability: local temperature, setpoint, mode, and a
read-back after the write. Matter's Thermostat cluster already names
those fields. The first transport should be one local bus that has
already normalized vendors, not a package per brand.

An install-added tool server would put device credentials and an open
tool list inside the harness profile. ADR 0019 keeps that profile
typed and small. The harness already emits tool calls. The control
plane is the only component that may perform them.

## Decision

1. **The closed tool list is the contract.** `home-action` may request
   only `climate.read`, `climate.set_setpoint`, and `climate.set_mode`.
   Arguments are a zone id and, for the writes, Celsius or a mode of
   `off`, `heat`, `cool`, or `auto`. The result is a read-back: zone,
   Celsius, setpoint, mode, and reachability. The model sees zone names
   and Celsius. It does not see entity ids, upstream URLs, or tokens.
2. **The control plane performs the call.** DeepSeek Harness emits the
   tool request. This process does not send `execute` back to the
   child. A tool outside the list fails the turn and writes nothing.
   A plain assistant reply with no tool is stored and does not touch
   a device.
3. **Policy is pre-authorization or an approval digest.** A configured
   zone may be read. A setpoint inside that zone's band, or a mode on
   that zone's list, runs. A setpoint or mode outside the band waits
   for an approval whose digest is that tool, zone, entity, and
   argument. An unknown zone is refused and is not approvable. Silence
   is not approval. A repeated decision with the same digest is a
   no-op. A changed digest is stale.
4. **The read-back is the result.** The receipt's `climate` object is
   the observation after the call. A model sentence is not completion.
   Setpoint and mode writes are idempotent, so a retry after a crash
   reconciles by performing the same stored call and reading again.
5. **The first transport is Home Assistant climate REST.** The package
   is `two.devices.climate`. It uses the standard library. The upstream
   must be a loopback or private IP origin. The token is the value of
   the environment variable named in the binding. It is not stored, not
   sent to the harness, and not returned on the API. MQTT and a Matter
   controller are later transports behind the same three tools.
6. **The install binds zones. It does not register tools.** The
   catalog slot `climate` is `shipped`, `selectable`, and
   `default_enabled: false`. `$TWO_DATA_DIR/devices/climate.yaml`
   enables it and names zones, the upstream, the token variable, and
   the pre-authorized band and modes. A missing or invalid file leaves
   `home-action` `profile_not_executable` and stores nothing. Landing
   the package does not enable it. The kind-level `device` slot stays
   reserved for a later protocol.
7. **The turn is not a coding task.** Schema v8 stores `home-action`
   turns and climate approvals in their own tables. They do not take a
   coding lease. A running home-action turn blocks coding dispatch. A
   queued chat turn is admitted first. `awaiting_approval` does not
   hold the inference slot.

## Consequences

- `docs/architecture.md` §5.2, §5.4, §16, §20, and §21 point here.
  Speech, profile preload, and slot priority past this admission order
  stay open. Landing this ADR does not close §21 item 20.
- `config/adapters/catalog.yaml` lists `climate`. `two adapters` still
  enables only `cli`.
- The local operator and `client:watch` may submit `home-action`. The
  watch still cannot submit `self-build`.

## Alternatives rejected

- **One package per air-conditioning brand.** The tool list would track
  firmware instead of the capability the profile is allowed to request.
- **An install-registered MCP server.** The tool list and the device
  credential would leave the control plane. A plugin could enable
  itself without the catalog and without adoption.
- **A Matter controller as the first transport.** The schema follows
  the Thermostat cluster. Commissioning a controller is a later
  package, and it is a new runtime dependency.
- **Letting the harness perform the HTTP call.** That sends the token
  and the upstream into the model process. ADR 0019 keeps device I/O
  on this side of the tool request.
