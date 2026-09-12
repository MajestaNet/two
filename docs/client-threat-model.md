# Client API threat model (B14)

| Field | Value |
| --- | --- |
| Status | Implemented contract for B14 slices 1–2 |
| Authority | [Architecture §6.3.H](architecture.md), [§12.6](architecture.md), [§15](architecture.md), [ADR 0015](adrs/0015-first-party-client-api.md) |
| Design | [Client API design](client-api-design.md) |
| OIDC/TLS libraries | Not added. Selection is [ADR 0016](adrs/0016-oidc-jwt-tls-dependencies.md) and waits on review. |

This is the implementation threat model for a first-party client that reaches
Majesta Two over a private overlay. It is not a mobile-app source tree and it
does not authorize a public API bind.

## Trust boundaries

| Zone | What is trusted | What is not |
| --- | --- | --- |
| Development host (SQLite, API, scheduler, worker) | Operator-controlled process, local Unix/loopback callers | Request JSON, `principal`/`actor` fields, spoofed headers |
| Private overlay (Tailscale/WireGuard) | Network reachability to the API | Device integrity, lock-screen UI, stolen tokens |
| Shared `TWO_API_TOKEN` | One coarse trusted-operator credential for CLI/overlay | Multi-user authorization, a mobile embedding, per-device revocation |
| Future OIDC issuer (not wired) | Server-validated tokens (issuer, audience, expiry, signature, azp) | Client-supplied roles, custom app cryptography |
| Task worktree / Harness | Controller and DSH on the host | The phone, notifications, and client caches |
| Repository content | Untrusted input that may be malicious | A source of authority or a shell string |

The API never calls Qwen, Ollama, ACP, git, or a shell. DeepSeek Harness owns
the model/tool loop. Client disconnect does not pause or cancel work.

## Actors

- **Local operator** — Unix socket or loopback. Local-trust authentication.
  Body `principal`/`actor` labels are audit compatibility only; they do not
  grant scopes.
- **Remote operator with `TWO_API_TOKEN`** — transitional overlay CLI. The
  server derives `token:operator` and operator scopes. The token is not a
  mobile credential.
- **Future mobile principal** — OAuth 2.1 public client with PKCE. Out of
  scope until ADR 0016 dependencies are approved and a later slice validates
  tokens. Installations without a trusted issuer fail closed.
- **Unauthenticated network caller** — must receive `401`.
- **Authenticated caller missing a scope** — must receive `403`.
- **Lost, stolen, or shared device** — treat refresh material and caches as
  compromised. Slice 1 has no OIDC session table; the mitigation is “do not
  embed `TWO_API_TOKEN` in the app” plus overlay-only HTTPS.
- **Malicious repository content** — objectives, diffs, and logs may contain
  secrets or prompt-like text. Ordinary clients do not receive raw
  trajectories, unbounded command logs, or canonical host paths.

## Assets

- Task objectives, acceptance criteria, diffs, artifacts, and reports
- Approval digests and decision records
- Repository/project configuration (later slices)
- SQLite store and worktree paths
- `TWO_API_TOKEN` and future OIDC refresh credentials
- Correlation identifiers (not secrets; still avoid stuffing them with source)

## Threats and slice 1 controls

### Phone on an untrusted network

A device may be on coffee-shop Wi-Fi or a hostile LAN.

- **Required:** HTTPS over a private overlay. Public binds and public tunnels
  remain forbidden (`two.api.bind`).
- **Slice 1:** overlay TCP already requires a bearer; missing/invalid tokens
  are `401`. `/health` stays local liveness and is not a task oracle.
- **Later:** OIDC + TLS termination (ADR 0016). No Python JWT library is
  added in this slice.

### Lost or revoked devices

- **Do not** put `TWO_API_TOKEN` in the app, backups, or push payloads.
- Slice 1 records the server-derived principal on mutations so a later
  revocation log has an identity other than a client-chosen label.
- Per-device refresh revocation is an OIDC-session concern (later slice).

### Token theft

- The shared bearer is equivalent to full operator scopes. Treat theft as
  host compromise for CLI/overlay.
- Network request bodies cannot mint a different principal or add scopes.
- Idempotency keys are namespaced by the **server** principal, not a body
  `actor`.

### Principal and scope elevation

- Scopes are computed from the authentication method (`local_trust` or
  `bearer_token`).
- `principal`, `actor`, `admin`, and any client-supplied scope list are not
  authority. Extra body fields are rejected (`extra="forbid"`).
- Remote authenticated callers: body `principal`/`actor` is ignored for
  authority and audit identity.
- Local/Unix callers: body labels remain for CLI compatibility; scopes stay
  server-derived.

### Stale approvals and lost updates

- Approvals stay first-writer-wins and bound to the immutable action digest
  (B11). Silence is never approval.
- Mutable task resources expose a monotonic `revision` and `ETag`.
- Optional `If-Match` on mutations: mismatch is `412` `stale_revision`.
  Absent `If-Match` keeps B07/CLI behavior.
- Duplicate `Idempotency-Key` with the same principal and body replays the
  original result. A different body is `409` `idempotency_conflict`.

### Source leakage through notifications, caches, and errors

- Slice 2 adds conversation pagination, SSE controller summaries, aggregate
  health/queue, repository/project reads, and bounded diffs/artifacts.
  Those bodies must not include secrets, environment values, canonical
  paths, raw Harness output, or verbose command logs.
- Error bodies keep `error.code` plus optional `correlation_id`,
  `field_errors`, and `retry_after_seconds`. They must not echo secrets,
  environment values, canonical paths, or raw Harness output.
- `/v1/tasks/{id}/events` remains an operator route. Remote callers need
  `events:audit` and receive policy-filtered payloads. Unix/loopback CLI
  compatibility keeps current payloads.
- `TaskProjection.graph` is `null` until B19 persists a graph. Do not invent
  one.

### Malicious repository content

- User text is data. It is never interpolated into a shell command by this
  API.
- Config candidates (slice 3) must not accept secrets, arbitrary host paths,
  YAML blobs, or unrestricted command strings from an ordinary client.
  Candidates are immutable SQLite rows. Activation uses `If-Match`.
  Capability-expanding changes require `admin` and a digest-scoped approval.

## Fail-closed summary

| Condition | Result |
| --- | --- |
| Public API bind | Refused |
| Remote bind without `TWO_API_TOKEN` | Process refuses to start |
| Missing/invalid bearer on `/v1` | `401` `unauthorized` |
| Authenticated caller lacks route scope | `403` `forbidden` |
| No OIDC issuer configured | Mobile sign-in unavailable (later); CLI/Unix continue |
| Stale `If-Match` | `412` `stale_revision` |
| Idempotency key reused with a different body | `409` `idempotency_conflict` |
| Stale approval digest | `409` `stale_digest` (unchanged B11) |

## Explicit non-goals of this document

- Implementing OIDC, PKCE, or TLS libraries
- Building the native mobile app
- Native-client push/promotion (B14 slices 4–5)
- Persisting the work graph (B19; already a parallel item)
- Slack or any messenger adapter
