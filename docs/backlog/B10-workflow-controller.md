# B10 — Workflow controller, budgets, review, reports

| Field | Value |
| --- | --- |
| ID | B10 |
| Phase | 5 — Durable workflow (policy) |
| Status | done |
| Depends on | B04, B05, B07, B08, B09 |
| Blocks | B12, B15, B16, B17 |
| Architecture | §6.3.A, §7.1, §8, §9, §21 items 5–8, 11 |

## Goal

Drive the durable workflow: Intake → Isolate → Inspect → Plan →
Implement → Validate → Repair → Review → Complete/Blocked. The
controller does not call the model. It selects reasoning effort by
phase, enforces budgets, requires progress between repairs, starts a
**fresh** review session, and is the only writer of terminal status.
Independent validation (B04) is authoritative.

## Current tree

- `src/two/controller/` drives stages, budgets, fresh review, and terminal status.
- Enums for stages and lifecycle exist.
- Manifest, policies, store, API, worker, and approvals exist.

## Out of scope

- Slack (B14).
- Paid routing (B16) except honoring `cloud_allowed: false` (never
  escalate).
- Merge/push/deploy.
- Infinite loops; overnight profile is larger ceilings, not infinity.

## Implementation plan

1. **Intake**
   - Validate manifest fields (`TaskManifest`).
   - Classify analysis-only vs code change vs dependency/migration/
     infra/external side effects. Refuse or require approval classes
     from `config/policies/default.yaml`.
   - Bind budgets from `execution_profile` unless the manifest
     overrides.
   - Persist then ack (already B07); controller fills stage
     `intake` → `isolate`.

2. **Isolate** — call B03; record base commit.

3. **Inspect / Plan / Implement**  
   Instruct the worker with phase-specific effort (§7.1):
   - triage: low
   - plan: medium
   - implement: medium
   - test diagnosis: medium
   - fresh review: high
   - mechanical: off/low  
   Plans must name files, tests, assumptions. `interactive` may wait
   for plan approval (B11). `workspace-auto` / `unattended` continue
   only inside policy.

4. **Validate / Repair**
   - Run B04 gates. Model claims are ignored.
   - Bounded repair cycles (`standard` 3, `overnight` 6).
   - No-progress: two consecutive attempts with no evidence change →
     stop (fresh review then block).
   - Overnight may not silently extend ceilings.

5. **Fresh review**
   New DSH session (B09 fresh handoff): task, acceptance criteria,
   final diff, tests, structured memory. No implementation transcript.
   Blocking findings → repair if budget remains.

6. **Completion**
   Controller sets `complete` only if required gates passed **and**
   review has no blocking finding. Else `blocked` / `failed` /
   `cancelled` per spec. Assemble report via `reporting/`:
   branch, commits, files, acceptance disposition, commands, reviewer
   findings, risks, trajectory refs, usage metrics.

7. **Modes** (§9)  
   `review-only` must not write the worktree. Enforce.

8. **Tests**
   - Fake worker + fake validation.
   - Cannot complete when validation failed.
   - Repair budget exhausted → `blocked`.
   - Review-only mode rejects writes.
   - Overnight ceilings loaded from policy YAML.
   - Parse architecture §8.1 YAML still works.

## Acceptance criteria

- [x] All eight stages exist as `WorkflowStage` transitions with events.
- [x] Validation failure cannot yield `complete`.
- [x] Fresh review uses no implementation transcript.
- [x] Budgets and no-progress limits enforced.
- [x] Controller does not import Slack or Ollama clients.

## Definition of done

End-to-end fixture bug-fix with fakes: isolate, fake implement, fail
once, repair, pass, review, report. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B10 — Workflow controller, budgets, review, reports**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.A, 7.1, 8, 9, 21
3. `docs/interaction-contract.md`, `docs/unattended-operations.md`
4. `docs/backlog/README.md` and `docs/backlog/B10-workflow-controller.md`
5. `src/two/controller/`, `src/two/reporting/`, `src/two/types.py`, `src/two/manifest.py`
6. Confirm B04, B05, B07, B08, B09 exist. If not, stop.

Implement **only B10**. Do not add Slack or paid providers. Do not call the model from the controller.

Standing orders:

- Architecture wins. The controller decides continue/retry/ask/stop; DSH owns the tool loop.
- `make ci` green. Fake the worker and validation in unit tests.
- Completion authority is the controller + B04 results, never a model self-report.
- Apache 2.0 headers. No merge/push/deploy.
- `cloud_allowed: false` must not escalate.

Concrete work:

1. Stage machine with events for each transition.
2. Phase-specific reasoning effort passed into the worker.
3. Repair/no-progress/budget enforcement from `config/policies/default.yaml` and manifest overrides.
4. Fresh review handoff using B05 memory + diff + B04 evidence.
5. Final report assembly in `reporting/`. Terminal status only from the controller.
6. Tests: no complete on failed gates; review-only has no writes; budget exhaustion blocks.
7. Mark B10 `done` when criteria pass. Update `docs/setup.md` if the product can now run a fake unattended fixture.

Commit: `feat: add durable workflow controller and final reports`.

Done when: fake bug-fix workflow cannot self-certify a failed test, reports are generated, `make ci` is green.
