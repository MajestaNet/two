# B09 — ACP worker, action ledger, reconciliation

| Field | Value |
| --- | --- |
| ID | B09 |
| Phase | 5 — Durable workflow (execution) |
| Status | done |
| Depends on | B02, B03, B06, B08 |
| Blocks | B10, B12 |
| Architecture | §6.3.G, §10, §12.4–12.5, §14, §21 items 3, 6, 12 |

## Goal

Supervise a DeepSeek Harness ACP child per running task: heartbeats,
bounded cancellation, session resume, an action ledger written **before**
tool execution, and **at-most-once** automatic replay. Majesta Two owns
task lifetime; DSH does not.

## Current tree

- `src/two/worker/` supervises a fake or pinned ACP child, records the
  action ledger before tool execution, and reconciles unknown outcomes.
- Schema v3 adds `tasks.dsh_session_id` for session resume.
- Default pytest uses `tests/unit/fixtures/acp/fake_acp_child.py`.

## Out of scope

- Workflow stage policy and fresh review (B10).
- Completing a task because the model said so.
- Local subagent fan-out (concurrency stays 1).
- Ralph workflow beyond documenting a later ceiling of three rounds
  (architecture §10.2) — optional stub, not required to close B09.

## Implementation plan

1. **ACP supervisor**
   - Launch/attach DSH ACP with task id, workspace path (B03),
     pinned provider config (B02).
   - Treat the child as supervised: health heartbeats, grace period
     on cancel, then terminate. Never delete the worktree on kill.
   - Closing a CLI/browser must not kill a controller-owned child
     (the worker process is long-lived, B12).

2. **Action ledger** (store `actions` from B06)
   - Before a tool action: persist `action_id`, intent, status
     `recorded`.
   - After: exit status, truncated output, diff fingerprint, status
     `executed`.
   - If crash between execute and persist: status `reconcile`.
     Inspect worktree + evidence. **Never** blindly re-issue.

3. **Session resume**
   - If DSH session id is valid, resume.
   - Else start fresh from objective, acceptance criteria, structured
     memory (B05 if present; else objective only), current diff,
     validation evidence. Same task id.

4. **Stream vs turn timeouts**
   - Fast connect timeout to the Mac.
   - Long total inference timeout.
   - Stream liveness ≠ total turn duration (slow reasoning is not a
     dead child).

5. **Tool-call repair**  
   Invalid tool JSON: one schema repair, then fresh model turn, then
   escalate (event + block signal). Repeated identical tool calls:
   stop.

6. **Tests**
   - Fake ACP child process (script that prints heartbeats / exits).
   - Intent persisted before fake tool runs.
   - Kill between execute and result → reconcile path, no second
     invoke of the same action_id.
   - Cancel during a long fake command: cooperative then grace kill;
     worktree retained.
   - Default pytest: no real DSH binary required. Optional
     `@pytest.mark.live_dsh`.

## Acceptance criteria

- [x] Worker count 1 for local Qwen.
- [x] At-most-once automatic replay proven in tests.
- [x] Worktree never auto-discarded on cancel/crash.
- [x] Task identity preserved across child restart.
- [x] Worker does not import Slack or set `complete`.

## Definition of done

Fake-ACP tests cover ledger + reconcile. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B09 — ACP worker, action ledger, reconciliation**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.G, 10, 12.4, 12.5, 14
3. `docs/unattended-operations.md`
4. `docs/backlog/README.md` and `docs/backlog/B09-acp-worker.md`
5. `src/two/worker/`
6. Confirm B02 pin notes, B03 workspace, B06 actions table, B08 slot. If any are missing, stop.

Implement **only B09**. Do not implement workflow stages, Slack, or completion certification.

Standing orders:

- Architecture wins. Do not reimplement the DSH agent loop; supervise ACP.
- `make ci` green without a live Mac or DSH by default (fake child).
- Local Qwen concurrency 1. Workspace-write sandbox remains DSH's; still never run tools against the canonical checkout.
- Apache 2.0 headers. At-most-once: never replay an action with unknown outcome.
- Do not merge/push/deploy. Do not bind public ports.

Concrete work:

1. ACP supervisor with heartbeats, cancel + grace, session id persistence.
2. Action ledger: record intent, then execute, then result; reconcile on gap.
3. Resume vs fresh structured handoff with the same task id.
4. Tests with a fake child covering crash-before-result and cancellation.
5. Mark B09 `done` when criteria pass.

Commit: `feat: supervise ACP workers with at-most-once action replay`.

Done when: reconcile tests prove no duplicate fake tool invocation, `make ci` is green.
