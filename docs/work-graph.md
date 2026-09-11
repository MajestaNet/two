# Work graph (longer-running loops)

The durable plan for a task is a **persisted graph of nodes and typed
edges**, walked one node at a time through DeepSeek Harness. Canonical
decision: [ADR 0014](adrs/0014-persisted-work-graph.md). Architecture
stage machine: [architecture.md](architecture.md) §8. Implementation
tracker: [B19](backlog/B19-persisted-work-graph.md).

This page does not copy the ADR. Pointers:

- Inner loop stays DeepSeek Harness (architecture §6.3.B, ADR 0011).
- Outer alignment is `two.graph` (no I/O in the contract package).
- SQLite persistence and controller wiring are B19.
- Clients read `TaskProjection.graph` (additive `/v1`; `null` until
  B19 fills it). `todos` remain a flattened view of implement /
  validate / repair / review nodes.
- Overnight still means larger *ceilings*, not an infinite loop
  ([unattended-operations.md](unattended-operations.md),
  [local-16k.md](local-16k.md)).

Do not add LangGraph, Temporal, or a second agent runtime. Do not run
two local Qwen nodes at once.
