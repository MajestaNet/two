# Channels

This repository is the **Majesta Two backend**. People interact with it
through clients of one control API. A messenger is optional and deferred.

Operator walkthrough: [setup.md](setup.md). The install menu is
[adapters.md](adapters.md) (`two adapters`). CLI on the development host
is enough; this page is the channel contract.

The contract is [architecture.md](architecture.md) §6.3.H and §8.3: one
task id, typed commands, stored projection (`two.projection`,
[B07](backlog/B07-control-api.md)). The additive GUI design is
[client-api-design.md](client-api-design.md). Clients never query the model
for status.

## First-party

| Surface | Role |
| --- | --- |
| Control API | Source of truth. Unix socket or loopback by default. |
| CLI | Same API, on this machine or over a private overlay. |
| Operator window | `apps/console`. Starts the control plane. Loopback only. |
| iPhone and Apple Watch | [MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile). Enrollment and push-to-talk. Not a second agent. |
| Development-loop GUI | [B14](backlog/B14-secure-mobile-client.md) / ADR 0015. API slices are in this repo. The native GUI is not built. |

## iPhone and Apple Watch

The apps are [MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile).
How to run them against this install is [local.md](local.md). The phone
enrolls with a client certificate. The watch sends text. Profiles are
`chat` and `home-action`. They do not submit `self-build` or resume
`operator`. Speech recognition stays on the device.

The separate B14 client would provide Projects, Task conversation,
Development loop, Evidence, and System views, with OAuth 2.1
Authorization Code and PKCE. That GUI is not built. OIDC is not accepted
([ADR 0016](adrs/0016-oidc-jwt-tls-dependencies.md)). The shared CLI
bearer token is not a phone credential.

Closing the phone does not stop the control plane.

## Local device packages

Climate, television, and vacuum are in-repo packages on this
installation
([ADR 0017](adrs/0017-local-self-building-system.md),
[architecture.md](architecture.md) §5.2,
[ADR 0021](adrs/0021-adapter-install-catalog.md)). They live under
`src/two/devices/`. ESPHome nodes are `src/two/devices/esphome/` and are
not their own catalog slot. The kind-level `device` slot stays reserved.

They are not messengers and not a second agent. They default off, stay
on the private network, and cannot reach shell, git, or secrets. They
do not open Ollama. The phone and watch submit text through the control
API. The controller resumes a persisted DeepSeek Harness profile
([ADR 0019](adrs/0019-mini-resident-control-plane.md),
architecture §5.4): `chat` has no tools, and `home-action` may request a
typed device tool. Neither profile is `self-build`. Climate is
[ADR 0022](adrs/0022-climate-device-protocol.md). Televisions are
[ADR 0029](adrs/0029-samsung-tv.md) (Samsung),
[ADR 0047](adrs/0047-lg-webos-tv.md) (LG webOS), and
[ADR 0049](adrs/0049-tcl-tv.md) (TCL Roku). Ecovacs vacuums are
[ADR 0038](adrs/0038-ecovacs-vacuum.md). Connect steps are in
[setup.md](setup.md).

## Watch voice client

An Apple Watch app is a first-party client of this API, not a device
adapter and not a HomePod integration
([ADR 0020](adrs/0020-watch-edge-mtls.md),
[watch-client.md](watch-client.md)). Caddy on a private address
requires a client certificate and proxies to the loopback API. The
watch principal cannot submit a self-build task. `chat` is stored
and resumed on the single inference slot
([B20](backlog/B20-chat-profile-resume.md)): `two chat send` /
`two chat show`, schema v7, and no coding lease. `home-action` is
stored and can run the closed climate tools when
`$TWO_DATA_DIR/devices/climate.yaml` enables them
([ADR 0022](adrs/0022-climate-device-protocol.md),
[ADR 0027](adrs/0027-echonet-air-conditioner.md),
[ADR 0048](adrs/0048-echonet-air-conditioner-makers.md),
[ADR 0028](adrs/0028-home-action-acp-client.md),
[B21](backlog/B21-climate-home-action.md)), and the closed television
tools when `$TWO_DATA_DIR/devices/tv.yaml` enables them
([ADR 0029](adrs/0029-samsung-tv.md),
[ADR 0047](adrs/0047-lg-webos-tv.md),
[ADR 0049](adrs/0049-tcl-tv.md)), and the closed vacuum tools when
`$TWO_DATA_DIR/devices/vacuum.yaml` enables them
([ADR 0038](adrs/0038-ecovacs-vacuum.md)). The climate binding transport is
Home Assistant REST, ECHONET Lite, or an ESPHome climate entity on a
shared node. The vacuum transport is the Ecovacs
Open API on the two official hosts. Without a climate, television, or
vacuum binding the turn is `profile_not_executable` and is not stored. The Xcode project is
[MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile), not
this repository. The catalog keeps `watch` at `contract`. Speech
recognition runs on the phone and the watch. This API receives text.

## Messengers (none selected)

A future messenger adapter should authenticate one vendor, map events to
typed Majesta Two commands, apply disclosure policy, and remain unable to
reach Ollama, shell, or git. None is selected. See
[adapters.md](adapters.md).

GitHub pull-request export is **not** a channel. It is a post-MVP
source-control adapter ([source-control-export.md](source-control-export.md),
[ADR 0012](adrs/0012-github-export-adapter.md)). Channels still must not
run git.

## Remote use

- **iPhone and Apple Watch:** Caddy mutual TLS on the home Wi-Fi address
  and the Tailscale address. Never publish the API. OIDC is the unbuilt
  B14 GUI, not this phone.
- **Any future cloud messenger:** prefer an outbound adapter. Do not publish
  the Majesta Two API so a vendor can webhook in.
- **CLI off-LAN:** Tailscale/WireGuard. See [remote-access.md](remote-access.md).
