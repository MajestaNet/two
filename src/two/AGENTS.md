# src/two

Python package for the Majesta Two control plane.

- Keep enums in `types.py` and the task request in `manifest.py`. No I/O in
  those modules. `projection.py` is the /v1 client contract (no I/O, no
  FastAPI). CLI and `channels.*` import it.
- `profiles.py` may read `config/inference/profiles.yaml`. No network.
- `topology.py` may read `config/deploy/topology.yaml`. No network.
- `runtime/` parses `models.lock`, emits the Ollama env contract, renders
  the launchd plist, and classifies Mac health from JSON. No network.
- `providers/` renders DSH settings from profile + topology + env and
  records the OpenAI-compatible HTTP contract. No network on the default
  path. Do not reimplement the DSH agent loop.
- `store/` is the SQLite WAL store (`open_store`). Do not open databases
  from `cli.py` at import time. The `two api` subcommand lazy-imports
  `two.api.server`.
- `client.py` is the stdlib HTTP/Unix client for `/v1` (urllib / http.client,
  including AF_UNIX). CLI task subcommands lazy-import it. Parse bodies with
  `two.projection`. Accept an injectable request callable for in-process
  TestClient tests. Do not import the store, git, Slack, or Ollama.
- `cli_task.py` formats projections and dispatches `two task …`. No workflow
  policy.
- `api/` maps HTTP to `two.store` and `two.approvals`. It must not import
  `two.workspace` git operations, `two.channels.slack`, or an Ollama
  client. Bind loopback or a Unix socket by default (ADR 0010). Request
  and projection bodies live in `two.projection`.
- `approvals/` owns question/approval resolution and pause/resume/cancel
  lifecycle policy. Silence is never approval. Digests are immutable.
  It does not import git, Slack, or the model.
- `scheduler/` owns the single local-model slot, lease reclaim, retry_wait,
  budgets clock, and Mac health mapping. Inject a health probe and worker
  callback; do not call the network or ACP from this package.
- `channels/*` adapters must not import `workspace` or run git. Slack is
  the MVP adapter only.
- `validation/` loads `config/repositories/*.yaml` and
  `config/policies/default.yaml`, then runs gates in the task worktree.
  It never writes task lifecycle.
- `reporting/` formats gate fragments and Stage 8 final reports. It does
  not set lifecycle.
- `context/` persists structured task memory as JSON under
  `TWO_DATA_DIR/tasks/<id>/memory.json` and builds bounded retrieval
  packets (git, `rg`, optional LSP). No embeddings, SQLite, or DSH/Ollama
  calls. Budget policy lives in `config/policies/context.yaml`.
- `controller/` owns workflow stages, repair/no-progress budgets, fresh
  review via `two.context.build_review_handoff` and `two.worker.plan_session`,
  and terminal status. Inject a worker and validation in tests. Production
  `two worker` drives this module (`two.recovery.drive`). It does not call
  the model, import Slack, or import an Ollama client.
- `worker/` supervises ACP children, the action ledger, and session resume.
  Default pytest uses a JSONL fixture child (ADR 0011). It must not import
  Slack or set lifecycle `complete`. Local Qwen worker count is one.
- `recovery/` owns architecture §12.5 startup recovery (`recover_startup`)
  and the `two scheduler` / `two worker` process loops. `run_worker` drives
  `WorkflowController` with `AcpPhaseWorker` and heartbeats the lease.
  It hooks `ActionLedger.recover` (no duplicate replay) and `Scheduler.start`
  (expired leases only). Human-paused tasks stay paused. Inject health
  and worktree probes in tests.
- `evals/` runs the architecture §18 corpus against `evals/` data.
  Offline by default. No Mac, Slack, production clones, or soak
  auto-pass. Duplicate side effects must stay zero.
- Use Pydantic v2 models with `extra="forbid"` for external payloads.
- `mypy --strict` applies to this tree. Add explicit return types.
- New `.py` files need the Apache 2.0 header and SPDX identifier.
