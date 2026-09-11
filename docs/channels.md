# Channels

This repository is the **Majesta Two backend**. People interact with it
through clients of one control API. A messenger is optional and deferred.

Operator walkthrough: [setup.md](setup.md). CLI on the development host
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

## Adapters (optional, deferred)

A future Slack, Matrix, Discord, or other adapter should authenticate one
vendor, map events to typed Majesta Two commands, apply disclosure policy,
and remain unable to reach Ollama, shell, or git. No messaging adapter is
currently selected for implementation. Existing Slack stubs do not imply a
shipped or planned product.

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
