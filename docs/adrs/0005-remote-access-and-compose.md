# ADR 0005 — Overlay for the API; Compose for unattended

## Status

Accepted. Messaging product identity is superseded by
[ADR 0007](0007-backend-first-channels.md); the first-party mobile remote
path is detailed by [ADR 0015](0015-first-party-client-api.md).

## Context

Operators will drive tasks from another network. The spec forbids
publishing the inference API or Harness UI. It was easy to misread that
as “remote access is missing.”

A second question: should every development host start as a Docker/VM
running the harness?

## Decision

1. **Original chat decision, superseded:** an outbound messaging adapter was
   selected for off-LAN chat. ADR 0015 instead plans a first-party mobile
   client over authenticated HTTPS on a private overlay. Future outbound
   adapters remain optional. Do not expose Majesta Two or Ollama publicly.
2. **Off-LAN clients = private overlay** (Tailscale or WireGuard) plus
   controller authentication. Default API bind stays loopback or a Unix
   socket.
3. **Ollama stays native on the Mac.** No Docker on the inference host.
4. **Compose is the recommended unattended packaging** for Majesta Two on a
   Linux development host. A full VM is optional extra isolation, not
   required to contribute.
5. **Harness is not in the foundation image.** Interactive use keeps DSH
   on the host so language servers and toolchains stay ordinary. Phase 5
   may add a worker/harness service with explicit mounts.

## Consequences

Setup leads with the API and CLI. `deploy/compose` packages `api`, `scheduler`,
and `worker` (the optional `slack` profile is a deferred legacy stub). Ollama is
never in this image. See [B12](../backlog/B12-dev-host-services.md).
