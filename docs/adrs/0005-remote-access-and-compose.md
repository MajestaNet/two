# ADR 0005 — Overlay for the API; Compose for unattended

## Status

Accepted. Messaging product identity is superseded by
[ADR 0007](0007-backend-first-channels.md).

## Context

Operators will drive tasks from another network. The spec forbids
publishing the inference API or Harness UI. It was easy to misread that
as “remote access is missing.”

A second question: should every development host start as a Docker/VM
running the harness?

## Decision

1. **Off-LAN chat = an optional messaging adapter** that dials out (Slack
   Socket Mode is the MVP example). Do not expose the Majesta Two API or Ollama so a
   vendor can webhook in. See ADR 0007.
2. **Off-LAN CLI or web = private overlay** (Tailscale or WireGuard) plus
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

Setup leads with the API and CLI. Slack is documented as the first
adapter, not as the product. `deploy/compose` packages `api`, `scheduler`,
and `worker` (optional `slack` profile is a stub until B14). Ollama is
never in this image. See [B12](../backlog/B12-dev-host-services.md).
