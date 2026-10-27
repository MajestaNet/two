# src/two

Python package for the Majesta Two control plane.

- Keep enums in `types.py` and the task request in `manifest.py`. No I/O in
  those modules. `projection.py` is the /v1 client contract (no I/O, no
  FastAPI). CLI and `channels.*` import it.
- `profiles.py` may read `config/inference/profiles.yaml`. No network.
  `recommend_profile` scores that catalog against a memory size. It does
  not probe the host. `two profiles --recommend` does the probe. 16 GB
  recommends `m16-qwen35-4b`. The repository default stays 24 GB.
- `adapters.py` may read `config/adapters/catalog.yaml` (ADR 0021). No
  network, no store, no channel import. `two adapters` prints the menu.
  `two adapters --json` adds bound device
  ids from the operator menu and omits secrets. It does not enable a slot.
  `console` is the in-repo window and stays off. `devices/climate/` is the climate package
  (ADR 0022) and stays default off.   `devices/tv/` is the television
  package (ADR 0029) and stays default off. `devices/vacuum/` is the
  vacuum package (ADR 0037) and stays default off. Do not add `export/` until the ADR
  for that slot.
- `topology.py` may read `config/deploy/topology.yaml`. No network.
- `edge.py` plans the watch mTLS edge (ADR 0020). `build_edge_plan` does
  no I/O. `issue_edge` writes a private CA and Caddyfile under the data
  directory and calls `openssl`. No store, no listen socket, no Python
  TLS library. CLI lazy-imports it from `two edge`.
- `setup.py` is the Mac mini plan (ADR 0019). `two setup --current` prints the optional split list (ADR 0013). No I/O, no
  network, no store. `two setup --plan` prints it. Apply I/O lives in
  `operator/`. CLI lazy-imports `two.operator` (not `two.runtime`).
- `runtime/` parses `models.lock`, emits the Ollama env contract, renders
  the launchd plist, and classifies Mac health from JSON. No network on
  the default unit-test path. `runtime/host.py` reads unified memory for
  `two profiles --recommend`. `runtime/poller.py` is the optional live
  Mac HTTP probe. `runtime/lan_bind.py` discovers a private Darwin bind.
- `operator/` is the interactive LAN path (ADR 0013): env apply, doctor,
  and `two up` supervisor. `operator/model.py` plans one `ollama pull`.
  `operator/recommend.py` joins the host probe to the catalog.
  `operator/menu.py` projects adapter slots and device ids.
  `operator/harness.py` installs the pinned DeepSeek Harness checkout
  for `two harness`. It does not run the agent loop. No store at
  import time. The API may call the menu. It does not call Ollama.
- `providers/` renders DSH settings from profile + topology + env and
  records the OpenAI-compatible HTTP contract. No network on the default
  path. Do not reimplement the DSH agent loop.
- `store/` is the SQLite WAL store (`open_store`). Schema v5 persists
  `work_nodes` / `work_edges`. Schema v6 persists projects and immutable
  config candidates (B14 slice 3). Schema v7 persists one `chat`
  harness session and `chat_turns` (B20). Schema v8 persists
  `home_action_turns` and `climate_approvals` (ADR 0022). Schema v9
  adds television tool names and `tv_approvals` (ADR 0029). Schema v10
  stores `route_slots`, `fanout_scope`, and `fanout_json` on
  `home_action_turns` (ADR 0030). Schema v11 adds the three vacuum
  tool names (ADR 0037). There is no vacuum approval table. Do not open databases from
  `cli.py` at import time. The `two api` subcommand lazy-imports
  `two.api.server`.
- `client.py` is the stdlib HTTP/Unix client for `/v1` (urllib / http.client,
  including AF_UNIX). CLI task subcommands lazy-import it. Parse bodies with
  `two.projection`. Accept an injectable request callable for in-process
  TestClient tests. Do not import the store, git, or Ollama.
- `cli_task.py` formats projections and dispatches `two task …`. No workflow
  policy. `cli_chat.py` dispatches `two chat send` / `two chat show`.
  It talks only to the control API.
- `two.api/` maps HTTP to `two.store` and `two.approvals`. It must not import
  `two.workspace` git operations or an Ollama client. Bind loopback or
  a Unix socket by default (ADR 0010). Request
  and projection bodies live in `two.projection`. `two.api.principal`
  derives identity and scopes; request bodies cannot elevate authority.
  `two.api.contract` owns correlation, ETags, and idempotency-key replay.
  `two.api.conversation` and `two.api.gui` build slice 2 read-only GUI
  projections (conversation, SSE, health, queue, repositories, diffs,
  artifacts). `two.api.config` validates typed repository/project
  candidates (slice 3). They must not call git, the shell, Ollama, or ACP.
