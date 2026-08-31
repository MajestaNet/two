# ADR 0011 — JSONL supervisor protocol until DSH ACP is wired

## Status

Accepted

## Context

Architecture §10 and backlog B09 require Majesta Two to supervise DeepSeek
Harness through ACP, not to reimplement the agent loop. Real DSH ACP is
JSON-RPC over stdio (`initialize`, `session/new`, `session/prompt`, …).

Phase 5 shipped `two.worker` against a **test fixture protocol**: newline
JSON objects (`heartbeat`, `session`, `tool_request`, `execute`,
`tool_result`, `cancel`). `build_dsh_argv` currently emits
`dsh acp --task-id …`, which the pinned Harness release does not speak.
Default pytest uses `tests/unit/fixtures/acp/fake_acp_child.py`.

Rewriting `docs/architecture.md` to match the fixture would hide the gap.
Implementing a full JSON-RPC ACP client is a follow-up once the pin’s ACP
surface is contract-tested.

## Decision

1. Keep the JSONL supervisor as the **offline / fake-child** control plane
   used by unit tests and `make ci`.
2. Document that production ACP is **not** the invented CLI. Operators who
   inject a child (`TWO_ACP_ARGV` / `AcpWorker(argv=…)`) must speak the
   JSONL fixture dialect or wrap DSH themselves.
3. Do not treat a model or child self-report as task completion. The
   workflow controller remains the only writer of `complete`.
4. A later item may replace JSONL with a real ACP client without changing
   the action ledger, lease, or stage machine.

## Consequences

- Unattended Compose can drive stages through `WorkflowController` with an
  injected PhaseWorker. A stock `dsh` binary will not satisfy the fixture
  protocol until an ACP adapter lands.
- Live DSH evaluation stays behind explicit env flags (`TWO_LIVE_EVAL`,
  `live_dsh`).
- This ADR does not authorize reimplementing the Harness agent loop.
