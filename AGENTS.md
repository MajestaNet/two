# AGENTS.md

## Overview

Majesta Two is a fully local, self-building system (ADR 0017). One local
installation of this repository is the development client and the only
development subject. DeepSeek Harness remains the pinned inner model/tool
loop and is not reimplemented here. The Mac mini is the always-on host for Qwen 3.8, this scaffold, and
DeepSeek Harness (ADR 0019). The installer selects the inference profile.
A later wearable or device request resumes a persisted harness profile
(`chat` or `home-action`), not the self-build profile. One inference
runs at a time. This repository is not a messenger product
and it does not develop unrelated repositories. The CLI is the local surface
today; ADR 0015/B14 plans a secure first-party mobile client over the same
API. The climate device package is in-repo and default off (ADR 0022).
A binding may use Home Assistant REST or ECHONET Lite (ADR 0027).
The television package is in-repo and default off (ADR 0029).
The vacuum package is in-repo and default off (ADR 0038). Its transport
is the Ecovacs Open API on the two official hosts.
Speech remains specified and not implemented.
The SQLite WAL store (`two.store`)
persists tasks, events, leases, the work graph (schema v5),
projects/config candidates (schema v6), and the chat harness session
plus turn log (schema v7), and home-action climate turns
(schema v8), television turns (schema v9), the utterance
route plus device fan-out plan (schema v10), and the three vacuum
tool names (schema v11).
The control API (`two.api`, ADR 0010) and approvals (`two.approvals`) are
the client contract. The scheduler owns the single local-model slot; the
ACP worker supervises a DeepSeek Harness child with an at-most-once ledger.
The workflow controller owns stage policy, budgets, fresh review, the
persisted work-graph walker, and terminal status. Messaging adapters are
optional and not implemented. `two adapters` prints the install menu
(ADR 0021). Only the CLI slot is enabled. Device and GitHub export paths
are reserved and are not packages.
GitHub export of task branches is post-MVP (ADR 0012) and is not implemented.

## Stack

Python 3.12, uv, ruff, mypy --strict on `src/two`, pytest, Pydantic v2,
FastAPI + uvicorn for the control API (ADR 0010).
System `rg` (ripgrep) is used by the context broker; tests skip that path
if it is missing. Do not add Poetry, pip-tools, or pre-commit unless an
ADR says so.

## Commands

```bash
uv sync --dev
make fmt
make lint
make typecheck
make test
make ci
make eval-offline
uv run two --help
uv run two profiles
uv run two profiles --recommend
uv run two model status
uv run two model pull --profile ID
uv run two harness status
uv run two harness install
uv run two topology
uv run two adapters
uv run two setup --plan
uv run two setup --ollama-url URL
uv run two up
uv run two down
uv run two doctor
uv run two api
uv run two edge plan --listen PRIVATE-LAN-IP
uv run two edge issue --listen PRIVATE-LAN-IP
uv run two scheduler
uv run two worker
uv run two task --help
uv run two task submit MANIFEST.yaml
uv run two task show ID
uv run two task message ID --text ...
uv run two task pause ID
uv run two task resume ID
uv run two task cancel ID
uv run two task approve ID APPROVAL_ID --digest ...
uv run two task reject ID APPROVAL_ID --digest ...
uv run two task answer ID QUESTION_ID --text ...
uv run two task report ID
uv run two chat send --text TEXT
uv run two chat show TURN_ID
uv run two climate send --text TEXT
uv run two climate show TURN_ID
uv run two climate approve TURN_ID --digest DIGEST
uv run two climate reject TURN_ID --digest DIGEST
uv run two route send --text TEXT
uv run two route show TURN_ID
uv run two tv send --text TEXT
uv run two tv show TURN_ID
uv run two tv approve TURN_ID --digest DIGEST
uv run two tv reject TURN_ID --digest DIGEST
uv run two tv pair --set SET
uv run two tv apps --set SET
uv run two vacuum send --text TEXT
uv run two vacuum show TURN_ID
uv run two vacuum robots
uv run python -m two.providers --check
./scripts/smoke-test.sh --dry-run
./scripts/bootstrap-dev-host.sh --dry-run
./scripts/run-evals.sh --offline
```

