# B14 — Secure first-party mobile client

| Field | Value |
| --- | --- |
| ID | B14 |
| Phase | 6 — First-party conversational control |
| Status | planned |
| Depends on | B07, B11 (B19 only for a populated graph view) |
| Blocks | Architecture §21 items 14–17 |
| Architecture | §6.3.H, §8.3–8.5, §12.6, §15, ADR 0015 |
| Design | [Client API design](../client-api-design.md) |

## Goal

Deliver a secure first-party native mobile client for conversation,
repository/project configuration, persisted-graph monitoring, evidence,
approvals, and system health. The app talks only to the Majesta Two control
API. Closing it never changes task execution.

This is intentionally more than a messenger adapter. It requires additive
backend client resources and a separate native app. Implement it in slices;
do not attempt the entire item in one PR.

## Current tree

- B07 `/v1` tasks, events, messages, controls, approvals, report, and shallow
  API/store health are implemented.
- B13 CLI consumes `two.projection`; no web UI was added.
- `TaskProjection.graph` already exists and may be `null`. B19 persists and
  walks the graph. Do **not** stop B14 because B19 is still planned. Slices 1–3
  and conversation/health/config work against the existing projection; the
  Development-loop view shows an empty/linear graph until B19 fills it.
- Remote API bind supports a shared bearer token. That token is not suitable
  for embedding in a mobile app. It is coarse authentication only: current
  network callers can supply `principal`/`actor` labels, and `/events` has no
  separate audit scope. Treat it as one trusted operator credential until
  Slice 1 lands.
- Repository profiles exist as host configuration, but there are no
  repository/project API resources or project store.
- There is no client-safe conversation feed, SSE change stream, aggregate
  system health projection, OIDC identity, or scoped authorization.
- Slack stubs may remain for compatibility, but Slack implementation is not
  part of B14.

## Required delivery slices

### Slice 1 — Threat model and contract foundations

- Write the implementation threat model for a phone on an untrusted network,
  lost/revoked devices, token theft, malicious repository content, stale
  approvals, and source leakage through notifications/caches.
- Add capability discovery, authenticated principal/scopes, idempotency keys,
  resource revisions/ETags, and consistent errors from the design.
- Select OIDC/JWT libraries and any TLS termination component in a focused
  ADR before adding runtime dependencies.
- Keep Unix/loopback CLI compatibility. Require HTTPS on a private overlay
  for mobile; refuse a public bind.
- Derive actor identity server-side. Network request bodies cannot assert
  their own principal.

### Slice 2 — Read-only GUI projections

- Add client-safe conversation pagination.
- Add task and system SSE streams with durable cursors and reconnect/reset
  behavior. Stream controller summaries, not model tokens.
- Add aggregate component health, capability discovery, and queue summary.
- Add bounded diff/artifact metadata and policy-filtered retrieval.
- Add repository and project read projections with sensitive host fields
  suppressed by default.
- Exercise snapshots plus reconnect in offline contract tests.

### Slice 3 — Typed repository and project configuration

- Persist project records and revisioned repository/project config
  candidates in the backend store.
- Validate immutable candidates; return a redacted diff, errors, risk class,
  and digest before activation.
- Use `If-Match` for activation. Capability-expanding changes require
  `config:write`, `admin`, and a digest-scoped approval according to policy.
- Never accept secrets, arbitrary host paths, YAML blobs, or shell strings
  from an ordinary client.
- Do not add a required task-manifest field. Any optional project association
  requires its own reviewed schema change.

### Slice 4 — Native mobile client

- Build the first-party native app in its designated repository. It is an
  OAuth 2.1 public client using Authorization Code with PKCE and an
  operator-configured OIDC issuer; no embedded client secret or shared
  `TWO_API_TOKEN`.
- Store rotating refresh credentials only in platform secure storage with
  device-unlock protection. Support sign-out and server-side revocation.
- Implement Projects, Task conversation, Development loop, Evidence, and
  System views from API snapshots plus SSE.
- Show the persisted graph and dependency reasons directly. Do not derive
  workflow state from chat text.
- Require foreground presence, fresh state, and any configured step-up
  authentication for approvals and sensitive config activation.
- Use an encrypted, bounded cache and clear source-bearing data on sign-out
  or revocation.

### Slice 5 — Minimal private notifications and promotion

- Make push optional. Notification providers receive only opaque task id and
  coarse event class; the app fetches details after unlock.
- Add mobile/API compatibility tests, lost-device revocation, stale cursor,
  stale ETag, idempotent retry, stale approval digest, lock-screen
  disclosure, and background-disconnect tests.
- Complete a no-terminal workflow over the private overlay: create, inspect,
  message, answer, pause, resume, cancel, approve, and read the final report.
- Run a dedicated security review before promotion.

## Out of scope

- A public Majesta Two endpoint or public tunnel.
- Direct mobile access to Ollama, DeepSeek Harness, shell, git, SQLite, or
  worktree paths.
- Raw model reasoning, token streaming, full trajectories, or unbounded logs.
- Embedding credentials, environment values, source-control tokens, or an
  OIDC client secret in the app.
- Offline approvals, background task creation, or notification-tap approval.
- Reimplementing the DSH loop, graph walker, workflow policy, or state store
  in the client.
- Slack, Matrix, Discord, or another vendor adapter.

## Acceptance criteria

- [ ] API/CLI continue to work without a mobile client or OIDC issuer.
- [ ] Mobile access is HTTPS over a private overlay and fails closed without
      trusted authentication.
- [ ] Principal and scopes are server-derived; unauthorized identities cannot
      read source or control tasks.
- [ ] Snapshots plus SSE reconstruct conversation, graph, validation, and
      health after disconnect without token streaming.
- [ ] Repository/project edits are typed, revisioned, validated, auditable,
      and digest-scoped where approval is required.
- [ ] Duplicate mutation retries do not double-apply; stale ETags and stale
      approval digests fail.
- [ ] Push, lock-screen UI, caches, and client logs do not disclose source,
      objectives, approval details, secrets, or raw host paths.
- [ ] The app contains no shared API token, client secret, model endpoint,
      shell, git, or workflow policy.
- [ ] Lost-device revocation prevents refresh and clears client cache on the
      next app activation.
- [ ] Bounded no-terminal workflow and security-review gates pass.

## Definition of done

All five slices are implemented and independently tested, the mobile client
passes the private-overlay workflow and security review, and the backlog
status is `done`. Backend-only slices may land earlier without claiming that
the mobile client exists.

---

## Agentic prompt

Do not paste this entire item into one coding session. Choose exactly one
unfinished slice, state it in the PR, and read:

1. `AGENTS.md` and the relevant directory `AGENTS.md`
2. `docs/architecture.md` §6.3.H, §8.3–8.5, §12.6, §15
3. `docs/client-api-design.md` and ADR 0015
4. B07, B11, and this item
5. Existing `two.projection`, `two.api`, `two.client`, and store contracts

B19 is **not** a start gate. If the graph is still `null`, project that
honestly and continue. Do not implement B19 in a B14 PR. Do not wait for
SQLite graph persistence before adding capabilities, auth, conversation,
SSE, health, or repository/project resources.

Keep `/v1` additive, use `two.projection` for public backend types, keep unit
tests offline, and leave `make ci` green. Do not expose a public port, invent
custom mobile cryptography, accept client-selected principals, or implement a
second agent loop. New runtime dependencies require a focused ADR and review.
