# ADR 0014 — Persisted work graph around DeepSeek Harness

## Status

Accepted (direction). The executable contract lives in `two.graph`
(pure types, invariants, walker). Persistence, controller wiring, and
CLI/API population are [B19](../backlog/B19-persisted-work-graph.md).
This ADR does **not** replace [architecture.md](../architecture.md)
§8’s stage machine or reimplement the DeepSeek Harness agent loop.

## Context

Majesta Two already splits **inference** from **execution** and wraps
DeepSeek Harness (DSH) in a durable controller:

| Layer | Owner today | What it remembers |
| --- | --- | --- |
| Inner loop | DSH (ACP child, ADR 0011) | Transcript, tools, compaction, session id |
| Policy pipeline | `WorkflowController` (B10) | Intake → Isolate → Inspect → Plan → Implement → Validate → Repair → Review |
| Task memory | `two.context.TaskMemory` | A **string** `plan`, a `current_step`, file/test lists |
| Client todos | `/v1` latest `task.todos` event | A flat list with no edges |
| Durability | SQLite WAL + action ledger | Lifecycle, leases, events, at-most-once tools |

That stack is correct for a **single bounded change**. It is a poor
alignment substrate for **longer-running loops**:

1. **Overnight only raises ceilings.** `overnight` is 8 hours / 30
   turns / 6 repair cycles ([architecture.md](../architecture.md)
   §6.3.G). It is still one implement/validate/repair loop, not a
   decomposition of a larger work item.
2. **Plans die at compaction.** DSH has plan/todo/goal tools, but those
   live in the harness session. After compaction or a fresh session
   (§6.3.G, §7.2, §14) Majesta Two reinjects a prose `plan` string.
   There is no durable record of which steps finished, which depend on
   which, or which evidence belongs to which step.
3. **Todos have no connections.** `TodoItem` is a row. Clients cannot
   see “session store waits on cookie flags” versus “both are
   independently ready.” Humans and the model drift independently.
4. **The 16K window cannot hold the whole job.**
   [local-16k.md](../local-16k.md) already tells operators to queue
   *another task tomorrow*. That is honest, and it fragments one
   product outcome across many task ids, reports, and worktrees.
5. **Architecture forbids the obvious shortcuts.** Non-goals include
   an unbounded prompt loop as a substitute for a state machine, local
   subagent fan-out, and reimplementing the harness inside this repo
   (§3, §6.3.A, §10.2).

The product need is: keep DSH as the inner loop, and persist a **graph
of nodes and typed edges** so a multi-hour (or multi-slice) item stays
aligned across compaction, child crash, host restart, and channel
handoff.

### Options considered

| Id | Option | Verdict |
| --- | --- | --- |
| **1a** | Keep DeepSeek Harness as the inner model/tool loop | **Keep.** Architecture §6.3.B. Pin stays. ACP supervisor stays (ADR 0011). |
| 1b | Replace DSH with LangGraph / a custom agent runtime | Reject. Reimplements the harness. New runtime dependency. |
| 2a | Richer free-form plan string + more todos | Reject. Still no connections; still lost at compaction. |
| **2b** | Persisted directed graph (nodes + typed edges) in Majesta Two | **Take.** Outer alignment layer. SQLite, no new orchestrator. |
| 2c | Linear checklist only (todos without edges) | Reject as the *only* model. Keep as a projection of the graph. |
| 2d | Temporal / Prefect / LangGraph checkpointer as the job runner | Reject. Second control plane beside the controller, scheduler, and leases. |
| 2e | Parallel Qwen-backed graph nodes / subagents | Reject. One local-model slot (§6.3.G, §10.2). |

**Decision: 1a + 2b.** DSH executes one node at a time. Majesta Two
persists the graph and walks it.

## Decision

1. **Do not reimplement the harness.** Each graph node that needs a
   model is one `WorkerInstruction` into the existing ACP worker
   (resume the node’s session, or start fresh when the node kind
   requires it). Tool policy, sandbox, ledger, and leases stay where
   they are.

2. **The 8-stage machine remains policy, not the work breakdown.**
   Intake and isolate stay host-only and run once per task. Inspect,
   plan, implement, validate, repair, and review become **node kinds**.
   `task.stage` is derived from the cursor node. Terminal status is
   still written only by the controller after gates + review.