`make ci` is the required gate. Validation commands for this repo are also
listed in `config/repositories/two.yaml`. `npm test` in `apps/console` checks
the local operator window and is not part of that gate.

## Layout

- `apps/console/` — local operator window (ADR 0031, ADR 0032, ADR 0033, ADR 0034, ADR 0035, ADR 0037). Electron,
  loopback only, default off. It calls `two up`, `two down`,
  `two profiles --recommend`, `two model`, `two harness`, and `POST /v1/voice/turns`.
  The voice profile defaults to unset. `chat` and `home-action` are the
  only explicit choices.
  Opening the window starts the control plane when it is not already running.
  Closing the window hides it. The menu bar opens it again. Quit of the
  window process does not stop the control plane or an Ollama serve this
  window started.
  A packaged build (`npm run package`) carries this control plane in a
  relocatable virtualenv. A checkout still uses `uv run two`. DeepSeek
  Harness is not baked into the package. The Server page checks for `dsh`
  and can install the pinned release, including Node 22 when it is missing.
  When `TWO_DATA_DIR` is unset, the window uses the platform data directory.
  The main process may install the official Ollama archive when no binary
  is found, or locate an existing `ollama` and run `--version`, `list`,
  `serve`, and `pull` on `127.0.0.1:11434`. The model list includes the
  16 GB catalog rows. One typed Ollama tag can be pulled and loaded.
  The Model page can select OpenRouter, defaulting to DeepSeek V4 Flash,
  and sign in with PKCE. The key stays in the data directory. Model text
  in the window does not cite an ADR. The renderer does not spawn
  a process. The API process does not call Ollama. `npm test` there is not
  part of `make ci`.
