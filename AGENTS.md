# AGENTS.md

## Overview

Majesta Two is the durable **backend** around DeepSeek Harness. Qwen 3.8 stays on
a dedicated Mac inference host. This repository is not a Slack (or other
messenger) product. Slack is the MVP optional adapter. The SQLite WAL store (`two.store`) persists tasks, events, and leases.
The control API (`two.api`, ADR 0010) and approvals (`two.approvals`) are
the client contract. The scheduler owns the single local-model slot; the
ACP worker supervises a DeepSeek Harness child with an at-most-once ledger.
The workflow controller owns stage policy, budgets, fresh review, and
terminal status. Slack remains the optional adapter and is not implemented.
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
uv run two topology
uv run two api
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
uv run python -m two.providers --check
./scripts/smoke-test.sh --dry-run
./scripts/bootstrap-dev-host.sh --dry-run
./scripts/run-evals.sh --offline
```

`make ci` is the required gate. Validation commands for this repo are also
listed in `config/repositories/two.yaml`.

## Layout

- `src/two/` — Python only. Package implementations live here.
  `src/two/runtime/` holds the Mac lock file, Ollama env/bind policy,
  launchd rendering, health classification, and the optional Mac HTTP poller.
  `src/two/context/` is the context broker and structured task memory
  (git, rg, optional LSP; JSON under `TWO_DATA_DIR`).
  `src/two/store/` is the SQLite WAL store (tasks, events, leases). CLI
  does not open it at import time.
  `src/two/api/` is the channel-neutral control API (FastAPI; ADR 0010).
  `two api` lazy-imports it so `two profiles` does not load the store.
  `src/two/projection.py` is the /v1 JSON contract (no FastAPI). CLI and
  adapters import it instead of inventing a second schema.
  `src/two/client.py` is the stdlib HTTP/Unix control-API client (B13).
  Task subcommands in `cli.py` / `cli_task.py` lazy-import it the same way
  `two api` lazy-imports the server. Tests inject FastAPI TestClient.
  `src/two/approvals/` is durable questions, approvals, and cooperative
  pause/resume/cancel (first-writer-wins; silence is never approval).
  `src/two/scheduler/` owns the single local-model queue slot, lease
  heartbeat/reclaim, retry_wait backoff, and Mac health mapping.
  `src/two/worker/` supervises a pinned ACP child, the action ledger, and
  session resume. Default tests use a fake child (`@pytest.mark.live_dsh`
  is opt-in).
  `src/two/controller/` drives the durable workflow, binds budgets, starts a
  fresh review session, and is the only writer of terminal status.
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
  `bootstrap-dev-host.sh` creates `TWO_DATA_DIR` / worktrees (mode 0700)
  and prints the Compose plan (`--dry-run` for CI).
- `docs/` — architecture and ADRs. `docs/architecture.md` is canonical.
  `docs/setup.md` is the living operator guide. `docs/backlog/` is the
  implementation tracker (one item per file; agent prompts at the end).
- `deploy/compose/` — Linux control-plane packaging (`api`, `scheduler`,
  `worker`; optional `slack` profile stub). No Ollama image.
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
  checkout. Retrieval and task memory live in `two.context` (git, `rg`,
  optional LSP; no embeddings).
- Add or update deterministic tests for code you change.
- Update this file in the same PR as command or layout changes.
- Update `docs/setup.md` (and its status table) when install, topology,
  profiles, or ports change.
- Keep `LICENSE` and `NOTICE` in the tree.

### Ask first

- New runtime dependency
- Cloud provider or paid-model route
- New messaging adapter or Slack scope changes
- GitHub App, source-control export, or a local git forge (ADR 0012)
- Task-manifest field changes
- Changing the *default* inference profile or default topology
  (per-host `colocated` on a large Mac is fine)
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