3. **The work graph is the durable plan.** Nodes have kind, status,
   bounded objective, acceptance criteria, write/fresh-session flags,
   and optional per-node turn slices. Edges are typed:
   `depends_on`, `repairs`, `reviews`, `supersedes`, `blocks`.
   `depends_on` is a DAG (`from_id` must finish before `to_id`).

4. **DSH may propose graph mutations; only the controller commits
   them.** Plan-stage structured output is `GraphProposal`. Invalid,
   cyclic, over-budget, or out-of-policy proposals do not land. The
   free-form plan string is a summary of the graph, not the source of
   truth.

5. **No new runtime orchestrator.** No LangGraph, Temporal, Prefect,
   or extra HTTP stack. Persistence is the existing SQLite WAL store
   (schema v4 in B19). The executable contract is `two.graph` (no I/O).

6. **Longer loops are more nodes, not an infinite inner loop.**
   Task-level budgets in `config/policies/default.yaml` still win.
   Node-count caps: 12 (`standard`), 32 (`overnight`). Per-node turn
   slices: 2 / 4. Repair still inserts bounded repair nodes; it does
   not cycle `depends_on`. Silence is still never approval.

7. **Alignment packet is a graph slice, not the transcript.** After
   compaction or a fresh session, the worker prompt is
   `render_node_handoff`: current node, completed predecessor
   summaries, dependents. No implementation conversation. Fresh review
   nodes always set `fresh_session`.

8. **`/v1` stays additive.** `TaskProjection.graph` is optional
   (`null` until B19 persists a graph). `schema_version` remains `1`.
   Existing `todos` become a view of implement/validate/repair/review
   nodes. Breaking changes still need `/v2`.

## Design

### Layering

```mermaid
flowchart TB
    clients["CLI / optional web / optional adapter"] --> api["Control API /v1"]
    api --> proj["TaskProjection + GraphView"]
    api --> ctrl["WorkflowController"]
    ctrl --> graph["two.graph walker"]
    ctrl --> mem["Structured task memory"]
    graph -->|"one ready node"| worker["ACP worker"]
    worker -->|"inner loop"| dsh["DeepSeek Harness"]
    dsh -->|"OpenAI-compatible"| qwen["Mac Qwen"]
    ctrl --> store["SQLite WAL"]
    graph -.->|"commit nodes/edges"| store
    worker -.->|"action ledger / session id"| store
```

The scheduler still owns the single local-model slot. The graph never
dispatches two RUNNING nodes.

### Node kinds

| Kind | Uses DSH? | Writes worktree? | Fresh session? |
| --- | --- | --- | --- |
| `inspect` | Yes | No | Resume allowed |
| `plan` | Yes | No | Resume allowed |
| `implement` | Yes | Yes | Resume allowed on the same node |
| `validate` | **No** — B04 gates | No | n/a |
| `repair` | Yes | Yes | Resume allowed on the same node |
| `review` | Yes | No | **Always** |
| `decision` | No | No | n/a (awaiting_input) |

Validate nodes never start a model session. That preserves
“the model cannot self-certify” (§8.2 Stage 6–8).

### Edge kinds

- `depends_on`: predecessor `from_id` must be `done` / `skipped` /
  `superseded` before `to_id` is READY.
- `repairs`: repair node points at the validate attempt it answers.
  Implemented as **new nodes**, not a `depends_on` cycle.
- `reviews`: review node points at the change set it judges.
- `supersedes`: a later plan revision retires placeholder linear nodes.
- `blocks`: human/policy gate; the target cannot run.

### Walker

`next_decision(graph)` is a pure function:

1. Normalize PENDING/READY from topology.
2. If a node is RUNNING, continue it (crash recovery uses the ledger).
3. If a node is `awaiting_input`, release the slot (existing B11).
4. Otherwise pick one READY node. Host-only validate nodes win over
   model nodes so gates run before another implement turn. Tie-break
   is node id.
5. If nothing is READY and any node is BLOCKED → task `blocked`.
6. If every node is terminal → `graph_satisfied`; the controller then
   applies Stage 8 completion policy (gates passed, no blocking
   review finding).

The linear pipeline is `compile_linear_graph`: inspect → plan →
implement → validate → review. That is today’s B10 drive, expressed as
a DAG, so existing fixture workflows stay representable.

