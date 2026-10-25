# ADR 0033 — Console voice profile

## Status

Accepted. Amends ADR 0031 decision 5.

## Context

The window always posted `profile: chat`. A transcript such as "turn
the heat on" then reached the no-tools chat profile. The utterance
router in ADR 0030 runs only when `profile` is omitted. The local
operator at this Mac already has climate and television bindings.

`self-build` stays off this window. A profile picker must not become
a way to submit a coding task.

## Decision

1. **The Chat box defaults to an unset profile.** The posted body is
   `{ "text": "..." }` with no `profile` field. The control API routes
   that transcript (ADR 0030).
2. **The operator may set `chat` or `home-action`.** Those are the only
   explicit values. `self-build` is refused in the window before the
   request is sent.
3. **The catalog `console` slot stays limited to `chat`.** This choice
   is the local operator window, not a resumed device client.

## Consequences

- Architecture §20 phase 6 follows this ADR for the window's voice turn.
  ADR 0030 still owns routing. ADR 0031 still owns the renderer boundary.
- `npm test` in `apps/console` checks the omitted profile and the refusal
  of `self-build`. It stays off `make ci`.

## Alternatives rejected

- **Leave the box on `chat`.** The router never sees the transcript.
- **Offer `self-build` in the list.** That submits a coding task from
  the chat box.
