# ADR 0041 — Closed approval words on the operator profile

## Status

Accepted. Amends ADR 0039. Does not change climate or television
approvals. Does not let a wearable resume `operator`.

## Context

ADR 0039 holds a binding write and a self-build task until an approval
digest matches. The local CLI posts that digest. Silence is not
approval. Architecture §15 also says broad conversational agreement is
not executable authorization.

The local operator window sends another `operator` transcript. Typing
`approved` there was stored as a new turn. The model then called
`install.status`. The pending write did not run.

## Decision

1. **A closed word list may apply the stored digest.** When
   `POST /v1/voice/turns` names `profile=operator`, and the transcript
   (trimmed, optional trailing `.` or `!`) is exactly `approve` or
   `approved`, the control plane posts the stored digest for the latest
   `awaiting_approval` operator turn from that principal. `reject` and
   `rejected` reject it. No new operator turn is inserted. The worker
   still performs the write after the turn is queued.
2. **Silence and other sentences stay a new turn.** `please approve`,
   `yes`, and an empty wait do nothing to the pending digest. The CLI
   digest route remains. The watch still cannot select `operator`.
3. **The digest is still the authority.** The chat word does not carry
   a digest. The control plane uses the digest already stored on that
   turn. A stale or missing pending turn is not invented.

## Consequences

- Architecture §5.4 and §15 record the closed word list.
- The console can type `approved` after a pending install summary.
- Climate and television approvals stay on their existing digest posts.
