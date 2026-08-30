# src/two

Python package for the Majesta Two control plane.

- Keep enums in `types.py` and the task request in `manifest.py`. No I/O in
  those modules.
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
- `api/` maps HTTP to `two.store` and `two.approvals`. It must not import
  `two.workspace` git operations, `two.channels.slack`, or an Ollama
  client. Bind loopback or a Unix socket by default (ADR 0010).
- `approvals/` owns question/approval resolution and pause/resume/cancel
  lifecycle policy. Silence is never approval. Digests are immutable.
  It does not import git, Slack, or the model.
- `channels/*` adapters must not import `workspace` or run git. Slack is
  the MVP adapter only.
- `validation/` loads `config/repositories/*.yaml` and
  `config/policies/default.yaml`, then runs gates in the task worktree.
  It never writes task lifecycle. `reporting/` formats gate fragments only.
- `context/` persists structured task memory as JSON under
  `TWO_DATA_DIR/tasks/<id>/memory.json` and builds bounded retrieval
  packets (git, `rg`, optional LSP). No embeddings, SQLite, or DSH/Ollama
  calls. Budget policy lives in `config/policies/context.yaml`.
- `controller` does not call the model. `worker` will own ACP later.
- Use Pydantic v2 models with `extra="forbid"` for external payloads.
- `mypy --strict` applies to this tree. Add explicit return types.
- New `.py` files need the Apache 2.0 header and SPDX identifier.