Longer work items call `apply_proposal` after Plan: placeholder
implement/validate/review nodes are `superseded`, and the committed
subgraph can contain several implement nodes with explicit
`depends_on` edges. Missing validate/review nodes are inserted by the
controller, not left to the model.

### Harness contract (1a)

For a RUN_NODE decision with `uses_harness=true`:

- Build `WorkerInstruction` from the node (effort from §7.1 by kind).
- Prompt = `render_node_handoff` plus the existing objective /
  acceptance criteria. Still no transcript on review nodes.
- `session_id` is stored **on the node**, not only on `tasks`. A later
  node does not silently resume a previous node’s conversation.
- Tool requests still go through the action ledger (at-most-once).
- DSH plan/todo tools are *hints*. If the child emits a todo list,
  B19 may parse it into a `GraphProposal`; it is not committed until
  `validate_graph` succeeds.
- Ralph remains an optional per-node repair ceiling of three rounds
  (§10.2). Ralph cannot mark the task complete.

### Persistence (B19)

Schema version 4 (names are indicative):

```text
work_nodes (id, task_id, kind, status, title, objective,
            acceptance_json, allow_writes, fresh_session,
            max_model_turns, summary, session_id,
            evidence_fingerprint, files_json, tests_json,
            created_at, updated_at)
work_edges (id, task_id, kind, from_id, to_id)
```

Events: `task.graph`, `graph.node`, `graph.edge`, `graph.walk`.
A successful commit is required before the next walker step, the same
ack-after-persist rule as task intake.

JSON task memory keeps a **summary** (`plan`, `current_step` = cursor
title). It does not become a second graph store.

### Human and model alignment

Clients project `GraphView` (nodes, edges, cursor, revision). CLI
`two task show` can print the cursor and READY set without a new
subcommand in this ADR; B19 may add `two task graph ID`.

Interactive plan approval digests the graph **shape**
(`graph_digest`): ids, kinds, titles, objectives, files, tests, edges.
Summaries, session ids, and evidence fingerprints are omitted so a
running walker does not invalidate digest A. Approving A never
authorizes revision A'.

### Budgets

| Cap | `standard` | `overnight` |
| --- | ---: | ---: |
| Task active time / turns / repairs | 90 min / 8 / 3 | 480 min / 30 / 6 |
| Graph node count | 12 | 32 |
| Turns per model node | 2 | 4 |

No-progress still uses evidence fingerprints, now **per node**. Two
consecutive attempts on the same node with an unchanged fingerprint
stop that node (then fresh review or block), instead of burning the
whole overnight budget on one stuck slice.

The controller must not silently extend any ceiling. A larger job is
more nodes inside the task budget, or a follow-up task with a new
worktree — not a hidden profile.

### Recovery

Startup recovery (§12.5) gains one step: reload the graph, reclaim the
lease, reconcile the RUNNING node’s last action, then `next_decision`.
A missing graph on a pre-B19 task is compiled with
`compile_linear_graph` from the current stage so old rows keep working.

## Consequences

- Longer unattended work can stay one task id, one worktree, one
  conversation, while the model only sees the current node slice.
  That is the 16K-compatible way to run loops that last hours without
  pretending the window holds the whole repository.
- Operators see *why* a slice is waiting (edges), not only *that* a
  todo is pending.
- Implementation is explicitly **not** a second architecture: B10
  remains the policy driver; B09 remains the harness supervisor; B05
  remains retrieval. B19 stores and walks the graph.
- DSH upgrades still cannot rewrite workflow policy. If ACP grows a
  native workflow API, Majesta Two may *project* it into this graph;
  it must not take the graph as an ephemeral child-only structure.
- Next free ADR after this file is **0015** (Slack SDK, GitHub SDK, or
  a new HTTP framework — still ask first).

## Non-goals (this ADR)

- Parallel local Qwen nodes or subagent fan-out.
- A vector database of nodes.
- LangGraph / Temporal / Prefect as a dependency.
- Replacing SQLite.
- Manifest field changes (the graph is produced at Plan, not submitted
  as a required manifest DAG).
- Changing the default inference profile or topology.
- Raising overnight ceilings.
- Checkpoint HTTP for clients (restore stays internal).
- GitHub export (ADR 0012) or Slack (B14).
