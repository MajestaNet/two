# B11 — Questions, approvals, pause/resume/cancel

| Field | Value |
| --- | --- |
| ID | B11 |
| Phase | 5 — Durable workflow (human boundaries) |
| Status | planned |
| Depends on | B06, B07 |
| Blocks | B14 |
| Architecture | §8.3 items 8–9, §8.4, §15, §21 items 13–16 |

## Goal

Questions and approvals are durable rows, not chat prompts. The first
valid authorized response wins. Silence is never approval. Pause,
resume, and cancel are cooperative at safe boundaries. `awaiting_input`
releases the local inference slot (scheduler already knows; this item
writes the records and API).

## Current tree

- `src/devflow/approvals/` is a stub.
- Store tables for questions/approvals specified in B06.
- API stubs for decide/pause in B07.

## Out of scope

- Slack buttons (B14 maps to these APIs).
- Changing an action after approval (digest must not match).

## Implementation plan

1. **Question records**  
   task, stage, actor, reason, options, recommendation, timestamps,
   status (`open` / `answered` / `expired`).

2. **Approval records**  
   action class, affected paths or external target, **immutable**
   digest of the proposed action. Approving digest A must not
   authorize digest A' after a patch.

3. **Resolution**
   - First valid authorized principal wins; later duplicates ack and
     ignore (store uniqueness + API 200 with `ignored: true`).
   - Timeout policy from manifest/policy: pause indefinitely, block
     after deadline, or pre-authorized **safe** default. Never treat
     timeout as approve unless that default is an explicit non-side-
     effect (almost never; default is pause).

4. **Pause / resume / cancel**
   - Pause: safe boundary, retain all state, lifecycle `paused`.
   - Resume: only from paused/awaiting_input with answers applied as
     events; do not create a new task id.
   - Cancel: cooperative stop, grace, record partial outcome,
     lifecycle `cancelled`, retain worktree.

5. **Authorization**  
   For the API, define who may decide (env token / local user). Do
   not invent Slack allowlists here; leave a principal id string that
   B14 will fill.

6. **Tests**
   - Duplicate decide ignored.
   - Stale digest rejected.
   - Pause does not delete rows or worktree path.
   - Cancelled task cannot be resumed into `running` without an
     explicit new policy (spec: cancelled is terminal).

## Acceptance criteria

- [ ] Silence ≠ approval.
- [ ] Digest mismatch rejected.
- [ ] `awaiting_input` is persisted so B08 can release the slot.
- [ ] CLI/API can resolve questions without Slack.

## Definition of done

Approvals module + API paths tested. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **DevFlow backlog item B11 — Questions, approvals, pause/resume/cancel**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 8.3, 8.4, 15
3. `docs/backlog/README.md` and `docs/backlog/B11-questions-approvals.md`
4. `src/devflow/approvals/`
5. B06 tables and B07 routes. If missing, stop.

Implement **only B11**. Do not add a Slack adapter. Do not call the model.

Standing orders:

- Architecture wins. Silence never implies approval.
- `make ci` green. Offline tests.
- Approval is scoped to one task and one digest.
- Apache 2.0 headers. Raw message text is never interpolated into a shell.
- Do not merge/push/deploy.

Concrete work:

1. Durable question and approval records with immutable action digests.
2. First-writer-wins resolution; duplicate and stale digest tests.
3. Pause/resume/cancel transitions that retain worktrees and events.
4. Wire B07 endpoints if they were placeholders.
5. Mark B11 `done` when criteria pass.

Commit: `feat: add durable questions, approvals, and cooperative cancel`.

Done when: digest and duplicate tests pass, cancelled tasks stay terminal, `make ci` is green.