- `approvals/` owns question/approval resolution and pause/resume/cancel
  lifecycle policy. Silence is never approval. Digests are immutable.
  It does not import git or the model.
- `scheduler/` owns the single local-model slot, lease reclaim, retry_wait,
  budgets clock, and Mac health mapping. It admits a queued chat turn,
  then a queued home-action turn, only when no coding lease is held.
  Inject a health probe and worker
  callback; do not call the network or ACP from this package.
- `channels/*` adapters must not import `workspace` or run git. Messaging
  adapters are deferred and none is selected. ADR 0015/B14 plans a
  first-party mobile API client, not another `channels.*` agent runtime.
  Device adapters live under `devices/`, not here. `devices/climate/`
  is ADR 0022 and stays default off. The binding transport is Home
  Assistant REST or ECHONET Lite (ADR 0027). `devices/tv/` is ADR 0029
  and stays default off. The transport is the Samsung local API.
  `devices/vacuum/` is ADR 0037 and stays default off. The transport is
  the Ecovacs Open API on the two official hosts.
- `routing/` classifies a transcript onto `chat` or an enabled device
  slot and plans a fan-out (ADR 0030). An obvious named-target command
  compiles the closed climate, television, or vacuum tool without the
  harness (ADR 0036). No store,
  no socket, no model client. Device packages add a route card;
  `routing/catalog.py` lists the shipped cards.
- Future `export/` (ADR 0012, B17) is the GitHub App handoff adapter.
  It is not implemented. Do not add `push` to `workspace/`. Do not put
  GitHub tokens in `worker/` or `channels/`.
- `validation/` loads `config/repositories/*.yaml` and
  `config/policies/default.yaml`, then runs gates in the task worktree.
  It never writes task lifecycle.
- `reporting/` formats gate fragments and Stage 8 final reports. It does
  not set lifecycle.
- `context/` persists structured task memory as JSON under
  `TWO_DATA_DIR/tasks/<id>/memory.json` and builds bounded retrieval
  packets (git, `rg`, optional LSP). No embeddings, SQLite, or DSH/Ollama
  calls. Budget policy lives in `config/policies/context.yaml`.
- `controller/` owns workflow stages, the persisted work-graph walker,
  repair/no-progress budgets, fresh review via `two.context.build_review_handoff`
  and `two.worker.plan_session`, and terminal status. Inject a worker and
  validation in tests. Production `two worker` drives this module
  (`two.recovery.drive`). It does not call the model or import an
  Ollama client.
- `graph/` is the no-I/O work-graph contract (ADR 0014): nodes, typed
  edges, linear compile, proposal apply, walker, digest, and node-scoped
  harness handoff. It must not import the store, ACP worker, or an
  Ollama client. Persistence is `two.store` schema v5. Do not add
  LangGraph or a second agent runtime.
- `worker/` supervises ACP children, the action ledger, and session resume.
  Default pytest uses a JSONL fixture child (ADR 0011). It must not set
  lifecycle `complete`. Local Qwen worker count is one. Profile `chat`
  resumes `harness_sessions` with no worktree and no tools. A tool
  request fails the chat turn and is not executed. Profile `home-action`
  may request the closed climate tools and, when those bindings are
  enabled, the closed television and vacuum tools. The control plane
  performs them and does not send `execute` to the child (ADR 0022,
  ADR 0029, ADR 0037).
  The climate transport is Home Assistant REST or ECHONET Lite (ADR 0027).
- `recovery/` owns architecture §12.5 startup recovery (`recover_startup`)
  and the `two scheduler` / `two worker` process loops. The scheduler
  idle poll is 1s (`IDLE_POLL_SECONDS`); lease heartbeat stays 10s.
  `run_worker` drives
  `WorkflowController` with `AcpPhaseWorker` and heartbeats the lease.
  It hooks `ActionLedger.recover` (no duplicate replay) and `Scheduler.start`
  (expired leases only). Human-paused tasks stay paused. Inject health
  and worktree probes in tests.
- `evals/` runs the architecture §18 corpus against `evals/` data.
  Offline by default. No Mac, production clones, or soak
  auto-pass. Duplicate side effects must stay zero.
- Use Pydantic v2 models with `extra="forbid"` for external payloads.
- `mypy --strict` applies to this tree. Add explicit return types.
- New `.py` files need the Apache 2.0 header and SPDX identifier.
