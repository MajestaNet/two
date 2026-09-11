# ADR 0015 — First-party client API and secure mobile direction

## Status

Accepted (design direction; implementation is [B14](../backlog/B14-secure-mobile-client.md))

## Context

[ADR 0007](0007-backend-first-channels.md) correctly made Majesta Two a
backend instead of a Slack product, but selected Slack as the first optional
client. The durable task API, approvals, CLI, and work-graph contract now
exist. The more valuable next surface is a first-party GUI that can show the
development loop directly: conversation, repository/project configuration,
persisted graph, validation evidence, and system health.

The current `/v1` API is sufficient for the CLI but not for that GUI. It has
no repository or project resources, aggregate health projection, safe
client-facing conversation, resumable change stream, mobile identity, or
fine-grained authorization. Copying the shared API bearer token into a phone
would also be an unacceptable credential model.

## Decision

1. Keep Majesta Two as the channel-neutral backend. The CLI remains
   supported, and every GUI uses the same controller resources.
2. Make a secure, first-party native mobile client the planned B14 client.
   Its source may live in a separate first-party repository; this backend
   owns the protocol and authorization contract.
3. Extend `/v1` additively for client-safe conversation, repository/project
   configuration, persisted-graph monitoring, bounded evidence, aggregate
   system health, capability discovery, and resumable server-sent events.
   [The client API design](../client-api-design.md) defines that contract.
4. Keep loopback/Unix as the default bind. Mobile access requires HTTPS over
   a private overlay and authenticated authorization. It does not authorize a
   public API endpoint.
5. Use standard OAuth 2.1 Authorization Code with PKCE and an
   operator-configured OIDC issuer for the native app. The app is a public
   client with no embedded secret. The existing shared bearer token remains
   a transitional trusted CLI mechanism and is not a mobile credential.
6. Derive principal and scopes from authentication. Client-supplied
   `principal`/`actor` fields cannot establish authority for network clients.
   Approvals remain first-writer-wins and bound to an immutable action
   digest.
7. Represent configuration edits as validated immutable candidates with
   optimistic concurrency and activation policy. A client never edits host
   YAML, sends secret values, or supplies arbitrary filesystem paths.
8. Stream durable controller summaries, not model tokens or raw Harness
   trajectories. Client disconnect remains independent from task lifetime.
9. Defer Slack. It may later be implemented as an optional adapter over the
   same API, but it is no longer the MVP client and has no committed backlog
   slot.

This decision supersedes ADR 0007 only where it names Slack as the MVP
adapter and places first-party client UX out of scope. ADR 0007's
backend-first boundary and thin-adapter rules remain accepted.

## Consequences

- B14 is renamed and redesigned around API readiness plus a separately built
  first-party mobile app.
- B07 remains the frozen implemented baseline. Proposed resources are not
  marked implemented, and breaking changes still require `/v2`.
- The graph is the GUI's plan/progress source of truth. Chat prose is not a
  second workflow state.
- Remote mobile access requires a private overlay and trusted OIDC setup.
  Installations without it fail closed and continue to support local CLI.
- Fine-grained auth, SSE, configuration persistence, and a native client add
  meaningful implementation and threat-model work; they must land in
  reviewable slices rather than one adapter patch.
- No OIDC library, reverse proxy, mobile framework, or push provider is
  selected by this documentation change. Runtime dependencies still require
  review when implementation begins.

## Alternatives rejected

- **Keep Slack first.** It offers convenient phone notifications but cannot
  provide the intended graph, config, evidence, and health experience without
  turning vendor messages into a poor GUI.
- **Embed the shared bearer token in the app.** A long-lived, broadly
  privileged secret is difficult to revoke per device and unsafe in mobile
  storage or backups.
- **Expose the API publicly behind a tunnel.** This expands the attack
  surface and conflicts with the private-overlay architecture.
- **Let the app call Harness or Ollama.** That forks policy, bypasses durable
  state, and violates the execution boundary.
- **Create a second chat service.** A review-only or interactive task already
  provides a durable conversation; another model loop would fragment task
  identity and memory.
