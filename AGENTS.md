# AGENTS.md

## Overview

DevFlow is the durable control plane around DeepSeek Harness. Qwen 3.8 stays on
a dedicated Mac inference host. This repository implements DevFlow; it does not
reimplement the harness agent loop. Foundation scaffold only: types, manifest,
CLI help, config templates. No SQLite store, ACP worker, or Slack adapter yet.

## Stack

Python 3.12, uv, ruff, mypy --strict on `src/devflow`, pytest, Pydantic v2.
Do not add Poetry, pip-tools, or pre-commit unless an ADR says so.

## Commands

```bash
uv sync --dev
make fmt
make lint
make typecheck
make test
make ci
uv run devflow --help
uv run devflow profiles
uv run devflow topology
```

`make ci` is the required gate. Validation commands for this repo are also
listed in `config/repositories/devflow.yaml`.

## Layout

- `src/devflow/` — Python only. Package implementations live here.
- `tests/` — unit, contract, integration. Unit tests must stay offline.
- `config/` — templates and repository profiles. No secrets.
- `scripts/` — operational stubs until later phases.
- `docs/` — architecture and ADRs. `docs/architecture.md` is canonical.
  `docs/setup.md` is the living operator guide.
- `deploy/compose/` — Linux control-plane packaging. No Ollama image.
- `evals/` — future evaluation corpus. No production repository clones.

## Conventions

- Keep the src layout. Public types stay in `types.py` and `manifest.py` with
  no I/O.
- SQLite belongs in `store/` only.
- `cli.py` and `channels.slack` stay thin. They must not contain workflow
  policy or git worktree logic.
- New source files need the Apache 2.0 header and
  `SPDX-License-Identifier: Apache-2.0`.

## Boundaries

### Always

- Treat worktree isolation as the design (implement it when that phase lands).
- Add or update deterministic tests for code you change.
- Update this file in the same PR as command or layout changes.
- Update `docs/setup.md` (and its status table) when install, topology,
  profiles, or ports change.
- Keep `LICENSE` and `NOTICE` in the tree.

### Ask first

- New runtime dependency
- Cloud provider or paid-model route
- Slack scope changes
- Task-manifest field changes
- Changing the *default* inference profile or default topology
  (per-host `colocated` on a large Mac is fine)
- Adding a vector database

### Never

- Merge, push, release, or deploy from agent-authored automation
- Bind inference or the DevFlow API to a public interface
- Commit `.env`, tokens, model weights, or real Mac addresses
- Edit the canonical checkout of a *target* repository
- Treat a model self-report as task completion
- Send full source, raw trajectories, or verbose logs to Slack
- Reimplement the DeepSeek Harness agent loop inside DevFlow

## Architecture authority

`docs/architecture.md` wins. If code and spec disagree, stop and write an ADR
under `docs/adrs/`. Do not rewrite the spec to match an accidental
implementation.

## Security

Secrets live in environment variables only. The dummy key `ollama` is not a
secret. Slack tokens must never reach DeepSeek Harness, Qwen, or target repos.

## PR

Use conventional commits. Leave `make ci` green. Do not invent a second
architecture.