- `src/two/` — Python only. Package implementations live here.
  `src/two/setup.py` is the Mac mini setup plan (ADR 0019). `two setup --current` still prints the optional split list (ADR 0013).
  `two setup --plan` prints it. `two setup --ollama-url` writes env via
  `two.operator`. `two doctor` / `two up` / `two down` are B18.
  `src/two/runtime/` holds the Mac lock file, Ollama env/bind policy,
  launchd rendering, health classification, and the optional Mac HTTP poller.
  `src/two/context/` is the context broker and structured task memory
  (git, rg, optional LSP; JSON under `TWO_DATA_DIR`).
 `src/two/store/` is the SQLite WAL store (tasks, events, leases, work
 graph). CLI does not open it at import time. Schema v5 adds `work_nodes`
 and `work_edges` (v4 is B14 idempotency). Schema v6 adds `projects`,
 `repository_config_state`, `config_candidates`, and `config_approvals`
 (B14 slice 3). Schema v7 adds `harness_sessions` and `chat_turns` (B20).
 Schema v8 adds `home_action_turns` and `climate_approvals` (B21).
 Schema v9 adds television tool names and `tv_approvals`. Schema v10
 stores the utterance route and fan-out plan. Schema v11 adds the three
 vacuum tool names (ADR 0038). There is no vacuum approval table.
 A chat turn is not a task and never takes a coding lease. A home-action
 turn is not a task either.
 `src/two/api/` is the channel-neutral control API (FastAPI; ADR 0010).
 `two api` lazy-imports it so `two profiles` does not load the store.
 Additive B14 slice 2 routes include conversation, SSE, aggregate health,
 queue, repository/project reads, and bounded diff/artifacts.
 `GET /v1/system/adapters` lists catalog slots and bound device ids. Slice 3 adds
 persisted `POST /v1/projects` and immutable config-candidate activate
 routes. `two.api.config` validates typed, non-secret fields.
 Principal/scope checks live in `two.api.principal`; correlation, ETag,
 and idempotency helpers live in `two.api.contract`. Conversation and
 SSE mapping live in `two.api.conversation`; health/queue/repo/diff/artifact
 builders live in `two.api.gui`.
 `src/two/adapters.py` loads `config/adapters/catalog.yaml` (ADR 0021).
 `two adapters` prints it and writes nothing. `two adapters --json`
 adds bound device ids and omits secrets. Only the `cli` slot is
  enabled. `console` is the local window (`apps/console`, ADR 0031, ADR 0032, ADR 0034, ADR 0035, ADR 0037),
 shipped and off, and it resumes `chat` only. `watch` and `mobile`
 are clients at `contract`. `climate`
 is shipped and off (`src/two/devices/climate/`, ADR 0022, ADR 0027).
 `tv` is shipped and off (`src/two/devices/tv/`, ADR 0029).
 `vacuum` is shipped and off (`src/two/devices/vacuum/`, ADR 0038).
 The kind-level `device` slot and `github` (`src/two/export/`) stay
 reserved. Do not enable a slot by adding a directory.
 `src/two/routing/` chooses `chat` or a device slot for a transcript
 that omits the profile, expands `all` across bound targets
 (ADR 0030), and compiles an obvious named-target climate, television,
 or vacuum command without the harness (ADR 0036). It does not call a device or
 load a model. The optional `TWO_ROUTE_MODEL=1` tie-break runs in the
 worker on the resident model.
 `src/two/edge.py` is the watch edge plan (ADR 0020): private CA,
 Caddy mutual TLS, loopback upstream. `two edge plan` writes nothing.
 `two edge issue` writes under `$TWO_DATA_DIR/edge`. The watch principal
 `client:watch` cannot submit `self-build`. The native app spec is
 `docs/watch-client.md` and is not an Xcode project in this repo.
 `src/two/projection.py` is the /v1 JSON contract (no FastAPI). CLI and
 adapters import it instead of inventing a second schema. It includes
 `SystemCapabilities`, additive `TaskProjection.revision`, and slice 2
 GUI projection types. `TaskProjection.graph` may be null (B19).
  `src/two/client.py` is the stdlib HTTP/Unix control-API client (B13).
  Task subcommands in `cli.py` / `cli_task.py` and `two chat` in
  `cli_chat.py` lazy-import it the same way `two api` lazy-imports the
  server. Tests inject FastAPI TestClient.
  `src/two/approvals/` is durable questions, approvals, and cooperative
  pause/resume/cancel (first-writer-wins; silence is never approval).
  `src/two/scheduler/` owns the single local-model queue slot, lease
  heartbeat/reclaim, retry_wait backoff, and Mac health mapping. It admits
  one queued chat turn only when no coding lease is held.
  `src/two/worker/` supervises a pinned ACP child, the action ledger, and
  session resume, including the no-tools `chat` profile. Production
  `home-action` uses that same `dsh --profile acp` client (ADR 0028) and
  performs the closed climate, television, and vacuum tools in this
  process. Default tests use
  a fake child (`@pytest.mark.live_dsh` is opt-in).
  `src/two/controller/` drives the durable workflow, binds budgets, walks
  the persisted work graph, starts a fresh review session, and is the only
  writer of terminal status.
  `src/two/graph/` is the no-I/O work-graph contract (ADR 0014): nodes,
  typed edges, walker, and node-scoped harness handoff. SQLite persistence
  and controller wiring live in `two.store` / `two.controller`. Do not put
  a second agent runtime here.
  `src/two/reporting/` formats gate fragments and Stage 8 final reports.
  `src/two/recovery/` is development-host startup recovery (architecture
  §12.5) and the `two scheduler` / `two worker` process loops.
  `src/two/evals/` runs the architecture §18 corpus (offline default;
  `TWO_LIVE_EVAL=1` for live Mac cases). Soaks are not auto-passed.
  Future: `src/two/export/` is the GitHub App handoff adapter (ADR 0012,
  B17). Not implemented. Do not put `push` in `workspace` or GitHub
  tokens in `channels` / DSH.
