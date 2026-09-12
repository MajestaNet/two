# B19 — Persisted work graph around DeepSeek Harness

| Field | Value |
| --- | --- |
| ID | B19 |
| Phase | 5+ — Longer-running loops (alignment) |
| Status | done |
| Depends on | B05, B06, B09, B10 |
| Blocks | B14 Development-loop completeness only (B14 slices 1–3 may start now) |
| Architecture | §6.3.A/E/G, §7.2, §8.2–8.5, §10, ADR 0014 |

## Goal

Persist a work graph of nodes and typed edges so longer unattended
loops stay aligned across compaction, harness restart, and channel
handoff — **without** reimplementing DeepSeek Harness or replacing the
B10 stage machine.

The executable contract lives in `src/two/graph/` (types, invariants,
linear compile, proposal apply, walker, node handoff). This item stores
that graph in SQLite (schema **v5**), has the controller walk it, and
projects it on `/v1`.

## Current tree

- `two.graph` is the no-I/O contract ([ADR 0014](../adrs/0014-persisted-work-graph.md)).
- `WorkflowController` walks `next_decision` after Intake/Isolate.
- `TaskMemory.plan` / `current_step` summarize the cursor (B05).
- Store schema is **v5** (`work_nodes`, `work_edges`). v4 is B14
  `idempotency_records` and must not be reused.
- ACP worker + ledger ([B09](B09-acp-worker.md), ADR 0011).
- `TaskProjection.graph` is filled when a graph is stored; `null`
  until then. `schema_version` stays 1.

## Out of scope

- Reimplementing the DSH agent loop.
- LangGraph, Temporal, Prefect, or any new runtime orchestrator.
- Parallel local Qwen nodes / subagent fan-out.
- Manifest field changes; default profile/topology changes.
- Raising overnight ceilings.
- Slack, paid routes, GitHub export.
- HTTP checkpoint restore for clients.

## Implementation plan

Three slices. Slice 1 may land alone. Slice 3 must not ship without 1
and 2. This item landed all three together.

### Slice 1 — SQLite graph

- Schema v5: `work_nodes`, `work_edges` (plus `work_graphs` cursor/revision).
- `Store` load/commit for one task graph. Commit before ack.
- Events `task.graph`, `graph.node`, `graph.edge`.
- Compile `compile_linear_graph` for new tasks at isolate (or first
  drive) so old tests keep a 1:1 stage mapping.
- Tests: round-trip, cycle rejected at the store boundary, v3 and v4
  databases migrate to v5; B14 idempotency tables survive.

### Slice 2 — Walker in the controller

- After Plan, accept a `GraphProposal` from the phase worker (structured
  fields on `WorkerPhaseResult` or a JSON artifact). Invalid proposals
  fall back to the linear graph, they do not crash the task.
- `drive` uses `next_decision`. Validate nodes call B04, not ACP.
- Review nodes always `fresh_session` + `render_node_handoff`.
- `insert_repair` on gate failure; budgets still from policy YAML.
- Session id stored on the **node**. Per-node no-progress fingerprints.
- Tests: two-implement overnight fixture serializes; failed gates
  cannot `complete`; review-only still cannot write.

### Slice 3 — Projection, memory, recovery

- Fill `TaskProjection.graph` and derive `todos` from the graph.
- Task memory `plan` / `current_step` summarize the cursor.
- `recover_startup` reloads the graph and resumes the RUNNING node
  through the ledger (no duplicate tool replay).
- Optional CLI: include cursor + READY set in `two task show`. No new
  required subcommand.
- Offline eval: compaction/fresh-session case injects a graph slice,
  not a transcript.

## Acceptance criteria

- [x] Schema v5 round-trips a linear graph and a two-node proposal.
- [x] `depends_on` cycles never persist.
- [x] At most one RUNNING node per task.
- [x] Validate nodes do not start a harness child.
- [x] Review nodes start a fresh session with no implementation
      transcript.
- [x] Overnight task-level budgets still win over node slices.
- [x] `/v1` `graph` is additive; `schema_version` stays 1.
- [x] Controller still does not import Slack or Ollama clients.

## Definition of done

A fake two-slice overnight workflow: inspect, plan (proposal with two
implement nodes and a depends_on edge), serialize both, fail validate
once, repair, pass, fresh review, report. Status `complete` only after
gates. `make ci` green. This file and [README.md](README.md) marked
`done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B19 — Persisted work
graph around DeepSeek Harness**.

Read first:

1. `AGENTS.md`
2. `docs/adrs/0014-persisted-work-graph.md`
3. `docs/architecture.md` §6.3.A/E/G, §7.2, §8, §10, §12.5
4. `docs/work-graph.md`, `docs/backlog/README.md`, this file
5. `src/two/graph/`, `src/two/controller/`, `src/two/store/`,
   `src/two/worker/`, `src/two/projection.py`

Implement **only B19**. Do not add LangGraph or any new runtime
dependency. Do not reimplement the DSH loop. Do not raise overnight
ceilings. Do not change the default inference profile.

Standing orders:

- Architecture wins. ADR 0014 is the graph decision. The controller
  still owns terminal status. DSH owns the tool loop.
- Graph tables are schema **v5**. Never reuse version 4 (B14
  idempotency).
- `make ci` green. Unit tests stay offline.
- Apache 2.0 headers. No merge/push/deploy.

Concrete work:

1. SQLite v5 `work_nodes` / `work_edges` plus events.
2. Controller walks `next_decision`; validate is B04; review is fresh.
3. Project `graph` on `/v1`; keep `todos` as a view.
4. Recovery reloads the graph; no duplicate tool replay.
5. Tests listed in Acceptance criteria.
6. Mark this item `done` and update `docs/setup.md` when the worker
   actually walks a persisted graph.

Commit: `feat: persist and walk the task work graph`.

Done when: a two-slice fake overnight workflow stays aligned on nodes
and edges, cannot self-certify failed gates, and `make ci` is green.
