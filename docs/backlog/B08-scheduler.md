# B08 — Scheduler, single slot, and Mac health

| Field | Value |
| --- | --- |
| ID | B08 |
| Phase | 5 — Durable workflow (queue) |
| Status | planned |
| Depends on | B06; B01 health-check contract for Mac probes |
| Blocks | B09, B10 |
| Architecture | §6.3.G, §12.2–12.4, §21 items 11–12 |

## Goal

Own the single local-model execution slot: queue order, renewable
leases, heartbeats, `retry_wait`, releasing the slot on
`awaiting_input`, and Mac health states (Healthy/Cold/Busy/Degraded/
Unavailable). The scheduler does not run ACP and does not talk to
Slack.

## Current tree

- `src/two/scheduler/` is a stub.
- Execution profiles and budgets live in `config/policies/default.yaml`
  and `types.ExecutionProfile`.
- Health states are specified in architecture §12.3.

## Out of scope

- Supervising DSH children (B09).
- Stage transitions (B10).
- Automatic cloud failover (forbidden unless `cloud_allowed`, B16).

## Implementation plan

1. **Slot**  
   Worker count for the local Qwen route is **one**. A second running
   task must stay `queued`. `awaiting_input`, `paused`, `blocked`
   release the slot.

2. **Lease loop**
   - Dispatch: pick oldest eligible `queued` task, obtain lease,
     set `running`.
   - Heartbeat interval and expiry are configuration.
   - On process start, reclaim **expired** leases only (§12.5 step 2).

3. **Mac poller**
   - Call the B01 health classification (subprocess or shared Python
     port of the classifier). Map:
     - Healthy → accept work
     - Cold → wait/preload, do not fail the task
     - Busy → stay queued
     - Degraded → stop new work; finish or cancel current per spec
     - Unavailable → pause task, preserve state  
   - Timeouts: fast connect timeout; do not treat a long decode as
     dead without a separate stream-liveness rule (B09 owns streams).

4. **retry_wait**  
   Bounded exponential backoff for transient 429/503/connection
   failures. Cap retries. Persist next-attempt time.

5. **Budgets clock**  
   Record active-execution vs wall-clock. Exclude `awaiting_input`
   from active time. Do not enforce full workflow stop conditions
   here beyond “over active-time budget → signal controller” if B10
   is absent: persist a `budget_exceeded` event and pause.

6. **Tests**
   - Fake clock / fake health.
   - Two tasks: only one `running`.
   - Expired lease reclaimed; unexpired not.
   - Unavailable Mac → task `paused`, worktree fields untouched
     (worktree may be null if B03 unused).

## Acceptance criteria

- [ ] One local inference slot.
- [ ] Expired leases only are reclaimed.
- [ ] Human-paused and awaiting-input tasks are not auto-started.
- [ ] No Slack, no ACP in this module.

## Definition of done

Scheduler can be run in tests with a fake worker callback. Status
`done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B08 — Scheduler, single slot, and Mac health**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.G, 12.2, 12.3, 12.4, 12.5
3. `docs/backlog/README.md` and `docs/backlog/B08-scheduler.md`
4. `src/two/scheduler/`, `src/two/types.py`
5. B06 store + B01 health classifier if present. If B06 is missing, stop.

Implement **only B08**. Do not spawn DeepSeek Harness. Do not import Slack.

Standing orders:

- Architecture wins. Worker count for local Qwen is one.
- `make ci` green. Fake the Mac; no live network in unit tests.
- No new runtime dependency unless already added by B07's ADR.
- Apache 2.0 headers. Scheduler must not contain git worktree logic.
- No automatic cloud failover.

Concrete work:

1. Queue dispatch, lease obtain/heartbeat/reclaim-expired, single slot.
2. Health poller using B01 classification (injectable).
3. `retry_wait` backoff with a cap; persist next attempt.
4. Active vs wall-clock budget accounting; awaiting_input excluded from active time.
5. Tests with fake clock and two-task slot exclusion.
6. Mark B08 `done` when criteria pass.

Commit: `feat: add durable scheduler with single local-model slot`.

Done when: slot, lease, and health tests pass, `make ci` is green.
