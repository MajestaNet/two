# ADR 0005 — Slack Socket Mode, overlay for API, Compose for unattended

## Status

Accepted

## Context

Operators will drive tasks from a phone Slack client and from laptops on
other networks. The spec already forbids publishing the inference API or
Harness UI. It was easy to misread that as “remote access is missing.”

A second question: should every development host start as a Docker/VM
running the harness?

## Decision

1. **Phone / off-LAN chat = Slack Socket Mode.** Outbound WebSocket only.
   Do not expose DevFlow or Ollama so Slack can webhook in.
2. **Phone / off-LAN CLI or web = private overlay** (Tailscale or
   WireGuard) plus controller authentication. Default API bind stays
   loopback or a Unix socket.
3. **Ollama stays native on the Mac.** No Docker on the inference host.
4. **Compose is the recommended unattended packaging** for DevFlow on a
   Linux development host. A full VM is optional extra isolation, not
   required to contribute.
5. **Harness is not in the foundation image.** Interactive use keeps DSH
   on the host so language servers and toolchains stay ordinary. Phase 5
   may add a worker/harness service with explicit mounts.

## Consequences

Setup docs lead with Slack for phones and Tailscale for API clients.
`deploy/compose` exists so the unattended topology is visible now, even
though api/scheduler/worker/slack processes are not implemented.