- `tests/` — unit, contract, integration. Unit tests must stay offline.
- `config/` — templates and repository profiles. No secrets.
- `scripts/` — `bootstrap-mac.sh`, `health-check.sh`, and
 `soak-inference.sh` implement Phase 1 dry-run/live Mac helpers.
 `scripts/lib/two-python.sh` is the shared interpreter (`uv run` or a
 venv that can import PyYAML; never system `python3`).
 `bootstrap-dev-host.sh` creates `TWO_DATA_DIR` / worktrees (mode 0700)
 and prints the Compose plan (`--dry-run` for CI).
- `docs/` — architecture and ADRs. `docs/architecture.md` is canonical.
  `docs/setup.md` is the living operator guide. `docs/local-16k.md` is
  24 GB / 16K operator guidance. `docs/backlog/` is the implementation
  tracker (one item per file; agent prompts at the end).
- `deploy/compose/` — Linux control-plane packaging (`api`, `scheduler`,
 `worker`). No Ollama image.
- `deploy/systemd/` — optional user-unit templates. Compose is the default
  unattended packaging.
- `evals/` — evaluation corpus (architecture §18). Tasks, tiny synthetic
  fixtures, expected overlays, and promotion checklists. No production
  clones. Offline runner: `make eval-offline` / `python -m two.evals`.
  Live cases need `TWO_LIVE_EVAL=1`. Soaks stay operator-owned
  (`evals/PROMOTION.md`); CI must not mark them passed.
  `src/two/evals/` is the runner.

## Conventions

- Keep the src layout. Public types stay in `types.py`, `manifest.py`, and
  `projection.py` with no I/O. `projection.py` is the /v1 client contract.
- SQLite belongs in `store/` only.
- `cli.py` and any `channels.*` adapter stay thin. They must not contain
  workflow policy or git worktree logic. Do not put vendor UX in
  `controller`. Do not put GitHub push in `channels` or `workspace`
  (ADR 0012).
- New source files need the Apache 2.0 header and
  `SPDX-License-Identifier: Apache-2.0`.

## Boundaries

### Always

- Treat worktree isolation as the design (`two.workspace`). Run
  validation in the worktree (`two.validation`), never the canonical
  checkout. The development subject is this installation (ADR 0017);
  adoption of a worktree onto the executing tree is a separate
  controller operation at process restart, and it is not implemented.
  Retrieval and task memory live in `two.context` (git, `rg`,
  optional LSP; no embeddings).
- Add or update deterministic tests for code you change.
- Update this file in the same PR as command or layout changes.
- Update `docs/setup.md` (and its status table) when install, topology,
  profiles, or ports change.
- Keep `LICENSE` and `NOTICE` in the tree.

### Ask first

- New runtime dependency
- Cloud provider or paid-model route
- New messaging adapter
- A concrete home, wearable, or other device adapter (the protocol needs
  its own ADR under ADR 0017)
- GitHub App, source-control export, or a local git forge (ADR 0012)
- Task-manifest field changes
- Changing the *default* inference profile or default topology
  (the default topology is `colocated` on the Mac mini, ADR 0019)
- Adding a vector database

### Never

- Merge, push to shared branches, release, or deploy from the agent
  loop (DSH, worker, `two.workspace`). Approved GitHub export of
  `agent/<task-id>` is ADR 0012 / B17 and is not implemented.
- Bind inference or the Majesta Two API to a public interface
- Commit `.env`, tokens, model weights, or real Mac addresses
- Edit the canonical checkout of a *target* repository
- Treat a model self-report as task completion
- Send full source, raw trajectories, or verbose logs to any messenger
- Reimplement the DeepSeek Harness agent loop inside Majesta Two

## Architecture authority

`docs/architecture.md` wins. If code and spec disagree, stop and write an ADR
under `docs/adrs/`. Do not rewrite the spec to match an accidental
implementation.

## Security

Secrets live in environment variables only. The dummy key `ollama` is not a
secret. Messenger tokens and GitHub App tokens must never reach DeepSeek
Harness, Qwen, or target repos.

## PR

Use conventional commits. Leave `make ci` green. Do not invent a second
architecture.
