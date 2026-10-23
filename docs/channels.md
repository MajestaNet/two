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

## First-party (this repo)

| Surface | Role |
| --- | --- |
| Control API | Source of truth. Unix socket or loopback by default. |
| CLI | Same API, for a development host or overlay. |
| First-party mobile | Planned B14 client over the same API and private overlay. Not a second agent. |

## Planned first-party mobile client

The secure native client is [B14](backlog/B14-secure-mobile-client.md) and
ADR 0015. It provides Projects, Task conversation, Development loop,
Evidence, and System views. It uses OAuth 2.1 Authorization Code with PKCE
against an operator-configured OIDC issuer, scoped server-derived identity,
and HTTPS over a private overlay. The shared CLI bearer token is not a mobile
credential.

Closing or disconnecting the app does not stop a task. The app projects the
persisted graph and controller evidence; it does not run a model/tool loop,
shell, git, or validation.

## Local device adapters (reserved)

Home, wearable, and later private-device adapters are an in-repo slot on
the self-building installation
([ADR 0017](adrs/0017-local-self-building-system.md),
[architecture.md](architecture.md) §5.2,
[ADR 0021](adrs/0021-adapter-install-catalog.md)). The catalog id is
`device`. The package path `src/two/devices/<name>/` does not exist yet.
They are not messengers, not a second agent, and not implemented. They
default off, stay on the private network, and cannot reach shell, git, or
secrets. They do not open Ollama.
A later wearable adapter submits text turns through the control API.
The controller resumes a persisted DeepSeek Harness profile
([ADR 0019](adrs/0019-mini-resident-control-plane.md),
architecture §5.4): `chat` has no tools, and `home-action` may request a
typed device tool such as a temperature change. Neither profile is
`self-build`. The adapter does not open Ollama. Climate is that
protocol ([ADR 0022](adrs/0022-climate-device-protocol.md)). Speech
still needs its own ADR.

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
[ADR 0028](adrs/0028-home-action-acp-client.md),
[B21](backlog/B21-climate-home-action.md)). The binding transport is
Home Assistant REST or ECHONET Lite. Without that binding the
turn is `profile_not_executable` and is not stored. The Xcode app is
not in this repository. The catalog keeps `watch` at `contract`.

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

- **First-party mobile:** HTTPS over Tailscale/WireGuard with trusted OIDC;
  never publish the API.
- **Any future cloud messenger:** prefer an outbound adapter. Do not publish
  the Majesta Two API so a vendor can webhook in.
- **CLI off-LAN:** Tailscale/WireGuard. See [remote-access.md](remote-access.md).
